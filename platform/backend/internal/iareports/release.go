package iareports

// Release a reviewed report to country leadership (release_leadership →
// reports.release_to_leadership): its reviewer releases the whole frozen
// evidence with the words and recommendations; the Country Director is
// told and responds to each recommendation.

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
)

const eventReleased = "ia.report.released"

func ownerLabel(role string) string {
	for _, o := range ActionOwners {
		if o[0] == role {
			return o[1]
		}
	}
	return role
}

// releaseToLeadership is reports.release_to_leadership.
func (r Reports) releaseToLeadership(ctx context.Context, p auth.Principal, id string) (Saved, error) {
	now := r.now()
	var x *report
	recommendations := 0
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		var err error
		if x, err = r.visible(ctx, tx, p, id, true); err != nil {
			return err
		}
		if x == nil {
			return refuse("That impact report is not in your country.")
		}
		if x.status != "reviewed" {
			return refuse("Only a reviewed report is released to leadership.")
		}
		var reviewer, hash, supersedes string
		var snapshot []byte
		if err := tx.QueryRow(ctx, `SELECT COALESCE(reviewed_by_id, ''), snapshot_hash, evidence_snapshot::text, COALESCE(supersedes_id, '')
FROM impact_report WHERE id = $1`, id).Scan(&reviewer, &hash, &snapshot, &supersedes); err != nil {
			return fmt.Errorf("iareports: the report to release: %w", err)
		}
		if reviewer != p.UserID {
			return refuse("The person who reviewed the report releases it.")
		}
		recs, err := recommendationPayload(ctx, tx, id)
		if err != nil {
			return err
		}
		recommendations = len(recs)
		narrative, _ := json.Marshal(map[string]any{"methodology": x.methodology, "findings": x.findings, "limitations": x.limitations})
		listed, _ := json.Marshal(recs)
		payload := `{"profile": "leadership", "snapshot": ` + string(snapshot) + `, "narrative": ` + string(narrative) +
			`, "recommendations": ` + string(listed) + `}`
		var release string
		if err := tx.QueryRow(ctx, `INSERT INTO impact_report_release (id, created_at, updated_at, audience, redaction_profile, rendered_payload,
  status, requested_by_id, approved_by_id, approved_at, released_by_id, released_at, revoked_reason, report_id, school_id)
VALUES ($1, $2, $2, 'leadership', 'leadership', $3::jsonb, 'released', $4, $4, $2, $4, $2, '', $5, NULL)
ON CONFLICT (report_id, audience, school_id) DO UPDATE SET redaction_profile = EXCLUDED.redaction_profile,
  rendered_payload = EXCLUDED.rendered_payload, status = EXCLUDED.status, requested_by_id = EXCLUDED.requested_by_id,
  approved_by_id = EXCLUDED.approved_by_id, approved_at = EXCLUDED.approved_at, released_by_id = EXCLUDED.released_by_id,
  released_at = EXCLUDED.released_at, revoked_reason = '', updated_at = EXCLUDED.updated_at
RETURNING id`, cuid.New(), now, payload, p.UserID, id).Scan(&release); err != nil {
			return fmt.Errorf("iareports: releasing the report: %w", err)
		}
		if _, err := tx.Exec(ctx, `UPDATE impact_report SET status = 'released', updated_at = $2 WHERE id = $1`, id, now); err != nil {
			return fmt.Errorf("iareports: marking the report released: %w", err)
		}
		superseded, err := r.supersedePrior(ctx, tx, p, id, supersedes, []string{"reviewed", "released"}, now)
		if err != nil {
			return err
		}
		_, err = audit.Append(ctx, tx, reportAudit("ia.report.released", id, p, x.country, x.version, "released", hash,
			map[string]any{"audience": "leadership", "release_id": release, "supersedes": superseded}), now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	directors, err := r.countryDirectors(ctx, x.country)
	if err != nil && r.Logger != nil {
		r.Logger.Warn("iareports: the Country Directors were not found", "report", x.id, "err", err)
	}
	to := []activities.NoticeTo{}
	for _, d := range directors {
		to = append(to, activities.NoticeTo{UserID: d, Route: PagePath + x.id + "/#recommendations", Label: "Read Report"})
	}
	title := "Impact report released: " + x.title
	if len([]rune(title)) > 200 {
		title = string([]rune(title)[:200])
	}
	if len(to) > 0 {
		if err := activities.SendNotices(ctx, r.DB, r.Push, r.Live, r.Logger, r.now(), x.id, "", activities.Origin{},
			activities.Notice{Title: title, Body: fmt.Sprintf("%s · %d recommendation(s) wait for your response.",
				iapages.PeriodLabel(x.fy, x.start, x.end), recommendations),
				Event: eventReleased, Category: "ia", ContextType: "ImpactReport", Priority: "high"}, to); err != nil && r.Logger != nil {
			r.Logger.Warn("iareports: the Country Director was not told", "report", x.id, "err", err)
		}
	}
	return Saved{Message: "Released to country leadership; the Country Director has been told.", ReportID: id}, nil
}

// recommendationPayload is reports.recommendation_payload.
func recommendationPayload(ctx context.Context, tx pgx.Tx, id string) ([]map[string]any, error) {
	rows, err := tx.Query(ctx, `SELECT id, text, owner_role, due_date FROM impact_report_recommendation WHERE report_id = $1
ORDER BY due_date, created_at`, id)
	if err != nil {
		return nil, fmt.Errorf("iareports: the recommendations: %w", err)
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var rid, text, owner string
		var due *time.Time
		if err := rows.Scan(&rid, &text, &owner, &due); err != nil {
			return nil, fmt.Errorf("iareports: a recommendation: %w", err)
		}
		day := ""
		if due != nil {
			day = due.Format(time.DateOnly)
		}
		out = append(out, map[string]any{"id": rid, "text": text, "owner_role": owner, "owner_label": ownerLabel(owner), "due_date": day})
	}
	return out, rows.Err()
}

// supersedePrior is reports._supersede_prior: the version this one corrects
// is superseded when it is in one of the statuses given.
func (r Reports) supersedePrior(ctx context.Context, tx pgx.Tx, p auth.Principal, id, prior string, when []string, now time.Time) (any, error) {
	if prior == "" {
		return nil, nil
	}
	x, err := scanReport(tx.QueryRow(ctx, `SELECT `+reportColumns+` FROM impact_report r WHERE r.id = $1 AND r.status = ANY($2) FOR UPDATE`, prior, when))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("iareports: the version it corrects: %w", err)
	}
	if _, err := tx.Exec(ctx, `UPDATE impact_report SET status = 'superseded', updated_at = $2 WHERE id = $1`, x.id, now); err != nil {
		return nil, fmt.Errorf("iareports: superseding the earlier version: %w", err)
	}
	var hash string
	_ = tx.QueryRow(ctx, `SELECT snapshot_hash FROM impact_report WHERE id = $1`, x.id).Scan(&hash)
	if _, err := audit.Append(ctx, tx, reportAudit("ia.report.superseded", x.id, p, x.country, x.version, "superseded", hash,
		map[string]any{"superseded_by": id}), now); err != nil {
		return nil, err
	}
	return x.id, nil
}

// countryDirectors is role_recipients(CD, country).
func (r Reports) countryDirectors(ctx context.Context, country string) ([]string, error) {
	rows, err := r.DB.Query(ctx, `SELECT u.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE 'CountryDirector' = ANY(u.roles) AND u.is_active AND u.deleted_at IS NULL AND sp.country = $1 ORDER BY u.id`, country)
	if err != nil {
		return nil, fmt.Errorf("iareports: the Country Directors: %w", err)
	}
	return pgx.CollectRows(rows, pgx.RowTo[string])
}

// releaseDrawer is release_drawer for the leadership release; served is
// false for a donor version or a school brief, still the existing page's.
func (r Reports) releaseDrawer(ctx context.Context, p auth.Principal, reportID, id string) (*screensv1.PageDrawer, bool, error) {
	x, err := r.visible(ctx, r.DB, p, reportID, false)
	if err != nil || x == nil {
		if err == nil {
			err = errNoReport
		}
		return nil, true, err
	}
	var audience, status, measured, total string
	var released *time.Time
	err = r.DB.QueryRow(ctx, `SELECT audience, status, released_at, COALESCE(rendered_payload->'snapshot'->'cohort'->>'measured', '0'),
  COALESCE(rendered_payload->'snapshot'->'cohort'->>'total', '0') FROM impact_report_release WHERE id = $1 AND report_id = $2`, id, reportID).
		Scan(&audience, &status, &released, &measured, &total)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, errNoReport
	}
	if err != nil {
		return nil, true, fmt.Errorf("iareports: the release: %w", err)
	}
	if audience != "leadership" {
		if p.ActiveRole == "RegionalVicePresident" && audience != "donor" {
			return nil, true, errNoReport
		}
		return nil, false, nil
	}
	if p.ActiveRole == "RegionalVicePresident" {
		return nil, true, errNoReport
	}
	label := map[string]string{"pending_approval": "Awaiting approval", "approved": "Approved", "released": "Released", "revoked": "Revoked"}[status]
	day := ""
	if released != nil {
		day = released.In(kampala).Format("2 Jan 2006 15:04")
	}
	return &screensv1.PageDrawer{Title: "Leadership release", Subtitle: "Country leadership · " + label, HasRequired: true, CancelLabel: "Cancel",
		Items: []*screensv1.DrawerItem{
			{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: []*screensv1.PageFact{
				{Label: "Released", Value: orDash(day)}, {Label: "Project cohort", Value: measured + " of " + total + " enrolments measured"}}}}},
			note("The whole report and its evidence, as released to the country's leadership."),
		}}, true, nil
}

var kampala = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return z
}()

// kampalaDay is timezone.localdate().
func kampalaDay(t time.Time) time.Time {
	l := t.In(kampala)
	return time.Date(l.Year(), l.Month(), l.Day(), 0, 0, 0, 0, time.UTC)
}

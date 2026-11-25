package iareports

// Submit a draft for review, freezing its evidence (report_submit →
// reports.submit_report), and withdraw a draft or a submitted report
// (report_withdraw → withdraw_report): the page's two one-button forms.

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
)

const eventReviewRequested = "ia.report.review_requested"

// submittable is _assert_submittable.
func submittable(x *report) error {
	for _, f := range [][2]string{{x.methodology, "the methodology"}, {x.findings, "the findings"},
		{x.limitations, "the limitations: what this evidence cannot show"}} {
		if strings.TrimSpace(f[0]) == "" {
			return refuse("State %s before submitting.", f[1])
		}
	}
	return nil
}

// submit is reports.submit_report.
func (r Reports) submit(ctx context.Context, p auth.Principal, id string) (Saved, error) {
	now := r.now()
	var x *report
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		var err error
		if x, err = r.ownDraft(ctx, tx, p, id); err != nil {
			return err
		}
		if err := submittable(x); err != nil {
			return err
		}
		var project, supersedes string
		if err := tx.QueryRow(ctx, `SELECT COALESCE(pr.name, ''), COALESCE(r.supersedes_id, '') FROM impact_report r
LEFT JOIN project pr ON pr.id = r.project_id WHERE r.id = $1`, id).Scan(&project, &supersedes); err != nil {
			return fmt.Errorf("iareports: the report's project: %w", err)
		}
		snapshot, err := iapages.ReportSnapshot(ctx, tx, p, iapages.SnapshotReport{ID: x.id, Title: x.title, Country: x.country,
			FY: x.fy, ProjectID: x.project, Project: project, Version: x.version, Start: x.start, End: x.end,
			ProgrammeAreas: x.areas}, now)
		if err != nil {
			return err
		}
		snapshot["generated_at"] = iapages.DjangoTime(now)
		canonical, err := audit.StableStringify(snapshot)
		if err != nil {
			return fmt.Errorf("iareports: the snapshot's hash: %w", err)
		}
		sum := sha256.Sum256([]byte(canonical))
		hash := hex.EncodeToString(sum[:])
		stored, err := iapages.PythonJSON(snapshot)
		if err != nil {
			return fmt.Errorf("iareports: writing the snapshot: %w", err)
		}
		if _, err := tx.Exec(ctx, `UPDATE impact_report SET evidence_snapshot = $2::jsonb, snapshot_hash = $3, status = 'submitted',
  submitted_at = $4, updated_at = $4 WHERE id = $1`, id, string(stored), hash, now); err != nil {
			return fmt.Errorf("iareports: freezing the evidence: %w", err)
		}
		var superseded any
		if supersedes != "" {
			var prior report
			prior, err = scanReport(tx.QueryRow(ctx, `SELECT `+reportColumns+` FROM impact_report r
WHERE r.id = $1 AND r.status IN ('returned', 'withdrawn') FOR UPDATE`, supersedes))
			switch {
			case errors.Is(err, pgx.ErrNoRows):
			case err != nil:
				return fmt.Errorf("iareports: the version it corrects: %w", err)
			default:
				if _, err := tx.Exec(ctx, `UPDATE impact_report SET status = 'superseded', updated_at = $2 WHERE id = $1`, prior.id, now); err != nil {
					return fmt.Errorf("iareports: superseding the earlier version: %w", err)
				}
				var priorHash string
				_ = tx.QueryRow(ctx, `SELECT snapshot_hash FROM impact_report WHERE id = $1`, prior.id).Scan(&priorHash)
				if _, err := audit.Append(ctx, tx, reportAudit("ia.report.superseded", prior.id, p, prior.country, prior.version,
					"superseded", priorHash, map[string]any{"superseded_by": id}), now); err != nil {
					return err
				}
				superseded = prior.id
			}
		}
		cohort, _ := snapshot["cohort"].(map[string]any)
		rows, _ := snapshot["rows"].([]any)
		_, err = audit.Append(ctx, tx, reportAudit("ia.report.submitted", id, p, x.country, x.version, "submitted", hash,
			map[string]any{"rows": len(rows), "measured": cohort["measured"], "supersedes": superseded}), now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	r.notifyReviewers(ctx, x)
	return Saved{Message: "Submitted. The evidence is frozen and a second reviewer has been told.", ReportID: id}, nil
}

// notifyReviewers is _notify_reviewers: the country's other IA officers,
// else its Country Director. A notice never undoes the transition.
func (r Reports) notifyReviewers(ctx context.Context, x *report) {
	ids, err := r.reviewerIDs(ctx, x)
	if err != nil || len(ids) == 0 {
		if err != nil && r.Logger != nil {
			r.Logger.Warn("iareports: the reviewers were not found", "report", x.id, "err", err)
		}
		return
	}
	period := iapages.PeriodLabel(x.fy, x.start, x.end)
	to := make([]activities.NoticeTo, 0, len(ids))
	for _, id := range ids {
		to = append(to, activities.NoticeTo{UserID: id, Route: PagePath + x.id + "/", Label: "Review Report"})
	}
	title := "Impact report to review: " + x.title
	if len([]rune(title)) > 200 {
		title = string([]rune(title)[:200])
	}
	if err := activities.SendNotices(ctx, r.DB, r.Push, r.Live, r.Logger, r.now(), x.id, "", activities.Origin{},
		activities.Notice{Title: title, Body: x.country + " · " + period + " · version " + strconv.Itoa(x.version),
			Event: eventReviewRequested, Category: "ia", ContextType: "ImpactReport", Priority: "normal"}, to); err != nil && r.Logger != nil {
		r.Logger.Warn("iareports: the reviewers were not told", "report", x.id, "err", err)
	}
}

// reviewerIDs is reports.reviewer_ids.
func (r Reports) reviewerIDs(ctx context.Context, x *report) ([]string, error) {
	if x.country == "" {
		return nil, nil
	}
	read := func(role string) ([]string, error) {
		rows, err := r.DB.Query(ctx, `SELECT u.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE $1 = ANY(u.roles) AND u.is_active AND u.deleted_at IS NULL AND sp.country = $2 AND sp.deleted_at IS NULL ORDER BY u.id`,
			role, x.country)
		if err != nil {
			return nil, fmt.Errorf("iareports: the reviewers: %w", err)
		}
		return pgx.CollectRows(rows, pgx.RowTo[string])
	}
	officers, err := read(roleIA)
	if err != nil {
		return nil, err
	}
	others := []string{}
	for _, id := range officers {
		if id != x.author {
			others = append(others, id)
		}
	}
	if len(others) > 0 {
		return others, nil
	}
	return read("CountryDirector")
}

// withdraw is reports.withdraw_report.
func (r Reports) withdraw(ctx context.Context, p auth.Principal, id, note string) (Saved, error) {
	if !mayAuthor(p) {
		return Saved{}, refuse(authorOnly)
	}
	now := r.now()
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		x, err := r.visible(ctx, tx, p, id, true)
		if err != nil {
			return err
		}
		if x == nil {
			return refuse("That impact report is not in your country.")
		}
		if x.author != p.UserID {
			return refuse("Only the officer who wrote the report changes it.")
		}
		if x.status != statusDraft && x.status != "submitted" {
			return refuse("This report is %s and cannot be withdrawn.", lower(statusLabels[x.status]))
		}
		if _, err := tx.Exec(ctx, `UPDATE impact_report SET status = 'withdrawn', updated_at = $2 WHERE id = $1`, id, now); err != nil {
			return fmt.Errorf("iareports: withdrawing the report: %w", err)
		}
		var hash string
		_ = tx.QueryRow(ctx, `SELECT snapshot_hash FROM impact_report WHERE id = $1`, id).Scan(&hash)
		var noted any
		if note != "" {
			noted = note
		}
		e := reportAudit("ia.report.withdrawn", id, p, x.country, x.version, "withdrawn", hash, map[string]any{"note": noted})
		if note != "" {
			reason := note
			if len([]rune(reason)) > 500 {
				reason = string([]rune(reason)[:500])
			}
			e.Reason = &reason
		}
		if _, err := audit.Append(ctx, tx, e, now); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, 'ImpactReport', $2, $3)`, eventReviewRequested, id, now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	return Saved{Message: "Report withdrawn.", ReportID: id}, nil
}

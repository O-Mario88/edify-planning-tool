package iareports

// Review a submitted report (impact_report_views.review_drawer and
// review_save → reports.review_report): a second IA officer in the
// country, the Country Director only where there is none; never the author.

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/jackc/pgx/v5"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const eventReviewDecided = "ia.report.review_decided"

// reviewerBasis is review.reviewer_basis: peer_ia, cd_fallback or "".
func (r Reports) reviewerBasis(ctx context.Context, q schooldirectory.Querier, p auth.Principal, author, country string) (string, error) {
	if p.UserID == "" || p.UserID == author {
		return "", nil
	}
	country = strings.TrimSpace(country)
	if country != "" {
		mine, err := profileCountry(ctx, q, p)
		if err != nil {
			return "", err
		}
		if mine != country {
			return "", nil
		}
	}
	switch p.ActiveRole {
	case roleIA:
		return "peer_ia", nil
	case "CountryDirector":
		if country == "" {
			return "cd_fallback", nil
		}
		var others bool
		if err := q.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE 'ImpactAssessment' = ANY(u.roles) AND u.is_active AND u.deleted_at IS NULL AND sp.country = $1 AND sp.deleted_at IS NULL
  AND u.id <> $2)`, country, author).Scan(&others); err != nil {
			return "", fmt.Errorf("iareports: the country's officers: %w", err)
		}
		if !others {
			return "cd_fallback", nil
		}
	}
	return "", nil
}

// reviewDrawer is review_drawer.
func (r Reports) reviewDrawer(ctx context.Context, p auth.Principal, id string) (*screensv1.PageDrawer, error) {
	x, err := r.visible(ctx, r.DB, p, id, false)
	if err != nil || x == nil {
		if err == nil {
			err = errNoReport
		}
		return nil, err
	}
	basis := ""
	if x.status == "submitted" {
		if basis, err = r.reviewerBasis(ctx, r.DB, p, x.author, x.country); err != nil {
			return nil, err
		}
	}
	if basis == "" {
		note := "Only a second Impact Assessment officer in this country reviews it; the Country Director only where there is none."
		if x.author == p.UserID {
			note = "You wrote this, so a second reviewer has to review it."
		}
		return emptyDrawer("Review impact report", x.title, note), nil
	}
	var raw []byte
	var hash string
	if err := r.DB.QueryRow(ctx, `SELECT evidence_snapshot::text, snapshot_hash FROM impact_report WHERE id = $1`, id).Scan(&raw, &hash); err != nil {
		return nil, fmt.Errorf("iareports: the frozen evidence: %w", err)
	}
	d := json.NewDecoder(strings.NewReader(string(raw)))
	d.UseNumber()
	var snapshot map[string]any
	if err := d.Decode(&snapshot); err != nil {
		return nil, fmt.Errorf("iareports: reading the frozen evidence: %w", err)
	}
	cohort, _ := snapshot["cohort"].(map[string]any)
	portfolio, _ := snapshot["portfolio"].(map[string]any)
	str := func(m map[string]any, key string) string {
		if v, ok := m[key]; ok && v != nil {
			return fmt.Sprint(v)
		}
		return "0"
	}
	generated, _ := snapshot["generated_at"].(string)
	if len([]rune(generated)) > 16 {
		generated = string([]rune(generated)[:16])
	}
	if len(hash) > 16 {
		hash = hash[:16]
	}
	school, _ := snapshot["portfolio_note"].(string)
	if len(portfolio) > 0 {
		grade, _ := portfolio["grade"].(map[string]any)
		label, _ := grade["label"].(string)
		school = str(portfolio, "measured") + " of " + str(portfolio, "schools_in_scope") + " schools with paired confirmed SSAs · " + label
	}
	facts := []*screensv1.PageFact{
		{Label: "Period", Value: iapages.PeriodLabel(x.fy, x.start, x.end)},
		{Label: "Evidence frozen", Value: strings.ReplaceAll(generated, "T", " ") + " · sha256 " + hash},
		{Label: "Project cohort", Value: str(cohort, "measured") + " of " + str(cohort, "total") + " enrolments measured in " + str(cohort, "unique_schools") + " schools"},
		{Label: "School change", Value: school},
	}
	return &screensv1.PageDrawer{Title: "Review impact report", Subtitle: fmt.Sprintf("%s · version %d", x.title, x.version), HasRequired: true,
		SubmitLabel: "Save decision", CancelLabel: "Cancel", CanSubmit: true, Items: []*screensv1.DrawerItem{
			{Kind: &screensv1.DrawerItem_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
			note("Read the findings against the frozen evidence and the limitations on the report page before deciding."),
			field(&screensv1.DrawerField{Name: "decision", Label: "Decision", Kind: "select", Required: true, Value: "approve",
				Options: []*screensv1.DrawerOption{{Value: "approve", Label: "Approve: the evidence supports the report as written"},
					{Value: "return", Label: "Return to the author to correct"}}}),
			field(&screensv1.DrawerField{Name: "note", Label: "Review note", Kind: "textarea", MaxLength: proto.Int32(4000)}),
		}}, nil
}

// review is reports.review_report.
func (r Reports) review(ctx context.Context, p auth.Principal, id string, values map[string]string) (Saved, error) {
	decision := values["decision"]
	if decision != "approve" && decision != "return" {
		return Saved{}, refuse("Choose approve or return.")
	}
	words := strings.TrimSpace(values["note"])
	if decision == "return" && words == "" {
		return Saved{}, refuse("Say what the author needs to change.")
	}
	now := r.now()
	var x *report
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		var err error
		if x, err = r.visible(ctx, tx, p, id, true); err != nil {
			return err
		}
		if x == nil {
			return refuse("That impact report is not in your country.")
		}
		if x.status != "submitted" {
			return refuse("This report is %s, not awaiting review.", lower(statusLabels[x.status]))
		}
		basis, err := r.reviewerBasis(ctx, tx, p, x.author, x.country)
		if err != nil {
			return err
		}
		switch {
		case basis != "":
		case p.UserID == x.author:
			return refuse("You wrote this, so a second reviewer has to review it.")
		case p.ActiveRole == "CountryDirector":
			return refuse("Another Impact Assessment officer in this country reviews it; the Country Director acknowledges only where there is no second officer.")
		default:
			return refuse("Only a second Impact Assessment officer in this country may review it.")
		}
		status, action := "reviewed", "ia.report.reviewed"
		if decision == "return" {
			status, action = "returned", "ia.report.returned"
		}
		kept := words
		if len([]rune(kept)) > 4000 {
			kept = string([]rune(kept)[:4000])
		}
		if _, err := tx.Exec(ctx, `UPDATE impact_report SET status = $2, reviewed_by_id = $3, reviewed_at = $4, review_basis = $5,
  review_note = $6, updated_at = $4 WHERE id = $1`, id, status, p.UserID, now, basis, kept); err != nil {
			return fmt.Errorf("iareports: saving the review: %w", err)
		}
		var hash string
		_ = tx.QueryRow(ctx, `SELECT snapshot_hash FROM impact_report WHERE id = $1`, id).Scan(&hash)
		var noted any
		if words != "" {
			noted = words
		}
		e := reportAudit(action, id, p, x.country, x.version, status, hash, map[string]any{"review_basis": basis, "note": noted})
		if words != "" {
			reason := words
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
	title, priority, message := "Your impact report was reviewed", "normal", "Report reviewed. Release it to country leadership when ready."
	if decision == "return" {
		title, priority, message = "Your impact report was returned", "high", "Report returned to its author."
	}
	body := words
	if body == "" {
		body = x.title
	}
	if len([]rune(body)) > 500 {
		body = string([]rune(body)[:500])
	}
	if err := activities.SendNotices(ctx, r.DB, r.Push, r.Live, r.Logger, r.now(), x.id, "", activities.Origin{},
		activities.Notice{Title: title, Body: body, Event: eventReviewDecided, Category: "ia", ContextType: "ImpactReport", Priority: priority},
		[]activities.NoticeTo{{UserID: x.author, Route: PagePath + x.id + "/", Label: "Open Report"}}); err != nil && r.Logger != nil {
		r.Logger.Warn("iareports: the author was not told", "report", x.id, "err", err)
	}
	return Saved{Message: message, ReportID: id}, nil
}

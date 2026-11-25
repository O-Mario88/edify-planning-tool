package iareports

// Record that a school's brief was shared (brief_shared →
// reports.record_brief_shared): the account owner says when and what the
// school said, which closes their to-do.

import (
	"context"
	"fmt"
	"regexp"
	"strings"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
)

var briefPagePath = regexp.MustCompile(`^/impact-briefs/([A-Za-z0-9]{1,30})/$`)

// saveBrief is the brief page's form.
func (r Reports) saveBrief(ctx context.Context, p auth.Principal, release string, values map[string]string) (Saved, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, "/impact-briefs/"+release+"/") {
		return Saved{}, refuse("This page is not available.")
	}
	now := r.now()
	today := kampalaDay(now)
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		b, err := iapages.ReadBrief(ctx, tx, p, release)
		if err != nil {
			return err
		}
		if b == nil {
			return refuse("That school brief is not yours to open.")
		}
		if !b.MayRecord {
			return refuse("The school's account owner records that the brief was shared.")
		}
		shared, err := day(values, "shared_on", "Date shared")
		if err != nil {
			return err
		}
		if shared == nil {
			return refuse("Say when the findings were shared.")
		}
		if shared.After(today) {
			return refuse("The date shared cannot be in the future.")
		}
		response, err := text(values, "school_response", "What the school said", true, 2000)
		if err != nil {
			return err
		}
		visit := strings.TrimSpace(values["visit"])
		if visit != "" {
			var exists bool
			if err := tx.QueryRow(ctx, `SELECT EXISTS (SELECT 1 FROM activity WHERE id = $1 AND school_id = $2 AND deleted_at IS NULL)`,
				visit, b.SchoolID).Scan(&exists); err != nil {
				return fmt.Errorf("iareports: the visit: %w", err)
			}
			if !exists {
				return refuse("Choose a visit to this school.")
			}
		}
		reason := "Findings shared on " + shared.Format("2006-01-02")
		if visit != "" {
			reason += " during visit " + visit
		}
		reason += ". School response: " + response
		var key string
		if err := tx.QueryRow(ctx, `UPDATE team_action SET state = 'resolved', resolved_at = $2, manual_resolution_reason = $3,
  resolved_by_system = false, updated_at = $2 WHERE id = $1 RETURNING condition_key`, b.ActionID, now, reason).Scan(&key); err != nil {
			return fmt.Errorf("iareports: closing the to-do: %w", err)
		}
		if _, err := audit.Append(ctx, tx, audit.Entry{Action: "school_action.resolved", SubjectKind: audit.Text("TeamAction"),
			SubjectID: audit.Text(b.ActionID), ActorID: audit.Text(p.UserID), ActorRole: audit.Text(p.ActiveRole), Success: true,
			Payload: map[string]any{"condition_key": key}}, now); err != nil {
			return err
		}
		x, err := scanReport(tx.QueryRow(ctx, `SELECT `+reportColumns+` FROM impact_report r WHERE r.id = $1`, b.ReportID))
		if err != nil {
			return fmt.Errorf("iareports: the brief's report: %w", err)
		}
		var hash string
		_ = tx.QueryRow(ctx, `SELECT snapshot_hash FROM impact_report WHERE id = $1`, b.ReportID).Scan(&hash)
		var visited any
		if visit != "" {
			visited = visit
		}
		if _, err := audit.Append(ctx, tx, reportAudit("ia.report.school_brief_shared", b.ReportID, p, x.country, x.version, x.status, hash,
			map[string]any{"release_id": release, "school_id": b.SchoolID, "shared_on": shared.Format("2006-01-02"), "visit_id": visited,
				"team_action_id": b.ActionID}), now); err != nil {
			return err
		}
		_, err = tx.Exec(ctx, `SELECT gateway_notifications.resolve_condition($1, 'ImpactReportRelease', $2, $3)`, eventSchoolBrief, release, now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	return Saved{Message: "Recorded: the findings were shared with the school.", ReportID: release}, nil
}

package iareports

// Start a correction (report_correct → reports.start_correction): a new
// draft version with the same words and recommendations; the corrected
// version stands until the new one replaces it.

import (
	"context"
	"fmt"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// correctable is start_correction's rule: a returned, reviewed or released
// report, or one withdrawn after it was submitted.
func correctable(status string, submitted bool) bool {
	return status == "returned" || status == "reviewed" || status == "released" || (status == "withdrawn" && submitted)
}

// correct is reports.start_correction.
func (r Reports) correct(ctx context.Context, p auth.Principal, id string) (Saved, error) {
	if !mayAuthor(p) {
		return Saved{}, refuse(authorOnly)
	}
	now, revision := r.now(), cuid.New()
	var version int
	err := pgx.BeginTxFunc(ctx, r.DB, pgx.TxOptions{AccessMode: pgx.ReadWrite, IsoLevel: pgx.ReadCommitted}, func(tx pgx.Tx) error {
		x, err := r.visible(ctx, tx, p, id, true)
		if err != nil {
			return err
		}
		if x == nil {
			return refuse("That impact report is not in your country.")
		}
		mine, err := profileCountry(ctx, tx, p)
		if err != nil {
			return err
		}
		if x.country == "" || mine != x.country {
			return refuse("Only an Impact Assessment officer in this country corrects it.")
		}
		var submitted, open bool
		if err := tx.QueryRow(ctx, `SELECT r.submitted_at IS NOT NULL, EXISTS (SELECT 1 FROM impact_report c
WHERE c.supersedes_id = r.id AND c.status IN ('draft', 'submitted', 'returned')) FROM impact_report r WHERE r.id = $1`, id).
			Scan(&submitted, &open); err != nil {
			return fmt.Errorf("iareports: the report to correct: %w", err)
		}
		if !correctable(x.status, submitted) {
			return refuse("Only a returned, reviewed, released or withdrawn report is corrected; edit a draft instead.")
		}
		if open {
			return refuse("A correction of this report is already open.")
		}
		version = x.version + 1
		if _, err := tx.Exec(ctx, `INSERT INTO impact_report (id, created_at, updated_at, author_id, author_role, review_basis,
  review_note, country, fy, period_start, period_end, programme_areas, title, status, methodology, findings, limitations,
  evidence_snapshot, snapshot_hash, version, project_id, supersedes_id)
SELECT $1, $2, $2, $3, $4, '', '', country, fy, period_start, period_end, programme_areas, title, 'draft', methodology, findings,
  limitations, '{}', '', $5, project_id, id FROM impact_report WHERE id = $6`, revision, now, p.UserID, p.ActiveRole, version, id); err != nil {
			return fmt.Errorf("iareports: starting the correction: %w", err)
		}
		rows, err := tx.Query(ctx, `SELECT text, owner_role, due_date FROM impact_report_recommendation WHERE report_id = $1
ORDER BY created_at, id`, id)
		if err != nil {
			return fmt.Errorf("iareports: the recommendations to carry: %w", err)
		}
		type carried struct {
			text, owner string
			due         any
		}
		list := []carried{}
		for rows.Next() {
			var c carried
			if err := rows.Scan(&c.text, &c.owner, &c.due); err != nil {
				rows.Close()
				return fmt.Errorf("iareports: a recommendation to carry: %w", err)
			}
			list = append(list, c)
		}
		rows.Close()
		for _, c := range list {
			if _, err := tx.Exec(ctx, `INSERT INTO impact_report_recommendation (id, created_at, updated_at, text, owner_role, due_date,
  status, response, report_id) VALUES ($1, $2, $2, $3, $4, $5, 'proposed', '', $6)`, cuid.New(), now, c.text, c.owner, c.due, revision); err != nil {
				return fmt.Errorf("iareports: carrying a recommendation: %w", err)
			}
		}
		_, err = audit.Append(ctx, tx, reportAudit("ia.report.correction_started", revision, p, x.country, version, statusDraft, "",
			map[string]any{"corrects": id, "corrects_version": x.version}), now)
		return err
	})
	if err != nil {
		return Saved{}, err
	}
	return Saved{Message: fmt.Sprintf("Version %d started as a draft; the earlier version stands until it replaces it.", version),
		ReportID: revision}, nil
}

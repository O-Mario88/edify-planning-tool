package iareports

// One report as its drawers read it: visible_reports, detail_rights'
// can_edit and _own_report.

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/iapages"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// statusLabels are ReportStatus's labels.
var statusLabels = map[string]string{
	"draft": "Draft", "submitted": "Submitted for review", "returned": "Returned", "reviewed": "Reviewed",
	"released": "Released", "withdrawn": "Withdrawn", "superseded": "Superseded",
}

type report struct {
	id, title, status, author, country, fy, project, methodology, findings, limitations string
	start, end                                                                          *time.Time
	areas                                                                               []string
	version                                                                             int
}

const reportColumns = `r.id, r.title, r.status, r.author_id, r.country, r.fy, COALESCE(r.project_id, ''), r.methodology,
  r.findings, r.limitations, r.period_start, r.period_end, COALESCE(r.programme_areas, '{}'), r.version`

func scanReport(row pgx.Row) (report, error) {
	var x report
	err := row.Scan(&x.id, &x.title, &x.status, &x.author, &x.country, &x.fy, &x.project, &x.methodology, &x.findings,
		&x.limitations, &x.start, &x.end, &x.areas, &x.version)
	return x, err
}

// visible is _visible (forUpdate false) or _report_for_update: the report if
// the reader may read it, else nil.
func (r Reports) visible(ctx context.Context, q schooldirectory.Querier, p auth.Principal, id string, forUpdate bool) (*report, error) {
	args := []any{}
	reach, err := iapages.ReportReach(ctx, q, p, r.now(), &args)
	if err != nil {
		return nil, err
	}
	args = append(args, id)
	lock := ""
	if forUpdate {
		lock = " FOR UPDATE OF r"
	}
	x, err := scanReport(q.QueryRow(ctx, fmt.Sprintf(`SELECT %s FROM impact_report r WHERE (%s) AND r.id = $%d%s`,
		reportColumns, reach, len(args), lock), args...))
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("iareports: the report: %w", err)
	}
	return &x, nil
}

// canEdit is detail_rights' can_edit.
func (x report) canEdit(p auth.Principal) bool {
	return x.author == p.UserID && p.ActiveRole == roleIA && x.status == statusDraft
}

// ownDraft is _own_report then _assert_draft, inside tx.
func (r Reports) ownDraft(ctx context.Context, tx pgx.Tx, p auth.Principal, id string) (*report, error) {
	if !mayAuthor(p) {
		return nil, refuse(authorOnly)
	}
	x, err := r.visible(ctx, tx, p, id, true)
	if err != nil {
		return nil, err
	}
	if x == nil {
		return nil, refuse("That impact report is not in your country.")
	}
	if x.author != p.UserID {
		return nil, refuse("Only the officer who wrote the report changes it.")
	}
	if x.status != statusDraft {
		return nil, refuse("This report is %s; its evidence is frozen, so a correction is a new version.",
			lower(statusLabels[x.status]))
	}
	return x, nil
}

func lower(s string) string {
	out := []rune(s)
	for i, c := range out {
		if c >= 'A' && c <= 'Z' {
			out[i] = c + ('a' - 'A')
		}
	}
	return string(out)
}

func isoDay(t *time.Time) string {
	if t == nil {
		return ""
	}
	return t.Format(time.DateOnly)
}

// Package iareports is Impact Assessment's impact reports
// (apps.impact.reports, apps.frontend.views.impact_report_views) drawn and
// saved in Go with Django absent: a report's drawers and their saves.
package iareports

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/activities"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// PagePath is the register; a report's own pages sit under it.
const PagePath = "/ia/impact-reports/"

const (
	roleIA      = "ImpactAssessment"
	statusDraft = "draft"
)

// Programme is apps.impact.models.Programme, in its order.
var Programme = [][2]string{
	{"training", "Christian training"}, {"lending", "Lending"}, {"edtech", "Educational technology"},
	{"visits", "School visits"}, {"cross", "Across programmes"},
}

// Reports draws and saves the impact report drawers.
type Reports struct {
	DB  *pgxpool.Pool
	Now func() time.Time
	// Push and Live carry a reviewer's notice to their phone and open pages.
	Push   activities.NoticePush
	Live   activities.NoticePublisher
	Logger *slog.Logger
}

func (r Reports) now() time.Time {
	if r.Now == nil {
		return time.Now()
	}
	return r.Now()
}

// Refusal is a service error (BadRequest, Forbidden, NotFound) in Django's
// words.
type Refusal struct {
	Message  string
	NotFound bool
	// Page: the page gate's refusal, which the drawer answers with.
	Page bool
}

// pageRefusal is require_page_permission("impact_reports")'s refusal.
const pageRefusal = "Access Denied: Your active role does not have permission to view Impact Reports."

func (e *Refusal) Error() string { return e.Message }

func refuse(format string, args ...any) error { return &Refusal{Message: fmt.Sprintf(format, args...)} }

// mayAuthor is reports.may_author.
func mayAuthor(p auth.Principal) bool { return p.ActiveRole == roleIA }

// profileCountry is the reader's staff profile country.
func profileCountry(ctx context.Context, q schooldirectory.Querier, p auth.Principal) (string, error) {
	var country string
	err := q.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("iareports: the reader's country: %w", err)
	}
	return strings.TrimSpace(country), nil
}

// projectOptions is reports.project_options: special projects with
// enrolments in the author's scope.
func (r Reports) projectOptions(ctx context.Context, p auth.Principal) ([][2]string, error) {
	scope, err := schooldirectory.ResolveScope(ctx, r.DB, p, r.now())
	if err != nil {
		return nil, err
	}
	if scope.SummaryOnly {
		return nil, nil
	}
	args := []any{}
	reach := schooldirectory.AnalyticsReach(scope, &args)
	rows, err := r.DB.Query(ctx, `SELECT DISTINCT pr.id, pr.name FROM project_school_assignment a
JOIN school s ON s.id = a.school_id JOIN project pr ON pr.id = a.project_id
WHERE pr.deleted_at IS NULL AND `+reach+` ORDER BY pr.name, pr.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("iareports: the projects: %w", err)
	}
	defer rows.Close()
	out := [][2]string{}
	for rows.Next() {
		var o [2]string
		if err := rows.Scan(&o[0], &o[1]); err != nil {
			return nil, fmt.Errorf("iareports: a project: %w", err)
		}
		out = append(out, o)
	}
	return out, rows.Err()
}

// fields is what _clean makes of a report form.
type fields struct {
	title, fy, methodology, findings, limitations string
	periodStart, periodEnd                        *time.Time
	areas                                         []string
	projectID                                     *string
}

func text(values map[string]string, key, label string, required bool, maxLength int) (string, error) {
	value := strings.TrimSpace(values[key])
	if required && value == "" {
		return "", refuse("%s is required.", label)
	}
	if utf8.RuneCountInString(value) > maxLength {
		return "", refuse("%s must be %d characters or fewer.", label, maxLength)
	}
	return value, nil
}

func day(values map[string]string, key, label string) (*time.Time, error) {
	raw := strings.TrimSpace(values[key])
	if raw == "" {
		return nil, nil
	}
	for _, layout := range []string{time.DateOnly, "20060102"} {
		if d, err := time.Parse(layout, raw); err == nil {
			return &d, nil
		}
	}
	return nil, refuse("%s must be a date (YYYY-MM-DD).", label)
}

func ticked(raw string) []string {
	out := []string{}
	for _, v := range strings.Split(raw, ",") {
		if v = strings.TrimSpace(v); v != "" {
			out = append(out, v)
		}
	}
	return out
}

// clean is reports._clean.
func (r Reports) clean(ctx context.Context, p auth.Principal, values map[string]string) (fields, error) {
	var f fields
	f.fy = strings.TrimSpace(values["fy"])
	known := false
	for _, o := range schooldirectory.FYOptions(r.now()) {
		known = known || o == f.fy
	}
	if !known {
		return f, refuse("Choose the financial year the report covers.")
	}
	var err error
	if f.periodStart, err = day(values, "period_start", "Period start"); err != nil {
		return f, err
	}
	if f.periodEnd, err = day(values, "period_end", "Period end"); err != nil {
		return f, err
	}
	if f.periodStart != nil && f.periodEnd != nil && f.periodStart.After(*f.periodEnd) {
		return f, refuse("The period must start before it ends.")
	}
	chosen := map[string]bool{}
	for _, a := range ticked(values["programme_areas"]) {
		ok := false
		for _, pr := range Programme {
			ok = ok || pr[0] == a
		}
		if !ok {
			return f, refuse("Choose programme areas from the list.")
		}
		chosen[a] = true
	}
	f.areas = []string{}
	for _, pr := range Programme {
		if chosen[pr[0]] {
			f.areas = append(f.areas, pr[0])
		}
	}
	if project := strings.TrimSpace(values["project"]); project != "" {
		options, err := r.projectOptions(ctx, p)
		if err != nil {
			return f, err
		}
		found := false
		for _, o := range options {
			found = found || o[0] == project
		}
		if !found {
			return f, refuse("Choose a special project with enrolments in your country.")
		}
		f.projectID = &project
	}
	if f.title, err = text(values, "title", "Title", true, 200); err != nil {
		return f, err
	}
	for _, t := range []struct {
		key, label string
		into       *string
	}{{"methodology", "Methodology", &f.methodology}, {"findings", "Findings", &f.findings}, {"limitations", "Limitations", &f.limitations}} {
		if *t.into, err = text(values, t.key, t.label, false, 10000); err != nil {
			return f, err
		}
	}
	return f, nil
}

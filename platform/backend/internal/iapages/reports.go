package iapages

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageheader"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// ReportsPath is the Impact Reports register.
const ReportsPath = "/ia/impact-reports/"

const (
	roleIA  = "ImpactAssessment"
	roleCD  = "CountryDirector"
	roleRVP = "RegionalVicePresident"
	roleAdm = "Admin"
)

// report is one impact report as its register row reads it.
type report struct {
	id, title, status, author, reviewer, note, country, fy string
	start, end                                             *time.Time
	programmes                                             []string
	version                                                int
	updated                                                time.Time
}

// reportReach is visible_reports as a WHERE clause on impact_report `r`,
// its arguments appended to args.
func (s *Service) reportReach(ctx context.Context, p auth.Principal, args *[]any) (string, error) {
	switch p.ActiveRole {
	case roleAdm:
		return "TRUE", nil
	case roleIA, roleCD:
		country, err := s.readerCountry(ctx, p)
		if err != nil {
			return "", err
		}
		if country == "" {
			return "TRUE", nil
		}
		*args = append(*args, country)
		return fmt.Sprintf("r.country = $%d", len(*args)), nil
	case roleRVP:
		*args = append(*args, rules.ReportRVPStatuses)
		where := fmt.Sprintf("r.status = ANY($%d)", len(*args))
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return "", fmt.Errorf("iapages: resolving the reader's scope: %w", err)
		}
		if !scope.RegionScope {
			return where, nil
		}
		ids := scope.RegionIDs
		if ids == nil {
			ids = []string{}
		}
		*args = append(*args, ids)
		return where + fmt.Sprintf(" AND r.country IN (SELECT country FROM region WHERE id = ANY($%d) AND COALESCE(country, '') <> '')", len(*args)), nil
	}
	return "FALSE", nil
}

// readerCountry is reports.reader_country: the analytics scope's country,
// else the reader's People record's.
func (s *Service) readerCountry(ctx context.Context, p auth.Principal) (string, error) {
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
	if err != nil {
		return "", fmt.Errorf("iapages: resolving the reader's scope: %w", err)
	}
	if c := strings.TrimSpace(scope.Country); c != "" {
		return c, nil
	}
	return s.profileCountry(ctx, p)
}

func (s *Service) profileCountry(ctx context.Context, p auth.Principal) (string, error) {
	var country string
	err := s.db.QueryRow(ctx, `SELECT COALESCE(country, '') FROM staff_profile WHERE user_id = $1 LIMIT 1`, p.UserID).Scan(&country)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", fmt.Errorf("iapages: reading the reader's country: %w", err)
	}
	return strings.TrimSpace(country), nil
}

func reportStatusLabel(status string) string {
	for _, s := range rules.ReportStatuses {
		if s[0] == status {
			return s[1]
		}
	}
	return status
}

// reports is impact_report_views.register_page.
func (s *Service) reports(ctx context.Context, p auth.Principal, role Role, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	args := []any{}
	reach, err := s.reportReach(ctx, p, &args)
	if err != nil {
		return nil, true, err
	}
	status := query.Get("status")
	if !slices.ContainsFunc(rules.ReportStatuses, func(x [2]string) bool { return x[0] == status }) {
		status = ""
	}
	rows, err := s.db.Query(ctx, `SELECT DISTINCT fy FROM impact_report r WHERE `+reach+` AND COALESCE(fy, '') <> '' ORDER BY fy DESC`, args...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the reports' years: %w", err)
	}
	years, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the reports' years: %w", err)
	}
	slices.Sort(years)
	slices.Reverse(years)
	fy := query.Get("fy")
	if !slices.Contains(years, fy) {
		fy = ""
	}
	listed, largs := reach, slices.Clone(args)
	if status != "" {
		largs = append(largs, status)
		listed += fmt.Sprintf(" AND r.status = $%d", len(largs))
	}
	if fy != "" {
		largs = append(largs, fy)
		listed += fmt.Sprintf(" AND r.fy = $%d", len(largs))
	}
	var total int
	if err := s.db.QueryRow(ctx, `SELECT count(*) FROM impact_report r WHERE `+listed, largs...).Scan(&total); err != nil {
		return nil, true, fmt.Errorf("iapages: counting the reports: %w", err)
	}
	size := rules.ReportPageSize
	number, pages := closedschools.PageOf(query.Get("register_page"), total, size)
	pargs := append(slices.Clone(largs), size, (number-1)*size)
	rows, err = s.db.Query(ctx, fmt.Sprintf(`SELECT r.id, r.title, r.status, COALESCE(r.author_id, ''), COALESCE(r.reviewed_by_id, ''), COALESCE(r.review_note, ''),
  COALESCE(r.country, ''), COALESCE(r.fy, ''), r.period_start, r.period_end, COALESCE(r.programme_areas, '{}'), r.version, r.updated_at
FROM impact_report r WHERE %s ORDER BY r.updated_at DESC, r.created_at DESC LIMIT $%d OFFSET $%d`, listed, len(pargs)-1, len(pargs)), pargs...)
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the reports: %w", err)
	}
	list, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (report, error) {
		var x report
		return x, row.Scan(&x.id, &x.title, &x.status, &x.author, &x.reviewer, &x.note, &x.country, &x.fy, &x.start, &x.end, &x.programmes, &x.version, &x.updated)
	})
	if err != nil {
		return nil, true, fmt.Errorf("iapages: reading the reports: %w", err)
	}
	cells, err := s.reportRows(ctx, p, list)
	if err != nil {
		return nil, true, err
	}
	operational := schooldirectory.OperationalFY(s.now())
	tiles, err := s.reportTiles(ctx, reach, args, operational)
	if err != nil {
		return nil, true, err
	}
	header := &screensv1.PageHeader{Eyebrow: "Reporting & accountability", Title: "Impact Reports",
		Description: "Evidence-based reports for country leadership, partner schools and donors: written by Impact Assessment, reviewed by a second reader, released per audience."}
	if p.ActiveRole == roleRVP {
		header.Description = "Reviewed impact reports of your region, as aggregates, and the donor versions waiting for your approval."
	}
	if p.ActiveRole == roleIA {
		header.Actions = []*screensv1.PageAction{pageheader.Drawer("Start report", ReportsPath+"new", false)}
	}
	statusOptions := []*screensv1.PageFilterOption{{Value: "", Label: "Every status"}}
	for _, x := range rules.ReportStatuses {
		statusOptions = append(statusOptions, &screensv1.PageFilterOption{Value: x[0], Label: x[1]})
	}
	filters := []*screensv1.PageFilter{{Name: "status", Value: status, Caption: "Status", Options: statusOptions}}
	if len(years) > 1 {
		f := &screensv1.PageFilter{Name: "fy", Value: fy, Caption: "Financial year", Options: []*screensv1.PageFilterOption{{Value: "", Label: "Every year"}}}
		for _, y := range years {
			f.Options = append(f.Options, &screensv1.PageFilterOption{Value: y, Label: "FY" + y})
		}
		filters = append(filters, f)
	}
	blocks := workspaceStrip(role)
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Impact reports at a glance", Metrics: tiles}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: filters}}},
		titled("Impact reports"))
	t := &screensv1.PageTable{}
	if len(cells) == 0 {
		body := "Reports written by Impact Assessment in your reach appear here."
		if p.ActiveRole == roleIA {
			body = "Start a report: set its period, write the methodology, findings and limitations, and add recommendations. Submitting freezes the evidence."
		}
		t.EmptyMessage = "No impact reports"
		t.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: "No impact reports " + body}}}}
	} else {
		for _, c := range []string{"Report", "Period", "Programmes", "Version", "Author", "Status", "Updated", ""} {
			t.Columns = append(t.Columns, &screensv1.PageColumn{Label: c})
		}
		for _, c := range cells {
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: c})
		}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("register_page", number, pages, total, size, query, rules.QueryKeysNotPassed))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: ReportsPath}, true, nil
}

// periodLabel is reports.period_label: the report's own dates, filled from
// its financial year.
func periodLabel(x report) string {
	start, end := x.start, x.end
	if x.fy != "" && (start == nil || end == nil) {
		n, _ := strconv.Atoi(x.fy)
		if start == nil {
			d := time.Date(n-1, time.October, 1, 0, 0, 0, 0, time.UTC)
			start = &d
		}
		if end == nil {
			d := time.Date(n, time.September, 30, 0, 0, 0, 0, time.UTC)
			end = &d
		}
	}
	switch {
	case start != nil && end != nil:
		return start.Format("2 Jan 2006") + " – " + end.Format("2 Jan 2006")
	case x.fy != "":
		return "FY" + x.fy
	}
	return "All recorded enrolments"
}

// reportRows is reports.decorate and the view's row: each report's words
// and the one action the reader may take on it.
func (s *Service) reportRows(ctx context.Context, p auth.Principal, list []report) ([][]*screensv1.PageCell, error) {
	ids := []string{}
	for _, x := range list {
		ids = append(ids, x.author, x.reviewer)
	}
	names, err := accountNames(ctx, s.db, ids)
	if err != nil {
		return nil, err
	}
	myCountry := ""
	if p.ActiveRole == roleIA || p.ActiveRole == roleCD {
		if myCountry, err = s.profileCountry(ctx, p); err != nil {
			return nil, err
		}
	}
	officers := map[string][]string{}
	canReview := func(x report) (bool, error) {
		if x.status != "submitted" || x.author == p.UserID || myCountry != x.country {
			return false, nil
		}
		switch p.ActiveRole {
		case roleIA:
			return true, nil
		case roleCD:
			ids, ok := officers[x.country]
			if !ok {
				if x.country != "" {
					rows, err := s.db.Query(ctx, `SELECT u.id FROM "user" u JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.roles @> ARRAY[$1]::varchar[] AND u.is_active AND u.deleted_at IS NULL AND sp.country = $2 AND sp.deleted_at IS NULL`, roleIA, x.country)
					if err != nil {
						return false, fmt.Errorf("iapages: reading the country's officers: %w", err)
					}
					if ids, err = pgx.CollectRows(rows, pgx.RowTo[string]); err != nil {
						return false, err
					}
				}
				officers[x.country] = ids
			}
			for _, id := range ids {
				if id != x.author {
					return false, nil
				}
			}
			return true, nil
		}
		return false, nil
	}
	out := [][]*screensv1.PageCell{}
	for _, x := range list {
		review, err := canReview(x)
		if err != nil {
			return nil, err
		}
		label := "Open"
		switch {
		case review:
			label = "Review"
		case x.author == p.UserID && p.ActiveRole == roleIA && x.status == "draft":
			label = "Continue draft"
		case x.status == "reviewed" && x.reviewer != "" && x.reviewer == p.UserID:
			label = "Release"
		}
		status := reportStatusLabel(x.status)
		if x.status == "returned" && x.note != "" {
			status += ": " + string([]rune(x.note)[:min(120, len([]rune(x.note)))])
		}
		programmes := []string{}
		for _, a := range x.programmes {
			l, ok := rules.ReportProgrammes[a]
			if !ok {
				l = a
			}
			programmes = append(programmes, l)
		}
		programmesText := strings.Join(programmes, ", ")
		if programmesText == "" {
			programmesText = "Across programmes"
		}
		author, ok := names[x.author]
		if !ok {
			author = "Unknown"
		}
		dash := func(t string) *screensv1.PageCell {
			if t == "" {
				t = "—"
			}
			return &screensv1.PageCell{Text: closedschools.Collapse(t)}
		}
		out = append(out, []*screensv1.PageCell{
			dash(x.title), dash(periodLabel(x)), dash(programmesText), dash(strconv.Itoa(x.version)), dash(author),
			dash(status), dash(x.updated.In(zone).Format("2 Jan 2006 15:04")),
			{Actions: []*screensv1.PageAction{{Key: "button", Label: label, Primary: true, Enabled: true, Href: ReportsPath + x.id + "/"}}},
		})
	}
	return out, nil
}

// reportTiles is reports.register_tiles over reports.counts.
func (s *Service) reportTiles(ctx context.Context, reach string, args []any, fy string) ([]*screensv1.PageMetric, error) {
	var submitted, returned, released, awaiting, overdue, donor int
	a := append(slices.Clone(args), fy, rules.ReportOpenRecommendations, s.now().In(zone).Format(time.DateOnly))
	n := len(args)
	err := s.db.QueryRow(ctx, fmt.Sprintf(`
WITH visible AS (SELECT * FROM impact_report r WHERE %s)
SELECT (SELECT count(*) FROM visible WHERE status = 'submitted'), (SELECT count(*) FROM visible WHERE status = 'returned'),
  (SELECT count(*) FROM visible WHERE status = 'released' AND fy = $%[2]d),
  (SELECT count(*) FROM impact_report_recommendation m WHERE m.report_id IN (SELECT id FROM visible WHERE status = 'released') AND m.status = 'proposed'),
  (SELECT count(*) FROM impact_report_recommendation m WHERE m.report_id IN (SELECT id FROM visible WHERE status = 'released')
     AND m.status = ANY($%[3]d) AND m.due_date < $%[4]d::date),
  (SELECT count(*) FROM impact_report_release l WHERE l.report_id IN (SELECT id FROM visible) AND l.audience = 'donor' AND l.status = 'pending_approval')`,
		reach, n+1, n+2, n+3), a...).Scan(&submitted, &returned, &released, &awaiting, &overdue, &donor)
	if err != nil {
		return nil, fmt.Errorf("iapages: counting the reports: %w", err)
	}
	responses := "from released reports"
	if overdue > 0 {
		responses = strconv.Itoa(overdue) + " overdue"
	}
	tone := func(warn bool, danger bool) string {
		switch {
		case danger:
			return "danger"
		case warn:
			return "warning"
		}
		return "info"
	}
	return []*screensv1.PageMetric{
		registryMetric("Impact Reports Awaiting Review", submitted, "reviewed by someone other than the author", tone(submitted > 0, false), ReportsPath+"?status=submitted"),
		registryMetric("Impact Reports Returned for Correction", returned, "a correction is a new version", tone(false, returned > 0), ReportsPath+"?status=returned"),
		registryMetric("Impact Reports Released This Year", released, "FY"+fy+", released to country leadership", "info", ReportsPath+"?status=released&fy="+fy),
		registryMetric("Report Recommendations Awaiting a Response", awaiting, responses, tone(awaiting > 0 || overdue > 0, false), ""),
		registryMetric("Donor Versions Awaiting RVP Approval", donor, "approved by an RVP, never the requester", tone(donor > 0, false), ""),
	}, nil
}

// registryMetric is a registered tile as the feed reads it: a helper that
// starts with a figure is drawn cut to that figure, with the tile's tone;
// any other is the tile's note, and the tone is not drawn.
func registryMetric(label string, value int, helper, tone, href string) *screensv1.PageMetric {
	m := &screensv1.PageMetric{Label: label, Value: strconv.Itoa(value), Href: href}
	if brief := schoolprofile.BriefHelper(helper); brief != "" {
		m.Helper, m.Tone = brief, tone
	} else {
		m.Note = helper
	}
	return m
}

// Package targetdistribution builds the Uganda Master Priority Plan
// (/target-distribution:
// apps.frontend.views.target_distribution_views.target_distribution_page, as
// the existing feed reads partials/priorities/distribution_view.html inside
// the Priorities rail): the year's country master and its distribution to
// Programme Leads.
//
// It reads; it never writes. It draws a year with no master yet: the year
// filter, the import form for a reader who may import, the rail and the empty
// state. A year that has a master, staged imports for a reader who may see
// them, any query besides the year, a year the view would not read as asked,
// and a reader with one view are handed on. The doors, the import permission
// and each role's rail are exported to rules.json by `manage.py
// export_target_distribution_rules`;
// apps/hr/test_target_distribution_rules_export.py fails when the two differ.
package targetdistribution

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page Go answers.
const Path = "/target-distribution"

// country is the master's country (country_distribution_workspace's default).
const country = "Uganda"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	Roles map[string]struct {
		Import bool        `json:"import"`
		Tabs   [][2]string `json:"tabs"`
	} `json:"roles"`
	MinFYYear int `json:"min_fy_year"`
	MaxFYYear int `json:"max_fy_year"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || r.MaxFYYear == 0 {
		panic(fmt.Sprintf("targetdistribution: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var errPassOn = errors.New("targetdistribution: passed to the existing application")

// Service answers Uganda Target Distribution from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db, its moment read from now.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers /target-distribution; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, true, pagegate.ErrNotAvailable
	}
	resp, err := s.build(ctx, role.Import, role.Tabs, query)
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return resp, true, nil
}

func (s *Service) build(ctx context.Context, canImport bool, tabs [][2]string, query url.Values) (*screensv1.GetPageResponse, error) {
	for key, values := range query {
		if key != "fy" && strings.Join(values, "") != "" {
			return nil, fmt.Errorf("the query %q: %w", key, errPassOn)
		}
	}
	// One tab is not a rail: the view is drawn on its own.
	if len(tabs) < 2 {
		return nil, fmt.Errorf("one view: %w", errPassOn)
	}
	raw := strings.TrimSpace(query.Get("fy"))
	years, err := s.cycleYears(ctx)
	if err != nil {
		return nil, err
	}
	fy, err := s.year(ctx, raw)
	if err != nil {
		return nil, err
	}
	var hasMaster, staged bool
	if err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM hr_strategic_priority WHERE fy = $1 AND level = 'country' AND country_id = $2 AND cycle_id IS NOT NULL),
       EXISTS (SELECT 1 FROM hr_priority_import_batch WHERE fy = $1 AND country_id = $2)`, fy, country).Scan(&hasMaster, &staged); err != nil {
		return nil, fmt.Errorf("targetdistribution: reading the year's master: %w", err)
	}
	if hasMaster {
		return nil, fmt.Errorf("a master: %w", errPassOn)
	}
	if canImport && staged {
		return nil, fmt.Errorf("staged imports: %w", errPassOn)
	}
	if !slices.Contains(years, fy) {
		years = append(years, fy)
	}
	view := []*screensv1.PageBlock{yearFilter(fy, years)}
	if canImport {
		view = append(view, importForm())
	}
	view = append(view, rail(tabs, raw),
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
			Empty: "Import the confirmed country priorities into the database before opening distribution."}})
	// The feed reads the rail's panel under each of its tabs.
	segments := &screensv1.PageSegments{}
	for _, t := range tabs {
		segments.Segments = append(segments.Segments, &screensv1.PageSegment{Label: t[0], Active: t[1] == Path, Blocks: view})
	}
	return &screensv1.GetPageResponse{
		Header: &screensv1.PageHeader{
			Eyebrow: "Impact Assessment · Uganda Target Distribution",
			Title:   "Uganda Master Priority Plan",
			Description: "The governed country plan for moving every confirmed field target from Impact Assessment to " +
				"Program Leads and onward to accountable CCEOs.",
		},
		Blocks:  []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Segments{Segments: segments}}},
		WebPath: Path,
	}, nil
}

// year is the year the view reads: an asked year it accepts as asked (any
// other ask is handed on, since the rail carries the ask as it came), else
// the latest cycle not archived, else the operational year.
func (s *Service) year(ctx context.Context, raw string) (string, error) {
	if raw != "" {
		n, err := strconv.Atoi(raw)
		if len(raw) != 4 || err != nil || strings.IndexFunc(raw, func(r rune) bool { return r < '0' || r > '9' }) >= 0 ||
			n < rules.MinFYYear || n > rules.MaxFYYear {
			return "", fmt.Errorf("the year %q: %w", raw, errPassOn)
		}
		return raw, nil
	}
	var latest *string
	if err := s.db.QueryRow(ctx, `SELECT max(financial_year) FROM hr_strategic_priority_cycle WHERE status <> 'archived'`).Scan(&latest); err != nil {
		return "", fmt.Errorf("targetdistribution: reading the latest cycle: %w", err)
	}
	if latest != nil && *latest != "" {
		return *latest, nil
	}
	return schooldirectory.OperationalFY(s.now()), nil
}

// cycleYears are every cycle's year, latest first.
func (s *Service) cycleYears(ctx context.Context) ([]string, error) {
	rows, err := s.db.Query(ctx, `SELECT financial_year FROM hr_strategic_priority_cycle ORDER BY financial_year DESC`)
	if err != nil {
		return nil, fmt.Errorf("targetdistribution: reading the cycles: %w", err)
	}
	defer rows.Close()
	years := []string{}
	for rows.Next() {
		var y string
		if err := rows.Scan(&y); err != nil {
			return nil, fmt.Errorf("targetdistribution: reading a cycle: %w", err)
		}
		years = append(years, y)
	}
	return years, rows.Err()
}

func yearFilter(fy string, years []string) *screensv1.PageBlock {
	filter := &screensv1.PageFilter{Name: "fy", Label: "Financial year", Value: fy}
	for _, y := range years {
		filter.Options = append(filter.Options, &screensv1.PageFilterOption{Value: y, Label: "FY" + y})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{filter}}}}
}

// importForm is partials/hr/priority_import.html with no staged import.
func importForm() *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: &screensv1.PageForm{
		Title: "Import country priorities",
		Text:  "Impact Assessment stages and validates; the Country Director still confirms and publishes.",
		Items: []*screensv1.PageFormItem{{Kind: &screensv1.PageFormItem_Field{Field: &screensv1.DrawerField{
			Name: "priority_file", Kind: "file", Required: true,
			Label: "Priority source file · CSV or XLSX Maximum 5 MB. The file is staged first; an upload never publishes or overwrites an approved master.",
		}}}},
		SubmitLabel: "Validate upload",
		Key:         "/target-distribution/import",
	}}}
}

// rail is partials/dashboards/_view_tabs_nav.html: the reader's views, each
// carrying the year as it was asked.
func rail(tabs [][2]string, raw string) *screensv1.PageBlock {
	links := &screensv1.PageLinkTabs{Scrolls: true}
	for _, t := range tabs {
		href := t[1]
		if raw != "" {
			href += "?" + url.Values{"fy": {raw}}.Encode()
		}
		links.Tabs = append(links.Tabs, &screensv1.PageLinkTab{Label: t[0], Href: href, Active: t[1] == Path})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: links}}
}

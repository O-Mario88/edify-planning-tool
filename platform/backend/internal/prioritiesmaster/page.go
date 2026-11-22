// Package prioritiesmaster builds Uganda Priorities (/priorities/master:
// apps.frontend.views.target_distribution_views.priorities_master_page, as
// the existing feed reads partials/priorities/master_view.html inside the
// Priorities rail): the year's Uganda master in its source's four columns —
// priorities, milestones, activities and targets — with each milestone's
// plan-linked progress. The target column is the country's figure, or for a
// Programme Lead the target their team received and their own share, or for
// a CCEO or Project Coordinator their own allocation.
//
// It reads; it never writes. The roles that run the master are sent to
// /target-distribution with the ask as it came. A query key the view does
// not read, a year the view would not read as Go does, a many-part ask sent
// on, and a master whose priorities hold no milestones are handed on. The
// doors and rails are exported to rules.json by `manage.py
// export_priorities_master_rules`;
// apps/hr/test_priorities_master_rules_export.py fails when the two differ.
package prioritiesmaster

import (
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
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
const Path = "/priorities/master"

// workspace is where the roles that run the master are sent.
const workspace = "/target-distribution"

const country = "Uganda"

//go:embed rules.json
var rulesJSON []byte

// door is what a role is given on the page.
type door struct {
	Runner bool        `json:"runner"`
	Scoped bool        `json:"scoped"`
	Lead   bool        `json:"lead"`
	Tabs   [][2]string `json:"tabs"`
}

var rules = func() (r struct {
	Roles     map[string]door `json:"roles"`
	MinFYYear int             `json:"min_fy_year"`
	MaxFYYear int             `json:"max_fy_year"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.Roles) == 0 || r.MaxFYYear == 0 {
		panic(fmt.Sprintf("prioritiesmaster: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var errPassOn = errors.New("prioritiesmaster: passed to the existing application")

// Service answers Uganda Priorities from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db, its moment read from now.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

// Build answers /priorities/master and /strategic-priorities; every other path is not its own.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path == StrategicPath {
		return s.buildStrategic(ctx, p, query)
	}
	if path != Path {
		return nil, false, nil
	}
	role, ok := rules.Roles[p.ActiveRole]
	if !ok {
		return nil, true, pagegate.ErrNotAvailable
	}
	resp, err := s.build(ctx, p, role, query)
	if errors.Is(err, errPassOn) {
		return nil, false, nil
	}
	if err != nil {
		return nil, true, err
	}
	return resp, true, nil
}

func (s *Service) build(ctx context.Context, p auth.Principal, role door, query url.Values) (*screensv1.GetPageResponse, error) {
	if role.Runner {
		// redirect(f"/target-distribution?{QUERY_STRING}"): one key reads
		// the same in any order; more would need the order it came in.
		if len(query) > 1 {
			return nil, fmt.Errorf("a many-part ask sent on: %w", errPassOn)
		}
		if len(query) == 0 {
			return &screensv1.GetPageResponse{Redirect: workspace}, nil
		}
		return &screensv1.GetPageResponse{Redirect: workspace + "?" + query.Encode()}, nil
	}
	for key, values := range query {
		if key != "fy" && strings.Join(values, "") != "" {
			return nil, fmt.Errorf("the query %q: %w", key, errPassOn)
		}
	}
	raw := strings.TrimSpace(query.Get("fy"))
	fy, err := s.year(ctx, raw)
	if err != nil {
		return nil, err
	}
	now := s.now()
	header := &screensv1.PageHeader{Eyebrow: "Strategy", Title: "Uganda Priorities"}
	switch {
	case role.Lead:
		header.Description = "The country plan with the target your team received from Impact Assessment and your own share of it once you distribute it within the team — neither is the country total."
	case role.Scoped:
		header.Description = "The country plan with your approved share of every target — the number in the last column is yours, not the country total."
	default:
		header.Description = "The Uganda Master Priority Plan, exactly as sourced — priorities, milestones, activities and Uganda's targets · FY " + fy + "."
	}
	view := []*screensv1.PageBlock{yearFilter(fy, schooldirectory.FYOptions(now))}
	if len(role.Tabs) >= 2 {
		view = append(view, rail(role.Tabs, raw))
	}
	m, err := readMaster(ctx, s.db, p, role, fy, time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC))
	if err != nil {
		return nil, err
	}
	if m == nil {
		view = append(view, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Empty{
			Empty: "The master plan appears here once it is seeded and confirmed."}})
	} else {
		view = append(view, m.blocks(role)...)
	}
	resp := &screensv1.GetPageResponse{Header: header, WebPath: Path, Blocks: view}
	if len(role.Tabs) >= 2 {
		// The feed reads the rail's panel under each of its tabs.
		segments := &screensv1.PageSegments{}
		for _, t := range role.Tabs {
			segments.Segments = append(segments.Segments, &screensv1.PageSegment{Label: t[0], Active: t[1] == Path, Blocks: view})
		}
		resp.Blocks = []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Segments{Segments: segments}}}
	}
	return resp, nil
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
		return "", fmt.Errorf("prioritiesmaster: reading the latest cycle: %w", err)
	}
	if latest != nil && *latest != "" {
		return *latest, nil
	}
	return schooldirectory.OperationalFY(s.now()), nil
}

// yearFilter is the year select over fy_options(); the feed reads the
// selected option, the first when the year is not among them.
func yearFilter(fy string, years []string) *screensv1.PageBlock {
	value := fy
	if !slices.Contains(years, fy) && len(years) > 0 {
		value = years[0]
	}
	filter := &screensv1.PageFilter{Name: "fy", Label: "Financial year", Value: value}
	for _, y := range years {
		filter.Options = append(filter.Options, &screensv1.PageFilterOption{Value: y, Label: "FY" + y})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{filter}}}}
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

// number is _fmt_number: a whole figure with commas, else its stored text
// with commas, then its unit (none for a percentage).
func number(text, unit string) string {
	r, ok := new(big.Rat).SetString(text)
	if !ok {
		return text
	}
	if r.IsInt() {
		text = r.Num().String()
	}
	whole, rest := text, ""
	if i := strings.IndexByte(text, '.'); i >= 0 {
		whole, rest = text[:i], text[i:]
	}
	sign := ""
	if strings.HasPrefix(whole, "-") {
		sign, whole = "-", whole[1:]
	}
	for i := len(whole) - 3; i > 0; i -= 3 {
		whole = whole[:i] + "," + whole[i:]
	}
	out := sign + whole + rest
	if unit != "" && unit != "percent" {
		out = strings.TrimSpace(out + " " + unit)
	}
	return out
}

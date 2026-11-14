// Package coverage is Coverage (/coverage): which of the reader's operating
// schools the programme reached with a completed visit in the year, by
// district, and the reader's clusters, as the existing page draws them
// (apps.frontend.views.extended_views.coverage_view and
// pages/coverage/index.html) and the app's feed reads them.
//
// The doors, the visit types, the statuses and the page size are exported to
// rules.json by `manage.py export_coverage_rules`;
// apps/schools/test_coverage_rules_export.py fails when the two differ.
package coverage

import (
	"cmp"
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"math"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/clusterpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page.
const Path = "/coverage"

//go:embed rules.json
var rulesJSON []byte

var rules = func() (r struct {
	PageRoles             []string `json:"page_roles"`
	DistrictProfileRoles  []string `json:"district_profile_roles"`
	VisitTypes            []string `json:"visit_types"`
	CompletedWorkStatuses []string `json:"completed_work_statuses"`
	OperatingStatuses     []string `json:"operating_statuses"`
	PageSize              int      `json:"page_size"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.VisitTypes) == 0 || r.PageSize == 0 {
		panic(fmt.Sprintf("coverage: the embedded rules are unreadable: %v", err))
	}
	return r
}()

// Service answers the page from the existing database.
type Service struct {
	db  schooldirectory.Querier
	now func() time.Time
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now}
}

type district struct {
	name                           string
	total, visited, unvisited, pct int
}

type cluster struct {
	name, districtID, district, status string
	schools                            int
}

// pct is round(n / max(total, 1) * 100), ties to even.
func pct(n, total int) int { return int(math.RoundToEven(float64(n) / float64(max(total, 1)) * 100)) }

// Build answers Path.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	options := schooldirectory.FYOptions(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if !slices.Contains(options, fy) {
		fy = schooldirectory.OperationalFY(now)
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, fmt.Errorf("coverage: resolving the reader's scope: %w", err)
	}
	args := []any{rules.OperatingStatuses}
	reach := "s.operational_status = ANY($1) AND " + schooldirectory.AnalyticsReach(scope, &args)
	args = append(args, rules.VisitTypes, rules.CompletedWorkStatuses, fy)
	n := len(args)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT COALESCE(d.name, ''), s.id IN (SELECT a.school_id FROM activity a WHERE a.activity_type = ANY($%d) AND a.status = ANY($%d)
  AND a.deleted_at IS NULL AND a.fy = $%d AND a.school_id IS NOT NULL), COALESCE(s.cluster_id, '')
FROM school s LEFT JOIN district d ON d.id = s.district_id WHERE %s`, n-2, n-1, n, reach), args...)
	if err != nil {
		return nil, true, fmt.Errorf("coverage: reading the schools: %w", err)
	}
	type school struct {
		district, cluster string
		visited           bool
	}
	schools, err := pgx.CollectRows(rows, func(r pgx.CollectableRow) (school, error) {
		var x school
		return x, r.Scan(&x.district, &x.visited, &x.cluster)
	})
	if err != nil {
		return nil, true, fmt.Errorf("coverage: reading the schools: %w", err)
	}
	byName, order := map[string]*district{}, []string{}
	perCluster := map[string]int{}
	visited := 0
	for _, x := range schools {
		name := x.district
		if name == "" {
			name = "No district"
		}
		d, ok := byName[name]
		if !ok {
			d = &district{name: name}
			byName[name] = d
			order = append(order, name)
		}
		d.total++
		if x.visited {
			d.visited++
			visited++
		}
		if x.cluster != "" {
			perCluster[x.cluster]++
		}
	}
	districts := []district{}
	for _, name := range order {
		d := *byName[name]
		d.unvisited, d.pct = d.total-d.visited, pct(d.visited, d.total)
		districts = append(districts, d)
	}
	slices.SortStableFunc(districts, func(a, b district) int {
		return cmp.Or(cmp.Compare(a.pct, b.pct), cmp.Compare(b.total, a.total), strings.Compare(a.name, b.name))
	})
	clusters, err := s.clusters(ctx, scope, perCluster)
	if err != nil {
		return nil, true, err
	}
	return page(p, fy, options, len(schools), visited, districts, clusters, query), true, nil
}

// clusters are the reader's clusters (cluster_queryset), held to an RVP's
// regions, by name, each with the reader's schools in it.
func (s *Service) clusters(ctx context.Context, scope schooldirectory.Scope, perCluster map[string]int) ([]cluster, error) {
	args := []any{}
	arg := func(v any) string {
		args = append(args, v)
		return "$" + strconv.Itoa(len(args))
	}
	where, err := clusterpage.ScopedClusters(ctx, s.db, scope, false, arg)
	if err != nil {
		return nil, fmt.Errorf("coverage: resolving the reader's clusters: %w", err)
	}
	if scope.RegionScope {
		ids := scope.RegionIDs
		if ids == nil {
			ids = []string{}
		}
		where += " AND d.region_id = ANY(" + arg(ids) + ")"
	}
	rows, err := s.db.Query(ctx, `SELECT c.id, c.name, COALESCE(d.id, ''), COALESCE(d.name, ''), COALESCE(c.status, '') FROM cluster c
LEFT JOIN district d ON d.id = c.district_id WHERE c.deleted_at IS NULL AND `+where+` ORDER BY c.name`, args...)
	if err != nil {
		return nil, fmt.Errorf("coverage: reading the clusters: %w", err)
	}
	return pgx.CollectRows(rows, func(r pgx.CollectableRow) (cluster, error) {
		var id string
		var c cluster
		err := r.Scan(&id, &c.name, &c.districtID, &c.district, &c.status)
		c.schools = perCluster[id]
		return c, err
	})
}

func cell(t string) *screensv1.PageCell { return &screensv1.PageCell{Text: closedschools.Collapse(t)} }

func numeric(labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, len(labels))
	for i, l := range labels {
		out[i] = &screensv1.PageColumn{Label: l, Numeric: i > 0}
	}
	return out
}

// title is |title: each word capitalised, the rest lower-cased.
func title(s string) string {
	out := []rune{}
	prev := false
	for _, r := range s {
		letter := (r >= 'a' && r <= 'z') || (r >= 'A' && r <= 'Z')
		switch {
		case letter && !prev:
			out = append(out, []rune(strings.ToUpper(string(r)))...)
		case letter:
			out = append(out, []rune(strings.ToLower(string(r)))...)
		default:
			out = append(out, r)
		}
		prev = letter
	}
	return string(out)
}

func intcomma(n int) string {
	s := strconv.Itoa(n)
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return s
}

// page is pages/coverage/index.html as the feed reads it.
func page(p auth.Principal, fy string, options []string, total, visited int, districts []district, clusters []cluster, query url.Values) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Time & Availability", Title: "Coverage",
		Description: "Which schools the program has actually reached with completed visits."}
	fyFilter := &screensv1.PageFilter{Name: "fy", Value: fy, Caption: "Financial Year"}
	for _, o := range options {
		fyFilter.Options = append(fyFilter.Options, &screensv1.PageFilterOption{Value: o, Label: "FY " + o})
	}
	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{Filters: []*screensv1.PageFilter{fyFilter}}}},
		{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{Title: "Performance overview", Metrics: []*screensv1.PageMetric{
			{Label: "Total Schools", Value: intcomma(total), Note: "active in program"},
			{Label: "Visited", Value: intcomma(visited), Note: "≥1 completed visit in FY" + fy},
			{Label: "Not Yet Visited", Value: intcomma(total - visited), Note: "awaiting first visit"},
			{Label: "Coverage Rate", Value: strconv.Itoa(pct(visited, total)) + "%"},
		}}}},
	}
	text := func(t string) *screensv1.PagePanelItem {
		return &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Text{Text: t}}
	}
	reach := "Reach by district · FY" + fy
	explained := "Least-reached districts first. This is where a redeployment decision starts."
	// A card with no table is read as one panel: its heading, its words and
	// its empty message.
	if len(districts) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: reach,
			Items: []*screensv1.PagePanelItem{text(explained), text("District reach appears once active schools are on the register.")}}}})
	} else {
		t := &screensv1.PageTable{Columns: numeric("District", "Schools", "Visited", "Not Yet", "Coverage")}
		for _, d := range districts {
			t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(d.name), cell(strconv.Itoa(d.total)),
				cell(strconv.Itoa(d.visited)), cell(strconv.Itoa(d.unvisited)), cell(strconv.Itoa(d.pct) + "%")}})
		}
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: reach}},
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{text(explained)}}}},
			&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	}
	if len(clusters) == 0 {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Clusters",
			Items: []*screensv1.PagePanelItem{text("Clusters appear as schools are grouped for operations.")}}}})
		return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Section{Section: "Clusters"}})
	links := slices.Contains(rules.DistrictProfileRoles, p.ActiveRole)
	size := rules.PageSize
	number, pages := closedschools.PageOf(query.Get("clusters_page"), len(clusters), size)
	t := &screensv1.PageTable{Columns: numeric("Cluster", "District", "Schools", "Status")}
	t.Columns[1].Numeric = false
	for _, c := range clusters[(number-1)*size : min(number*size, len(clusters))] {
		district := &screensv1.PageCell{Text: "—"}
		if c.district != "" {
			district.Text = closedschools.Collapse(c.district)
			if links && c.districtID != "" {
				district.Href = "/districts/" + c.districtID
			}
		}
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{cell(c.name), district, cell(strconv.Itoa(c.schools)),
			{Text: title(c.status), Tone: "primary", Badge: true}}})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}})
	if pages > 1 {
		blocks = append(blocks, closedschools.PagerPanel("clusters_page", number, pages, len(clusters), size, query, nil))
	}
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: Path}
}

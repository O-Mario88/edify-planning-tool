// Package reports is Programme Output Reports (/reports): verified delivery
// in the reader's country against the approved targets for a financial
// year, period by period, as the existing page draws it
// (apps.frontend.views.extended_views.reports_view and
// partials/analytics/panels/reports.html in the Analytics section shell)
// and the app's feed reads it.
//
// The door, the reporting areas, the achieved statuses and the quarters are
// exported to rules.json by `manage.py export_reports_rules`;
// apps/schools/test_reports_rules_export.py fails when the two differ.
package reports

import (
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

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/decisionlog"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// Path is the page.
const Path = "/reports"

// onTrack and atRisk are the page's thresholds.
const (
	onTrack = 70
	atRisk  = 50
)

//go:embed rules.json
var rulesJSON []byte

type area struct {
	Label      string   `json:"label"`
	Types      []string `json:"types"`
	TargetType string   `json:"target_type"`
}

var rules = func() (r struct {
	PageRoles        []string                      `json:"page_roles"`
	Strips           map[string]*decisionlog.Strip `json:"strips"`
	Areas            []area                        `json:"areas"`
	AchievedStatuses []string                      `json:"achieved_statuses"`
	Quarters         []struct {
		Key, Code, Label string
		Order            int
	} `json:"quarters"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil || len(r.PageRoles) == 0 || len(r.Areas) == 0 || len(r.Quarters) != 4 {
		panic(fmt.Sprintf("reports: the embedded rules are unreadable: %v", err))
	}
	return r
}()

var zone = func() *time.Location {
	z, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		panic(fmt.Sprintf("reports: loading the zone: %v", err))
	}
	return z
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

// period is one column of the timeline: its labels, which activities it
// holds, and whether it is still to come.
type period struct {
	chevron, kind, filter string
	dimmed                bool
	achieved              int
	target                float64
	hasTarget             bool
}

// cell is one area in one period.
type cell struct {
	achieved int
	target   *float64
	pct      *int
}

// pyRound is Python's round(): halves to even.
func pyRound(x float64) int { return int(math.RoundToEven(x)) }

// floatformat0 is |floatformat:0: halves away from zero.
func floatformat0(x float64) string { return strconv.FormatFloat(math.Round(x), 'f', 0, 64) }

// fixed0 is "{:.0f}": halves to even.
func fixed0(x float64) string { return strconv.FormatFloat(x, 'f', 0, 64) }

// periods is the chevron row in order: this month, Q1, Q2, the half year,
// Q3, Q4 and the year.
func periods(today time.Time, fy, operational string) []period {
	current := 0
	if fy == operational {
		switch m := today.Month(); {
		case m >= 10:
			current = 1
		case m <= 3:
			current = 2
		case m <= 6:
			current = 3
		default:
			current = 4
		}
	}
	quarter := func(i int) period {
		q := rules.Quarters[i]
		return period{chevron: q.Label, kind: "Quarter " + strconv.Itoa(q.Order), filter: "a.quarter = '" + q.Code + "'",
			dimmed: current != 0 && q.Order > current}
	}
	return []period{
		{chevron: today.Format("Jan 2006"), kind: "Monthly", filter: "a.month = " + strconv.Itoa(int(today.Month())), dimmed: fy != operational},
		quarter(0), quarter(1),
		{chevron: "Mid Year (Oct - Mar)", kind: "Cumulative", filter: "a.quarter IN ('Q1', 'Q2')", dimmed: current != 0 && current < 2},
		quarter(2), quarter(3),
		{chevron: "FY " + fy, kind: "Full Year", filter: "TRUE"},
	}
}

// Build answers Path.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path != Path {
		return nil, false, nil
	}
	if !slices.Contains(rules.PageRoles, p.ActiveRole) {
		return nil, true, pagegate.ErrNotAvailable
	}
	now := s.now()
	operational := schooldirectory.OperationalFY(now)
	choices := schooldirectory.FYOptions(now)
	fy := query.Get("fy")
	if !slices.Contains(choices, fy) {
		fy = operational
	}
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, fmt.Errorf("reports: resolving the reader's scope: %w", err)
	}
	local := now.In(zone)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	ps := periods(today, fy, operational)
	cells, err := s.achieved(ctx, scope, fy, ps)
	if err != nil {
		return nil, true, err
	}
	targets, err := s.targets(ctx, fy)
	if err != nil {
		return nil, true, err
	}
	matrix := make([][]cell, len(rules.Areas))
	for i, a := range rules.Areas {
		t, ok := targets[a.TargetType]
		for j := range ps {
			c := cell{achieved: cells[i][j]}
			if ok && a.TargetType != "" {
				c.target = &t
				if t != 0 {
					pct := pyRound(float64(c.achieved) / t * 100)
					c.pct = &pct
				}
			}
			matrix[i] = append(matrix[i], c)
			ps[j].achieved += c.achieved
			if c.target != nil && *c.target != 0 {
				ps[j].target += *c.target
				ps[j].hasTarget = true
			}
		}
	}
	return page(rules.Strips[p.ActiveRole], fy, choices, ps, matrix), true, nil
}

// achieved counts each area's verified work in each period of the year, in
// the reader's country.
func (s *Service) achieved(ctx context.Context, scope schooldirectory.Scope, fy string, ps []period) ([][]int, error) {
	args := []any{fy, rules.AchievedStatuses}
	where := "a.deleted_at IS NULL AND a.fy = $1"
	if scope.CountryScope && scope.Country != "" {
		args = append(args, scope.CountryIDs())
		where += " AND " + schoolprofile.ActivityInCountry(len(args))
	}
	cols := []string{}
	for _, a := range rules.Areas {
		args = append(args, a.Types)
		n := len(args)
		for _, p := range ps {
			cols = append(cols, fmt.Sprintf("count(*) FILTER (WHERE a.activity_type = ANY($%d) AND a.status = ANY($2) AND %s)", n, p.filter))
		}
	}
	out := make([]int, len(cols))
	dest := make([]any, len(cols))
	for i := range out {
		dest[i] = &out[i]
	}
	if err := s.db.QueryRow(ctx, `SELECT `+strings.Join(cols, ", ")+`
FROM activity a LEFT JOIN school s ON s.id = a.school_id LEFT JOIN cluster cl ON cl.id = a.cluster_id WHERE `+where, args...).Scan(dest...); err != nil {
		return nil, fmt.Errorf("reports: counting the verified work: %w", err)
	}
	grid := make([][]int, len(rules.Areas))
	for i := range grid {
		grid[i] = out[i*len(ps) : (i+1)*len(ps)]
	}
	return grid, nil
}

// targets is each target type's approved total for the year (a type whose
// rows carry no value has none).
func (s *Service) targets(ctx context.Context, fy string) (map[string]float64, error) {
	kinds := []string{}
	for _, a := range rules.Areas {
		if a.TargetType != "" {
			kinds = append(kinds, a.TargetType)
		}
	}
	rows, err := s.db.Query(ctx, `SELECT target_type, sum(target_value) FROM target_setting
WHERE fy = $1 AND target_type = ANY($2) AND is_active GROUP BY 1`, fy, kinds)
	if err != nil {
		return nil, fmt.Errorf("reports: reading the targets: %w", err)
	}
	defer rows.Close()
	out := map[string]float64{}
	for rows.Next() {
		var kind string
		var total *float64
		if err := rows.Scan(&kind, &total); err != nil {
			return nil, fmt.Errorf("reports: reading the targets: %w", err)
		}
		if total != nil {
			out[kind] = *total
		}
	}
	return out, rows.Err()
}

// Package dashboard builds a field officer's Home (/dashboard for a CCEO:
// apps.frontend.views.dashboard_views.dashboard_view and
// pages/dashboards/cceo.html, as the existing feed reads them): the header,
// the week at a glance, Do next, then This Week — "What needs you now" (the
// officer's past-due work) and the officer's own week
// (apps.analytics.pl_week_service, solo).
//
// It builds a Programme Lead's Home too (leadpage.go): This Week carrying the
// Planning Monitor and the Staff Activity Log.
//
// It reads; it never writes. It answers the officer's own tab of This Week
// for any week, and the lead's team tabs; it hands on the other views
// (Urgent schools, Map, the lead's Priorities to Collaboration), the other
// tabs (My week, My partners, the lead's Me and Partners), a pressed figure,
// a paged table, an acting seat and every other role. The statuses, labels, views and doors are exported to
// rules.json by `manage.py export_dashboard_rules`;
// apps/frontend/test_dashboard_rules_export.py fails when the two differ.
package dashboard

import (
	"context"
	_ "embed"
	"encoding/json"
	"fmt"
	"net/url"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/myplan"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Path is the page this package answers.
const Path = "/dashboard"

//go:embed rules.json
var rulesJSON []byte

type metric struct {
	Label  string `json:"label"`
	Helper string `json:"helper"`
	// Where the tile opens (CCEO_KPI_LINKS), "" for a tile that opens nothing.
	Href string `json:"href"`
}

var rules = func() (r struct {
	Officer struct {
		Role               string          `json:"role"`
		CompletedStatuses  []string        `json:"completed_statuses"`
		UnderWayStatuses   []string        `json:"under_way_statuses"`
		NotStartedStatuses []string        `json:"not_started_statuses"`
		DoneStatuses       []string        `json:"done_statuses"`
		ReturnedStatuses   []string        `json:"returned_statuses"`
		VisitTypes         []string        `json:"visit_types"`
		ClusterTypes       []string        `json:"cluster_types"`
		Metrics            []metric        `json:"metrics"`
		Views              [][2]string     `json:"views"`
		Opens              map[string]bool `json:"opens"`
	} `json:"officer"`
	Lead struct {
		Role                   string            `json:"role"`
		DefaultView            string            `json:"default_view"`
		Views                  []string          `json:"views"`
		ViewAliases            map[string]string `json:"view_aliases"`
		ViewTabs               [][2]string       `json:"view_tabs"`
		ReleasedStatuses       []string          `json:"released_statuses"`
		PartnerSettledStatuses []string          `json:"partner_settled_statuses"`
		CompletedStatuses      []string          `json:"completed_statuses"`
		TrainingTypes          []string          `json:"training_types"`
		SSACollectionTypes     []string          `json:"ssa_collection_types"`
		OperatingStatuses      []string          `json:"operating_statuses"`
		ApproverSeniority      map[string]int    `json:"approver_seniority"`
		ListRows               int               `json:"list_rows"`
		DelegatedBackDays      int               `json:"delegated_back_days"`
		AttentionLimit         int               `json:"attention_limit"`
		TeamOversightURL       string            `json:"team_oversight_url"`
		CCEOBacklogStatuses    []string          `json:"cceo_backlog_statuses"`
		NotInPlanStatuses      []string          `json:"not_in_plan_statuses"`
		VisitTypes             []string          `json:"visit_types"`
		ClusterMeetingTypes    []string          `json:"cluster_meeting_types"`
		SchoolCapacity         int               `json:"cceo_school_capacity"`
		WeeklyCapacity         int               `json:"cceo_weekly_activity_capacity"`
		LeaveLookaheadDays     int               `json:"leave_lookahead_days"`
		CardURLs               map[string]string `json:"card_urls"`
		Opens                  map[string]bool   `json:"opens"`
	} `json:"lead"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("dashboard: reading rules.json: %v", err))
	}
	o := r.Officer
	if o.Role == "" || len(o.Metrics) != 4 || len(o.Views) == 0 || len(o.DoneStatuses) == 0 ||
		r.Lead.Role == "" || len(r.Lead.ViewTabs) == 0 || len(r.Lead.OperatingStatuses) == 0 || r.Lead.ListRows == 0 {
		panic("dashboard: rules.json lacks the role, the figures, the views or the statuses")
	}
	return r
}()

// kampala is the page's local day.
var kampala = time.FixedZone("EAT", 3*60*60)

// Service builds the page.
type Service struct {
	db    schooldirectory.Querier
	now   func() time.Time
	cache *viewCache
}

// NewService is the page over db.
func NewService(db schooldirectory.Querier, now func() time.Time) *Service {
	return &Service{db: db, now: now, cache: newViewCache()}
}

// served is whether Go draws the page this query asks for: This Week (the
// view named, or none), the officer's own tab, no figure pressed and no
// table paged. Every other key the page reads is handed on.
func served(query url.Values) bool {
	for key, values := range query {
		value := ""
		if len(values) > 0 {
			value = strings.TrimSpace(values[0])
		}
		switch key {
		case "fy", "week":
			// The officer's Home reads the operational year whatever fy
			// says; the week is resolved below.
		case "view":
			switch strings.ToLower(value) {
			case "map":
				return false
			}
		case "who":
			if value == "everyone" || value == "partners" {
				return false
			}
		case "show":
			if myplan.ShowFilter(value) {
				return false
			}
		default:
			return false
		}
	}
	return true
}

// Build answers /dashboard for a field officer or a Programme Lead, and
// /analytics/country-director/drilldown for Country Director oversight.
func (s *Service) Build(ctx context.Context, p auth.Principal, path string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if path == CDDrilldownPath {
		return s.buildCDDrilldown(ctx, p, query)
	}
	// The desktop page differs from the phone's (its own header and the
	// parts marked mobile-home-hide), which Go does not build yet: a desktop
	// reading is the existing page's (pagegate.Desktop).
	if pagegate.Desktop(ctx) {
		return nil, false, nil
	}
	if path == Path && p.ActiveRole == rules.Lead.Role {
		return s.buildLead(ctx, p, query)
	}
	if path != Path || p.ActiveRole != rules.Officer.Role || !served(query) {
		return nil, false, nil
	}
	now := s.now()
	owners := myplan.OwnerIDs(p)
	local := now.In(kampala)
	today := time.Date(local.Year(), local.Month(), local.Day(), 0, 0, 0, 0, time.UTC)
	if strings.EqualFold(strings.TrimSpace(query.Get("view")), "operations") {
		return s.buildOfficerOperationsView(ctx, p, owners, today)
	}
	past, err := myplan.ReadPastDue(ctx, s.db, owners, now)
	if err != nil {
		return nil, true, err
	}
	if past.Paged {
		return nil, false, nil
	}
	start := myplan.ResolveWeek(query.Get("week"), today)
	week, err := myplan.ReadWeek(ctx, s.db, owners, p.StaffProfileID, start, now, operationalFY(now.UTC()), past.Total())
	if err != nil {
		return nil, true, err
	}
	if week.Paged {
		return nil, false, nil
	}
	home, err := s.readHome(ctx, owners, today)
	if err != nil {
		return nil, true, err
	}
	blocks := []*screensv1.PageBlock{home.strip()}
	blocks = append(blocks, home.doNext(past.Total())...)
	blocks = append(blocks, views(past, week)...)
	return &screensv1.GetPageResponse{
		Header:    home.header(today),
		Blocks:    blocks,
		WebPath:   Path,
		Selection: myplan.ActivityBar(),
	}, true, nil
}

// operationalFY is get_operational_fy: the year starts on 1 October.
func operationalFY(now time.Time) string {
	if now.Month() >= time.October {
		return fmt.Sprint(now.Year() + 1)
	}
	return fmt.Sprint(now.Year())
}

// views is This Week under the views' rail. With past-due work the feed
// reads the rail as segments, each drawing This Week (the kind chips hide
// the week's own rail from it); without, as link tabs above the blocks.
func views(past myplan.PastDue, week myplan.Week) []*screensv1.PageBlock {
	body := append(myplan.PastDueBlocks(past), myplan.WeekBlocks(week)...)
	if past.Total() == 0 {
		tabs := &screensv1.PageLinkTabs{Scrolls: true}
		for _, v := range rules.Officer.Views {
			tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: v[1], Href: Path + "?view=" + v[0], Active: v[0] == "week"})
		}
		return append([]*screensv1.PageBlock{{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}}}, body...)
	}
	segments := &screensv1.PageSegments{}
	if week.HasTables() {
		// The first table title band on the page is the week's.
		segments.Subtitle = "Ordered by date"
	}
	for _, v := range rules.Officer.Views {
		segments.Segments = append(segments.Segments, &screensv1.PageSegment{Label: v[1], Active: v[0] == "week", Blocks: body})
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Segments{Segments: segments}}}
}

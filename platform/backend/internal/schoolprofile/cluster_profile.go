package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const clusterPrefix = "/clusters/"

// clusterTabDefs are the Cluster Profile's tabs, in the page's order.
var clusterTabDefs = [][2]string{
	{"overview", "Overview"},
	{"schools", "Schools"},
	{"ssa", "SSA Performance"},
	{"activities", "Cluster Activities"},
	{"attendance", "Meeting Attendance"},
	{"member_activities", "Member School Activities"},
	{"analytics", "Cluster Analytics"},
}

// ClusterAccess is what one reader may do on one cluster's profile.
type ClusterAccess struct {
	// Readable is scoping.cluster_in_scope: outside it the cluster does not
	// exist for this reader.
	Readable bool
	// Plan schedules the cluster's group trainings and meetings.
	Plan bool
	// AddSchools opens the bulk add drawer.
	AddSchools bool
	// Edit is may_edit_cluster_profile.
	Edit bool
	// DeleteBlock is why the cluster cannot be deleted, when it cannot.
	DeleteBlock string
}

// ClusterWorkspace lends the profile what the Clusters page owns: who may
// read a cluster and its school roster (clusterpage reads this package, so
// it cannot be imported here).
type ClusterWorkspace interface {
	ProfileAccess(ctx context.Context, p auth.Principal, clusterID string) (ClusterAccess, error)
	Roster(ctx context.Context, p auth.Principal, clusterID, fy string) (*screensv1.GetPageResponse, error)
}

// WithClusterWorkspace gives the profiles the Cluster Profile page; without
// it the page stays the existing application's.
func (sp *ScopePages) WithClusterWorkspace(w ClusterWorkspace) *ScopePages {
	sp.s.clusterWorkspace = w
	return sp
}

type clusterDetail struct {
	id, name, subCounty, clusterType, status string
	districtID, districtName, regionName     string
	staffID, staffName                       string
	leaderName, leaderPhone                  string
	partnerID, partnerName                   string
}

type clusterActivityRow struct {
	id, activityType, status, title string
	plannedDate                     *time.Time
	schoolName, schoolCode          string
	ownerName                       string
	invited, attended               int
	teachers, leaders, other        int
	attendanceRows                  int
}

// clusterProfile draws /clusters/<id> and /clusters/<id>/profile: every
// figure from the profile engine over the cluster's operating schools, for a
// reader whose scope holds the cluster.
func (sp *ScopePages) clusterProfile(ctx context.Context, p auth.Principal, rawRest string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	rest := strings.TrimSuffix(strings.TrimSuffix(rawRest, "/"), "/profile")
	if rest == "" || strings.Contains(rest, "/") {
		return nil, false, nil
	}
	d := rules.Doors[p.ActiveRole]
	if !d.OpenCluster && !d.OpenDistrict && !d.Profile {
		return nil, true, pagegate.ErrNotAvailable
	}
	s := sp.s
	if s.clusterWorkspace == nil || s.clusterCards == nil {
		return nil, false, nil
	}
	access, err := s.clusterWorkspace.ProfileAccess(ctx, p, rest)
	if err != nil {
		return nil, true, err
	}
	if !access.Readable {
		return nil, true, ErrNotFound
	}
	cl, err := s.readClusterDetail(ctx, rest)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, ErrNotFound
	}
	if err != nil {
		return nil, true, err
	}

	now := s.now()
	running := schooldirectory.OperationalFY(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if !contains(fyChoices(running), fy) {
		fy = running
	}
	base := clusterPrefix + cl.id
	scope := scopeOf{kind: "cluster", key: cl.id, name: cl.name, covers: "Cluster schools", where: "s.cluster_id = $2", args: []any{cl.id}}
	factsOf := func(pr *scopeProfile) []*screensv1.PageFact { return clusterFacts(cl, pr, d.OpenStaff) }

	tab := strings.ToLower(strings.TrimSpace(query.Get("tab")))
	if !isClusterTab(tab) {
		tab = "overview"
	}
	header := clusterHeader(cl, access, base, fy)

	// The records behind a figure and the Schools tab's Show lists are the
	// engine's own pages, under this page's header and tabs.
	show := strings.TrimSpace(query.Get("show"))
	if query.Get("what") != "" || (tab == "schools" && show != "" && show != "all") {
		page := scopePage{scope: scope, base: base, back: [2]string{"Back to Clusters", "/clusters"}, facts: factsOf}
		answer, handled, err := s.scopePage(ctx, p, page, query)
		if err != nil || !handled {
			return answer, handled, err
		}
		answer.Header, answer.Tabs, answer.WebPath = header, clusterTabs(tab), base
		return answer, true, nil
	}

	today := kampalaDay(now)
	l := lens{tab: "overview", fy: fy, running: running, window: periodWindow(fy, ""), base: base, query: query}
	reader, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, true, err
	}
	pr, err := s.readScopeProfile(ctx, btReader{p: p, scope: reader, doors: d}, scope, l, now)
	if err != nil {
		return nil, true, err
	}
	ex, err := s.scopeExecutionFigures(ctx, pr, l, today)
	if err != nil {
		return nil, true, err
	}
	cards, err := s.clusterCards.Cards(ctx, []string{cl.id}, fy, today.Format("2006-01-02"))
	if err != nil {
		return nil, true, err
	}
	card := cards[cl.id]
	attention := pr.attentionLinks(l, d.Profile)
	ids := idsOf(pr.schools)

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: factsOf(pr)}}},
		clusterYearFilter(running, fy, tab),
		clusterSummaryStrip(pr, ex, len(attention), base, fy),
	}
	var selection *screensv1.PageSelection
	switch tab {
	case "overview", "schools":
		members, picked, err := s.clusterMembers(ctx, p, cl, pr, fy)
		if err != nil {
			return nil, true, err
		}
		selection = picked
		if tab == "overview" {
			history, err := s.clusterYearHistory(ctx, cl.id, ids, running)
			if err != nil {
				return nil, true, err
			}
			blocks = append(blocks, clusterSSARail(pr, l), history.chart(chartSSATrend), history.chart(chartVisitCoverage),
				history.chart(chartTrainingCoverage), history.chart(chartActionClosure), clusterReadiness(pr, d.Profile),
				clusterActivityStrip(ex, base, fy), clusterAttendanceStrip(ex, card, base, fy),
				clusterInsights(attention), clusterRecommended(cl, pr, ex, access, base, fy))
		}
		blocks = append(blocks, members)
	case "ssa":
		atTarget := 0
		for _, x := range pr.schools {
			if c := pr.scores[x.id].current; c != nil && *c >= rules.Engine.SSATarget {
				atTarget++
			}
		}
		progress, err := s.progressByYear(ctx, ids)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, clusterSSARail(pr, l))
		blocks = append(blocks, ssaSection(pr.cmp, pr.overall, atTarget, l, progress)...)
	case "activities", "member_activities", "attendance":
		activities, err := s.clusterActivities(ctx, cl.id, fy, ids)
		if err != nil {
			return nil, true, err
		}
		switch tab {
		case "activities":
			blocks = append(blocks, clusterActivityStrip(ex, base, fy), executionTable(ex, l),
				clusterActivitiesTable("Cluster Activities", sessionsOf(activities, true),
					"No cluster-wide activities are recorded for "+fyLabel(fy)+"."))
		case "member_activities":
			blocks = append(blocks, clusterActivitiesTable("Member School Activities", sessionsOf(activities, false),
				"No member school has an activity recorded for "+fyLabel(fy)+"."))
		default:
			participation, err := s.clusterParticipation(ctx, cl.id, fy, pr, s.clusterCards.AlertAfter())
			if err != nil {
				return nil, true, err
			}
			showMissing := strings.EqualFold(show, "missing")
			blocks = append(blocks, clusterAttendanceStrip(ex, card, base, fy), participation)
			blocks = append(blocks, clusterAttendanceBlocks(activities, showMissing, base, fy)...)
		}
	case "analytics":
		history, err := s.clusterYearHistory(ctx, cl.id, ids, running)
		if err != nil {
			return nil, true, err
		}
		blocks = append(blocks, history.chart(chartSSATrend), history.chart(chartSSACoverage), history.chart(chartVisitCoverage),
			history.chart(chartTrainingCoverage), history.chart(chartActionClosure))
	}
	return &screensv1.GetPageResponse{
		Header: header, Tabs: clusterTabs(tab), Blocks: blocks, Selection: selection, WebPath: base,
	}, true, nil
}

func isClusterTab(tab string) bool {
	for _, def := range clusterTabDefs {
		if def[0] == tab {
			return true
		}
	}
	return false
}

func clusterTabs(active string) []*screensv1.PageTab {
	tabs := make([]*screensv1.PageTab, 0, len(clusterTabDefs))
	for _, def := range clusterTabDefs {
		tabs = append(tabs, &screensv1.PageTab{Key: def[0], Label: def[1], Active: def[0] == active})
	}
	return tabs
}

func (s *Service) readClusterDetail(ctx context.Context, id string) (clusterDetail, error) {
	var cl clusterDetail
	err := s.db.QueryRow(ctx, `
SELECT c.id, c.name, COALESCE(NULLIF(c.sub_county_name, ''), sc.name, ''), COALESCE(c.cluster_type, ''), COALESCE(c.status, 'active'),
       COALESCE(c.district_id, ''), COALESCE(d.name, ''), COALESCE(r.name, ''),
       COALESCE(c.responsible_staff_id, ''), COALESCE(u.name, ''),
       COALESCE(c.cluster_leader_name, ''), COALESCE(c.cluster_leader_phone, ''),
       COALESCE(c.facilitating_partner_id, ''), COALESCE(pt.name, '')
FROM cluster c
LEFT JOIN sub_county sc ON sc.id = c.sub_county_id
LEFT JOIN district d ON d.id = c.district_id
LEFT JOIN region r ON r.id = COALESCE(c.region_id, d.region_id)
LEFT JOIN "user" u ON u.id = c.responsible_staff_id
LEFT JOIN partner pt ON pt.id = c.facilitating_partner_id
WHERE c.id = $1 AND c.deleted_at IS NULL`, id).Scan(
		&cl.id, &cl.name, &cl.subCounty, &cl.clusterType, &cl.status,
		&cl.districtID, &cl.districtName, &cl.regionName,
		&cl.staffID, &cl.staffName,
		&cl.leaderName, &cl.leaderPhone,
		&cl.partnerID, &cl.partnerName,
	)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return cl, fmt.Errorf("schoolprofile: reading cluster %s: %w", id, err)
	}
	return cl, err
}

// clusterActivities are the year's work of the cluster and of its schools,
// newest first.
func (s *Service) clusterActivities(ctx context.Context, clusterID, fy string, schoolIDs []string) ([]clusterActivityRow, error) {
	rows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(a.activity_type, ''), COALESCE(a.status, ''),
       COALESCE(NULLIF(a.activity_name_snapshot, ''), NULLIF(a.purpose_intervention, ''), a.activity_type, 'Activity'),
       COALESCE(a.planned_date, a.scheduled_date),
       COALESCE(s.name, ''), COALESCE(s.school_id, ''),
       COALESCE(u.name, ''),
       COALESCE((SELECT count(*) FROM cluster_activity_attendance caa WHERE caa.activity_id = a.id AND caa.invited), 0),
       COALESCE((SELECT count(*) FROM cluster_activity_attendance caa WHERE caa.activity_id = a.id AND caa.attended), 0),
       COALESCE(a.teachers_attended, 0), COALESCE(a.leaders_attended, 0), COALESCE(a.other_participants, 0),
       COALESCE((SELECT count(*) FROM cluster_activity_attendance caa WHERE caa.activity_id = a.id), 0)
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
LEFT JOIN "user" u ON u.id = a.responsible_staff_id
WHERE a.deleted_at IS NULL
  AND a.fy = $2
  AND (a.cluster_id = $1 OR a.school_id = ANY($3::text[]))
ORDER BY COALESCE(a.planned_date, a.scheduled_date) DESC NULLS LAST, a.created_at DESC
LIMIT 200`, clusterID, fy, schoolIDs)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading cluster activities: %w", err)
	}
	defer rows.Close()
	out := []clusterActivityRow{}
	for rows.Next() {
		var r clusterActivityRow
		if err := rows.Scan(&r.id, &r.activityType, &r.status, &r.title, &r.plannedDate,
			&r.schoolName, &r.schoolCode, &r.ownerName,
			&r.invited, &r.attended, &r.teachers, &r.leaders, &r.other, &r.attendanceRows); err != nil {
			return nil, fmt.Errorf("schoolprofile: scanning cluster activity: %w", err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// sessionsOf keeps the cluster-wide work (no school of its own) or the work
// at member schools.
func sessionsOf(all []clusterActivityRow, clusterWide bool) []clusterActivityRow {
	out := make([]clusterActivityRow, 0, len(all))
	for _, a := range all {
		if (a.schoolName == "") == clusterWide {
			out = append(out, a)
		}
	}
	return out
}

func makeCols(labels ...string) []*screensv1.PageColumn {
	out := make([]*screensv1.PageColumn, 0, len(labels))
	for _, lbl := range labels {
		out = append(out, &screensv1.PageColumn{Label: lbl})
	}
	return out
}

func formatLeader(name, phone string) string {
	if name == "" {
		return "Not assigned"
	}
	if phone != "" {
		return name + " (" + phone + ")"
	}
	return name
}

func hrefIf(cond bool, href string) string {
	if cond {
		return href
	}
	return ""
}

// region draws /regions/<id>: reuses the full multi-school ScopePages engine.
func (sp *ScopePages) region(ctx context.Context, p auth.Principal, id string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if id == "" || strings.Contains(id, "/") {
		return nil, false, nil
	}
	if !rules.Doors[p.ActiveRole].OpenSubRegion && !rules.Doors[p.ActiveRole].OpenDistrict {
		return nil, true, pagegate.ErrNotAvailable
	}
	s := sp.s
	var name, country string
	err := s.db.QueryRow(ctx, `SELECT name, COALESCE(country, '') FROM region WHERE id = $1`, id).Scan(&name, &country)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, ErrNotFound
	}
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading region: %w", err)
	}
	scope := scopeOf{
		kind:   "sub_region",
		key:    id,
		name:   name + " Region",
		covers: "All schools in the region",
		where:  "(s.region_id = $2 OR d.region_id = $2)",
		args:   []any{id},
	}
	page := scopePage{
		scope: scope,
		base:  regionPrefix + id,
		back:  [2]string{"Back to Country Profile", "/country-profile"},
		lead:  country,
	}
	page.facts = func(pr *scopeProfile) []*screensv1.PageFact {
		districts := map[string]bool{}
		for _, x := range pr.schools {
			if x.district != "" {
				districts[x.district] = true
			}
		}
		open := rules.Doors[p.ActiveRole].OpenStaff
		return []*screensv1.PageFact{
			{Label: "Type", Value: "Region"},
			{Label: "Country", Value: orDash(country)},
			{Label: "Districts", Value: strconv.Itoa(len(districts))},
			peopleFact("Programme Lead", pr.leads, open, "/staff/"),
			peopleFact("Staff", pr.staff, open, "/staff/"),
		}
	}
	return s.scopePage(ctx, p, page, query)
}

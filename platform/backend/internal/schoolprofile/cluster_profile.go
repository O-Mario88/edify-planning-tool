package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"math"
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

type clusterDetail struct {
	id, name, subCounty, clusterType, status string
	districtID, districtName, regionName     string
	staffID, staffName                       string
	leaderName, leaderPhone                  string
	partnerID, partnerName                   string
}

type clusterSchoolRow struct {
	id, code, name, schoolType string
	ssaStatus, readiness       string
	hasGPS                     bool
	gpsVerified                bool
	ssaAvg                     *float64
	visitsPlanned, visitsDone  int
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

// clusterProfile draws /clusters/<id> and /clusters/<id>/profile with real
// PostgreSQL data across Overview, Schools, Attendance, Activities, and SSA tabs.
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
	var cl clusterDetail
	err := s.db.QueryRow(ctx, `
SELECT c.id, c.name, COALESCE(c.sub_county_name, ''), COALESCE(c.cluster_type, ''), COALESCE(c.status, 'active'),
       COALESCE(c.district_id, ''), COALESCE(d.name, ''), COALESCE(r.name, ''),
       COALESCE(c.responsible_staff_id, ''), COALESCE(u.name, ''),
       COALESCE(c.cluster_leader_name, ''), COALESCE(c.cluster_leader_phone, ''),
       COALESCE(c.facilitating_partner_id, ''), COALESCE(pt.name, '')
FROM cluster c
LEFT JOIN district d ON d.id = c.district_id
LEFT JOIN region r ON r.id = COALESCE(c.region_id, d.region_id)
LEFT JOIN "user" u ON u.id = c.responsible_staff_id
LEFT JOIN partner pt ON pt.id = c.facilitating_partner_id
WHERE c.id = $1 AND c.deleted_at IS NULL`, rest).Scan(
		&cl.id, &cl.name, &cl.subCounty, &cl.clusterType, &cl.status,
		&cl.districtID, &cl.districtName, &cl.regionName,
		&cl.staffID, &cl.staffName,
		&cl.leaderName, &cl.leaderPhone,
		&cl.partnerID, &cl.partnerName,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, ErrNotFound
	}
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading cluster %s: %w", rest, err)
	}

	now := s.now()
	running := schooldirectory.OperationalFY(now)
	fy := strings.TrimSpace(query.Get("fy"))
	knownFY := false
	for _, y := range fyChoices(running) {
		if y == fy {
			knownFY = true
		}
	}
	if !knownFY {
		fy = running
	}

	// Read all member schools of this cluster (active membership or school.cluster_id).
	sRows, err := s.db.Query(ctx, `
SELECT DISTINCT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(s.school_type, ''),
       COALESCE(s.current_fy_ssa_status, ''), COALESCE(s.planning_readiness, ''),
       (COALESCE(sl.lat, vl.lat, gp.latitude, s.latitude) IS NOT NULL
        AND COALESCE(sl.lng, vl.lng, gp.longitude, s.longitude) IS NOT NULL) AS has_gps,
       (sl.lat IS NOT NULL OR vl.lat IS NOT NULL) AS gps_verified,
       (SELECT avg(sr.average_score) FROM ssa_record sr
        WHERE sr.school_id = s.id AND sr.fy = $2 AND sr.deleted_at IS NULL) AS ssa_avg,
       (SELECT count(*) FROM activity a
        WHERE a.school_id = s.id AND a.fy = $2 AND a.deleted_at IS NULL
          AND NOT (a.status = ANY($3))) AS planned_cnt,
       (SELECT count(*) FROM activity a
        WHERE a.school_id = s.id AND a.fy = $2 AND a.deleted_at IS NULL
          AND a.status = ANY($4)) AS done_cnt
FROM school s
LEFT JOIN field_routes.school_location sl ON sl.school_id = s.id AND sl.target = 'school'
LEFT JOIN field_routes.verified_location vl ON vl.school_id = s.id
LEFT JOIN school_geo_point gp ON gp.school_id = s.id
WHERE s.deleted_at IS NULL
  AND (
    s.cluster_id = $1
    OR EXISTS (SELECT 1 FROM school_cluster_membership m WHERE m.school_id = s.id AND m.cluster_id = $1 AND m.ended_at IS NULL)
    OR EXISTS (SELECT 1 FROM school_cluster_assignment sca WHERE sca.school_id = s.id AND sca.cluster_id = $1)
  )
ORDER BY s.name`, cl.id, fy, rules.Engine.NotInPlanStatuses, rules.Engine.CompletedWorkStatuses)
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading cluster schools: %w", err)
	}
	defer sRows.Close()

	var schools []clusterSchoolRow
	schoolIDs := make([]string, 0)
	var gpsCount, coreCount, ssaDoneCount, totalVisitsPlanned, totalVisitsDone int
	var ssaSum float64
	var ssaRated int
	for sRows.Next() {
		var r clusterSchoolRow
		if err := sRows.Scan(&r.id, &r.code, &r.name, &r.schoolType, &r.ssaStatus, &r.readiness,
			&r.hasGPS, &r.gpsVerified, &r.ssaAvg, &r.visitsPlanned, &r.visitsDone); err != nil {
			return nil, true, fmt.Errorf("schoolprofile: scanning cluster school: %w", err)
		}
		schools = append(schools, r)
		schoolIDs = append(schoolIDs, r.id)
		if r.hasGPS {
			gpsCount++
		}
		if strings.Contains(strings.ToLower(r.schoolType), "core") {
			coreCount++
		}
		if r.ssaAvg != nil {
			ssaDoneCount++
			ssaSum += *r.ssaAvg
			ssaRated++
		} else if strings.EqualFold(r.ssaStatus, "done") || strings.EqualFold(r.ssaStatus, "completed") {
			ssaDoneCount++
		}
		totalVisitsPlanned += r.visitsPlanned
		totalVisitsDone += r.visitsDone
	}
	if err := sRows.Err(); err != nil {
		return nil, true, err
	}

	// Read cluster activities & attendance records for this FY.
	aRows, err := s.db.Query(ctx, `
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
  AND (a.cluster_id = $1 OR (cardinality($3::text[]) > 0 AND a.school_id = ANY($3::text[])))
ORDER BY COALESCE(a.planned_date, a.scheduled_date) DESC NULLS LAST, a.created_at DESC
LIMIT 120`, cl.id, fy, schoolIDs)
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading cluster activities: %w", err)
	}
	defer aRows.Close()

	var activities []clusterActivityRow
	var clusterSessions, sessionsDone, missingAttendance int
	for aRows.Next() {
		var r clusterActivityRow
		if err := aRows.Scan(&r.id, &r.activityType, &r.status, &r.title, &r.plannedDate,
			&r.schoolName, &r.schoolCode, &r.ownerName,
			&r.invited, &r.attended, &r.teachers, &r.leaders, &r.other, &r.attendanceRows); err != nil {
			return nil, true, fmt.Errorf("schoolprofile: scanning cluster activity: %w", err)
		}
		activities = append(activities, r)
		if r.schoolName == "" {
			clusterSessions++
			if contains(rules.Engine.CompletedWorkStatuses, r.status) {
				sessionsDone++
				if r.attendanceRows == 0 && r.teachers+r.leaders+r.other == 0 {
					missingAttendance++
				}
			}
		}
	}
	if err := aRows.Err(); err != nil {
		return nil, true, err
	}

	tab := strings.ToLower(strings.TrimSpace(query.Get("tab")))
	validTabs := []string{"overview", "schools", "attendance", "activities", "ssa"}
	if !contains(validTabs, tab) {
		tab = "overview"
	}
	base := clusterPrefix + cl.id
	tabDefs := [][2]string{
		{"overview", "Overview"},
		{"schools", fmt.Sprintf("Schools (%d)", len(schools))},
		{"attendance", "Attendance"},
		{"activities", fmt.Sprintf("Activities (%d)", len(activities))},
		{"ssa", "SSA & Outcomes"},
	}
	tabs := make([]*screensv1.PageTab, 0, len(tabDefs))
	for _, td := range tabDefs {
		tabs = append(tabs, &screensv1.PageTab{Key: td[0], Label: td[1], Active: td[0] == tab})
	}

	// Header & Action Links
	descParts := []string{"Cluster Profile"}
	if cl.districtName != "" {
		descParts = append(descParts, cl.districtName+" District")
	}
	if cl.subCounty != "" {
		descParts = append(descParts, cl.subCounty)
	}
	descParts = append(descParts, fyLabel(fy))
	header := &screensv1.PageHeader{
		Eyebrow:     "Clusters",
		BackLabel:   "Back to Clusters",
		BackHref:    "/clusters",
		Title:       cl.name,
		Description: strings.Join(descParts, " · "),
		Badges: []*screensv1.PageBadge{
			{Text: strings.ToUpper(cl.status), Tone: "positive"},
		},
		Actions: []*screensv1.PageAction{
			{Key: "route", Label: "Plan Cluster Route", Enabled: true, Primary: true,
				Href: "/my-plan/smart-route?cluster=" + url.QueryEscape(cl.id)},
			{Key: "oversight", Label: "Cluster Oversight", Enabled: true, Href: "/cluster-oversight"},
		},
	}
	if cl.clusterType != "" {
		header.Badges = append(header.Badges, &screensv1.PageBadge{Text: cl.clusterType, Tone: "neutral"})
	}

	// Facts bar
	facts := []*screensv1.PageFact{
		{Label: "District", Value: orDash(cl.districtName), Href: hrefIf(cl.districtID != "", "/districts/"+cl.districtID)},
		{Label: "Sub-county", Value: orDash(cl.subCounty)},
		{Label: "Responsible Staff", Value: orDash(cl.staffName), Href: hrefIf(cl.staffID != "", "/staff/"+cl.staffID)},
		{Label: "Cluster Leader", Value: formatLeader(cl.leaderName, cl.leaderPhone)},
	}
	if cl.partnerName != "" {
		facts = append(facts, &screensv1.PageFact{Label: "Facilitating Partner", Value: cl.partnerName, Href: "/partners/" + cl.partnerID})
	}
	facts = append(facts, &screensv1.PageFact{Label: "Fiscal Year", Value: fyLabel(fy)})

	// FY Filter
	fyOpts := make([]*screensv1.PageFilterOption, 0)
	for _, y := range fyChoices(running) {
		fyOpts = append(fyOpts, &screensv1.PageFilterOption{Value: y, Label: fyLabel(y)})
	}
	filters := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: []*screensv1.PageFilter{{Name: "fy", Label: "Fiscal Year", Value: fy, Options: fyOpts}},
		Hidden:  map[string]string{"tab": tab},
	}}}

	// KPI Strip
	gpsPct := 0
	ssaPct := 0
	if len(schools) > 0 {
		gpsPct = int(math.Round(float64(gpsCount) * 100 / float64(len(schools))))
		ssaPct = int(math.Round(float64(ssaDoneCount) * 100 / float64(len(schools))))
	}
	avgSSAStr := "—"
	if ssaRated > 0 {
		avgSSAStr = fmt.Sprintf("%.1f/10", ssaSum/float64(ssaRated))
	}
	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Cluster Performance Snapshot",
		Metrics: []*screensv1.PageMetric{
			{Label: "Member Schools", Value: intcomma(len(schools)), Note: fmt.Sprintf("%d Core", coreCount), Href: base + "?tab=schools&fy=" + fy},
			{Label: "GPS Coverage", Value: fmt.Sprintf("%d/%d", gpsCount, len(schools)), Note: fmt.Sprintf("%d%% geo-located", gpsPct), Href: base + "?tab=schools&fy=" + fy},
			{Label: "SSA Coverage", Value: fmt.Sprintf("%d%%", ssaPct), Note: fmt.Sprintf("Avg %s", avgSSAStr), Href: base + "?tab=ssa&fy=" + fy},
			{Label: "Cluster Sessions", Value: fmt.Sprintf("%d/%d", sessionsDone, clusterSessions), Note: "completed / planned", Href: base + "?tab=attendance&fy=" + fy},
			{Label: "School Visits", Value: fmt.Sprintf("%d/%d", totalVisitsDone, totalVisitsPlanned), Note: "completed / planned", Href: base + "?tab=activities&fy=" + fy},
		},
	}}}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		filters,
		strip,
	}

	switch tab {
	case "overview":
		blocks = append(blocks, clusterOverviewPanels(cl, schools, activities, missingAttendance, base, fy)...)
	case "schools":
		blocks = append(blocks, clusterSchoolsTable(schools))
	case "attendance":
		showMissing := strings.EqualFold(strings.TrimSpace(query.Get("show")), "missing")
		blocks = append(blocks, clusterAttendanceBlocks(activities, showMissing, base, fy)...)
	case "activities":
		blocks = append(blocks, clusterActivitiesTable(activities))
	case "ssa":
		blocks = append(blocks, clusterSSATable(schools, fy))
	}

	return &screensv1.GetPageResponse{
		Header:  header,
		Tabs:    tabs,
		Blocks:  blocks,
		WebPath: base,
	}, true, nil
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

func clusterOverviewPanels(cl clusterDetail, schools []clusterSchoolRow, activities []clusterActivityRow, missingAttendance int, base, fy string) []*screensv1.PageBlock {
	var out []*screensv1.PageBlock
	items := []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Text{Text: fmt.Sprintf(
			"%s currently brings together %d active school(s) in %s District.",
			cl.name, len(schools), orDash(cl.districtName))}},
	}
	if missingAttendance > 0 {
		items = append(items, &screensv1.PagePanelItem{
			Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{
				Links: []*screensv1.PageLink{{
					Text: fmt.Sprintf("%d completed cluster session(s) missing attendance records — review now", missingAttendance),
					Href: base + "?tab=attendance&show=missing&fy=" + fy,
				}},
			}},
		})
	}
	out = append(out, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Cluster Summary",
		Items: items,
	}}})
	// Show top schools & recent activities directly on overview
	if len(schools) > 0 {
		limit := min(10, len(schools))
		out = append(out, clusterSchoolsTable(schools[:limit]))
	}
	if len(activities) > 0 {
		limit := min(8, len(activities))
		out = append(out, clusterActivitiesTable(activities[:limit]))
	}
	return out
}

func clusterSchoolsTable(schools []clusterSchoolRow) *screensv1.PageBlock {
	rows := make([]*screensv1.PageRow, 0, len(schools))
	for _, sc := range schools {
		gpsLabel := "Missing GPS"
		gpsTone := "attention"
		if sc.gpsVerified {
			gpsLabel = "Verified GPS"
			gpsTone = "positive"
		} else if sc.hasGPS {
			gpsLabel = "Recorded GPS"
			gpsTone = "info"
		}
		ssaTxt := "Not assessed"
		if sc.ssaAvg != nil {
			ssaTxt = fmt.Sprintf("%.1f/10", *sc.ssaAvg)
		}
		ref := sc.code
		if ref == "" {
			ref = sc.id
		}
		rows = append(rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: orDash(sc.code)},
				{Text: sc.name, Href: "/schools/" + url.PathEscape(ref)},
				{Text: orDash(sc.schoolType)},
				{Text: gpsLabel, Tone: gpsTone},
				{Text: ssaTxt},
				{Text: fmt.Sprintf("%d / %d", sc.visitsDone, sc.visitsPlanned)},
			},
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:        "Cluster Member Schools",
		Columns:      makeCols("School ID", "School Name", "Type", "GPS", "SSA Score", "Visits (Done/Planned)"),
		Rows:         rows,
		EmptyMessage: "No active schools are currently assigned to this cluster.",
	}}}
}

func clusterAttendanceBlocks(activities []clusterActivityRow, showMissing bool, base, fy string) []*screensv1.PageBlock {
	var rows []*screensv1.PageRow
	for _, a := range activities {
		if a.schoolName != "" {
			continue // cluster-level sessions only
		}
		missing := a.attendanceRows == 0 && a.teachers+a.leaders+a.other == 0
		if showMissing && !missing {
			continue
		}
		dateStr := "—"
		if a.plannedDate != nil {
			dateStr = a.plannedDate.Format("02 Jan 2006")
		}
		attText := fmt.Sprintf("%d/%d schools · %d participants", a.attended, a.invited, a.teachers+a.leaders+a.other)
		tone := "positive"
		if missing {
			attText = "Attendance missing"
			tone = "attention"
		}
		rows = append(rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: dateStr},
				{Text: a.title, Href: "/activities/" + a.id},
				{Text: a.activityType},
				{Text: a.status},
				{Text: attText, Tone: tone},
				{Text: orDash(a.ownerName)},
			},
		})
	}
	caption := "Cluster Session Attendance"
	if showMissing {
		caption = "Cluster Sessions Missing Attendance"
	}
	filterLink := &screensv1.PageLink{Text: "Show sessions missing attendance", Href: base + "?tab=attendance&show=missing&fy=" + fy}
	if showMissing {
		filterLink = &screensv1.PageLink{Text: "Show all cluster sessions", Href: base + "?tab=attendance&fy=" + fy}
	}
	return []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
			Title: "Attendance Filter",
			Items: []*screensv1.PagePanelItem{{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{filterLink}}}}},
		}}},
		{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        caption,
			Columns:      makeCols("Date", "Session", "Type", "Status", "Attendance", "Lead Staff"),
			Rows:         rows,
			EmptyMessage: "No cluster sessions match this attendance filter for " + fyLabel(fy) + ".",
		}}},
	}
}

func clusterActivitiesTable(activities []clusterActivityRow) *screensv1.PageBlock {
	rows := make([]*screensv1.PageRow, 0, len(activities))
	for _, a := range activities {
		dateStr := "—"
		if a.plannedDate != nil {
			dateStr = a.plannedDate.Format("02 Jan 2006")
		}
		whereCell := &screensv1.PageCell{Text: "Cluster-wide"}
		if a.schoolName != "" {
			ref := a.schoolCode
			if ref == "" {
				ref = a.schoolName
			}
			whereCell = &screensv1.PageCell{Text: a.schoolName, Href: "/schools/" + url.PathEscape(ref)}
		}
		rows = append(rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: dateStr},
				{Text: a.title, Href: "/activities/" + a.id},
				{Text: a.activityType},
				whereCell,
				{Text: a.status},
				{Text: orDash(a.ownerName)},
			},
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:        "Cluster & Member School Activities",
		Columns:      makeCols("Date", "Activity", "Type", "Location", "Status", "Owner"),
		Rows:         rows,
		EmptyMessage: "No activities recorded for this cluster in the selected fiscal year.",
	}}}
}

func clusterSSATable(schools []clusterSchoolRow, fy string) *screensv1.PageBlock {
	rows := make([]*screensv1.PageRow, 0, len(schools))
	for _, sc := range schools {
		score := "Not assessed"
		tone := "attention"
		if sc.ssaAvg != nil {
			score = fmt.Sprintf("%.1f / 10", *sc.ssaAvg)
			if *sc.ssaAvg >= 7.0 {
				tone = "positive"
			} else if *sc.ssaAvg >= 5.0 {
				tone = "info"
			}
		}
		ref := sc.code
		if ref == "" {
			ref = sc.id
		}
		rows = append(rows, &screensv1.PageRow{
			Cells: []*screensv1.PageCell{
				{Text: orDash(sc.code)},
				{Text: sc.name, Href: "/schools/" + url.PathEscape(ref)},
				{Text: orDash(sc.schoolType)},
				{Text: score, Tone: tone},
				{Text: orDash(sc.ssaStatus)},
				{Text: orDash(sc.readiness)},
			},
		})
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
		Title:        "School Self-Assessment (SSA) Coverage — " + fyLabel(fy),
		Columns:      makeCols("School ID", "School Name", "Type", "Average SSA", "SSA Status", "Planning Readiness"),
		Rows:         rows,
		EmptyMessage: "No schools in this cluster yet.",
	}}}
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

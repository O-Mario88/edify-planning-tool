package schoolprofile

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

const (
	regionPrefix = "/regions/"
	staffPrefix  = "/staff/"
	userPrefix   = "/users/"
)

type staffDetail struct {
	userID, staffProfileID, name, email, phone string
	roles                                      []string
	activeRole, status                         string
	staffNumber, title, department, country    string
	districtID, districtName                   string
}

// staffProfile draws /staff/<id> and /users/<id> (resolving either user.id or
// staff_profile.id) with real portfolio KPIs, assigned schools, clusters, and activities.
func (sp *ScopePages) staffProfile(ctx context.Context, p auth.Principal, prefix, rawID string, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	id := strings.TrimSuffix(rawID, "/")
	if id == "" || strings.Contains(id, "/") {
		return nil, false, nil
	}
	d := rules.Doors[p.ActiveRole]
	if !d.OpenStaff && p.UserID != id && p.StaffProfileID != id {
		return nil, true, pagegate.ErrNotAvailable
	}

	s := sp.s
	var st staffDetail
	err := s.db.QueryRow(ctx, `
SELECT u.id, COALESCE(sp.id, ''), COALESCE(u.name, ''), COALESCE(u.email, ''), COALESCE(u.phone, ''),
       COALESCE(u.roles, ARRAY[]::text[]), COALESCE(u.active_role, ''), COALESCE(u.status, 'active'),
       COALESCE(sp.staff_number, ''), COALESCE(sp.title, ''), COALESCE(sp.department, ''), COALESCE(sp.country, 'UG'),
       COALESCE(sp.primary_district_id, ''), COALESCE(d.name, '')
FROM "user" u
LEFT JOIN staff_profile sp ON sp.user_id = u.id AND sp.deleted_at IS NULL
LEFT JOIN district d ON d.id = sp.primary_district_id
WHERE (u.id = $1 OR sp.id = $1) AND u.deleted_at IS NULL
LIMIT 1`, id).Scan(
		&st.userID, &st.staffProfileID, &st.name, &st.email, &st.phone,
		&st.roles, &st.activeRole, &st.status,
		&st.staffNumber, &st.title, &st.department, &st.country,
		&st.districtID, &st.districtName,
	)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, true, ErrNotFound
	}
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading staff %s: %w", id, err)
	}

	now := s.now()
	running := schooldirectory.OperationalFY(now)
	fy := strings.TrimSpace(query.Get("fy"))
	if !contains(fyChoices(running), fy) {
		fy = running
	}

	ownerIDs := []string{st.userID}
	if st.staffProfileID != "" && st.staffProfileID != st.userID {
		ownerIDs = append(ownerIDs, st.staffProfileID)
	}

	// Assigned schools
	type staffSchool struct {
		id, code, name, district, schoolType, ssaStatus string
		hasGPS                                          bool
	}
	sRows, err := s.db.Query(ctx, `
SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(d.name, ''), COALESCE(s.school_type, ''),
       COALESCE(s.current_fy_ssa_status, ''),
       (COALESCE(sl.lat, vl.lat, gp.latitude, s.latitude) IS NOT NULL
        AND COALESCE(sl.lng, vl.lng, gp.longitude, s.longitude) IS NOT NULL)
FROM school s
LEFT JOIN district d ON d.id = s.district_id
LEFT JOIN field_routes.school_location sl ON sl.school_id = s.id AND sl.target = 'school'
LEFT JOIN field_routes.verified_location vl ON vl.school_id = s.id
LEFT JOIN school_geo_point gp ON gp.school_id = s.id
WHERE s.deleted_at IS NULL AND s.account_owner_id = ANY($1)
ORDER BY s.name LIMIT 100`, ownerIDs)
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading staff schools: %w", err)
	}
	defer sRows.Close()
	var schools []staffSchool
	var coreCount, gpsCount int
	for sRows.Next() {
		var r staffSchool
		if err := sRows.Scan(&r.id, &r.code, &r.name, &r.district, &r.schoolType, &r.ssaStatus, &r.hasGPS); err != nil {
			return nil, true, err
		}
		schools = append(schools, r)
		if strings.Contains(strings.ToLower(r.schoolType), "core") {
			coreCount++
		}
		if r.hasGPS {
			gpsCount++
		}
	}

	// Clusters managed by staff
	type staffCluster struct {
		id, name, district, status string
		schoolCount                int
	}
	cRows, err := s.db.Query(ctx, `
SELECT c.id, c.name, COALESCE(d.name, ''), COALESCE(c.status, 'active'),
       (SELECT count(*) FROM school s WHERE s.cluster_id = c.id AND s.deleted_at IS NULL)
FROM cluster c
LEFT JOIN district d ON d.id = c.district_id
WHERE c.deleted_at IS NULL AND c.responsible_staff_id = ANY($1)
ORDER BY c.name LIMIT 60`, ownerIDs)
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading staff clusters: %w", err)
	}
	defer cRows.Close()
	var clusters []staffCluster
	for cRows.Next() {
		var r staffCluster
		if err := cRows.Scan(&r.id, &r.name, &r.district, &r.status, &r.schoolCount); err != nil {
			return nil, true, err
		}
		clusters = append(clusters, r)
	}

	// Recent FY activities
	type staffAct struct {
		id, title, actType, status, schoolName, schoolCode string
		plannedDate                                        *time.Time
	}
	aRows, err := s.db.Query(ctx, `
SELECT a.id, COALESCE(NULLIF(a.activity_name_snapshot, ''), NULLIF(a.purpose_intervention, ''), a.activity_type, 'Activity'),
       COALESCE(a.activity_type, ''), COALESCE(a.status, ''),
       COALESCE(s.name, ''), COALESCE(s.school_id, ''),
       COALESCE(a.planned_date, a.scheduled_date)
FROM activity a
LEFT JOIN school s ON s.id = a.school_id
WHERE a.deleted_at IS NULL AND a.fy = $2 AND a.responsible_staff_id = ANY($1)
ORDER BY COALESCE(a.planned_date, a.scheduled_date) DESC NULLS LAST
LIMIT 80`, ownerIDs, fy)
	if err != nil {
		return nil, true, fmt.Errorf("schoolprofile: reading staff activities: %w", err)
	}
	defer aRows.Close()
	var acts []staffAct
	var doneActs int
	for aRows.Next() {
		var r staffAct
		if err := aRows.Scan(&r.id, &r.title, &r.actType, &r.status, &r.schoolName, &r.schoolCode, &r.plannedDate); err != nil {
			return nil, true, err
		}
		acts = append(acts, r)
		if contains(rules.Engine.CompletedWorkStatuses, r.status) {
			doneActs++
		}
	}

	tab := strings.ToLower(strings.TrimSpace(query.Get("tab")))
	if !contains([]string{"overview", "schools", "clusters", "activities"}, tab) {
		tab = "overview"
	}
	base := prefix + st.userID
	tabs := []*screensv1.PageTab{
		{Key: "overview", Label: "Overview", Active: tab == "overview"},
		{Key: "schools", Label: fmt.Sprintf("Schools (%d)", len(schools)), Active: tab == "schools"},
		{Key: "clusters", Label: fmt.Sprintf("Clusters (%d)", len(clusters)), Active: tab == "clusters"},
		{Key: "activities", Label: fmt.Sprintf("Activities (%d)", len(acts)), Active: tab == "activities"},
	}

	roleLabel := st.activeRole
	if roleLabel == "" && len(st.roles) > 0 {
		roleLabel = st.roles[0]
	}
	header := &screensv1.PageHeader{
		Eyebrow:     "People & Staff",
		BackLabel:   "Back to Users",
		BackHref:    "/admin-panel/users",
		Title:       orDash(st.name),
		Description: fmt.Sprintf("%s · %s · %s", orDash(roleLabel), orDash(st.email), fyLabel(fy)),
		Badges: []*screensv1.PageBadge{
			{Text: orDash(roleLabel), Tone: "info"},
			{Text: strings.ToUpper(st.status), Tone: "positive"},
		},
	}

	facts := []*screensv1.PageFact{
		{Label: "Email", Value: orDash(st.email)},
		{Label: "Phone", Value: orDash(st.phone)},
		{Label: "Roles", Value: orDash(strings.Join(st.roles, ", "))},
		{Label: "Primary District", Value: orDash(st.districtName), Href: hrefIf(st.districtID != "", "/districts/"+st.districtID)},
		{Label: "Department", Value: orDash(st.department)},
		{Label: "Country", Value: orDash(st.country)},
	}

	strip := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Staff Portfolio Summary (" + fyLabel(fy) + ")",
		Metrics: []*screensv1.PageMetric{
			{Label: "Assigned Schools", Value: intcomma(len(schools)), Note: fmt.Sprintf("%d Core · %d GPS", coreCount, gpsCount), Href: base + "?tab=schools&fy=" + fy},
			{Label: "Clusters Managed", Value: intcomma(len(clusters)), Href: base + "?tab=clusters&fy=" + fy},
			{Label: "FY Activities", Value: fmt.Sprintf("%d / %d", doneActs, len(acts)), Note: "completed / total", Href: base + "?tab=activities&fy=" + fy},
		},
	}}}

	schoolTable := func(list []staffSchool) *screensv1.PageBlock {
		rows := make([]*screensv1.PageRow, 0, len(list))
		for _, sc := range list {
			ref := sc.code
			if ref == "" {
				ref = sc.id
			}
			gps := "Missing"
			if sc.hasGPS {
				gps = "Recorded"
			}
			rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: orDash(sc.code)},
				{Text: sc.name, Href: "/schools/" + url.PathEscape(ref)},
				{Text: orDash(sc.district)},
				{Text: orDash(sc.schoolType)},
				{Text: gps},
				{Text: orDash(sc.ssaStatus)},
			}})
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Assigned Schools",
			Columns:      makeCols("School ID", "School Name", "District", "Type", "GPS", "SSA Status"),
			Rows:         rows,
			EmptyMessage: "No schools directly assigned to this staff member.",
		}}}
	}

	clusterTable := func(list []staffCluster) *screensv1.PageBlock {
		rows := make([]*screensv1.PageRow, 0, len(list))
		for _, c := range list {
			rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: c.name, Href: "/clusters/" + c.id},
				{Text: orDash(c.district)},
				{Text: intcomma(c.schoolCount)},
				{Text: strings.ToUpper(c.status)},
			}})
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Managed Clusters",
			Columns:      makeCols("Cluster", "District", "Schools", "Status"),
			Rows:         rows,
			EmptyMessage: "No clusters assigned to this staff member.",
		}}}
	}

	actTable := func(list []staffAct) *screensv1.PageBlock {
		rows := make([]*screensv1.PageRow, 0, len(list))
		for _, a := range list {
			dt := "—"
			if a.plannedDate != nil {
				dt = a.plannedDate.Format("02 Jan 2006")
			}
			scCell := &screensv1.PageCell{Text: "—"}
			if a.schoolName != "" {
				ref := a.schoolCode
				if ref == "" {
					ref = a.schoolName
				}
				scCell = &screensv1.PageCell{Text: a.schoolName, Href: "/schools/" + url.PathEscape(ref)}
			}
			rows = append(rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
				{Text: dt},
				{Text: a.title, Href: "/activities/" + a.id},
				{Text: a.actType},
				scCell,
				{Text: a.status},
			}})
		}
		return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{
			Title:        "Recent FY Activities",
			Columns:      makeCols("Date", "Activity", "Type", "School", "Status"),
			Rows:         rows,
			EmptyMessage: "No activities recorded in " + fyLabel(fy) + ".",
		}}}
	}

	blocks := []*screensv1.PageBlock{
		{Kind: &screensv1.PageBlock_Facts{Facts: &screensv1.PageFacts{Facts: facts}}},
		strip,
	}

	switch tab {
	case "overview":
		if len(clusters) > 0 {
			blocks = append(blocks, clusterTable(clusters[:min(6, len(clusters))]))
		}
		if len(schools) > 0 {
			blocks = append(blocks, schoolTable(schools[:min(8, len(schools))]))
		}
		if len(acts) > 0 {
			blocks = append(blocks, actTable(acts[:min(8, len(acts))]))
		}
	case "schools":
		blocks = append(blocks, schoolTable(schools))
	case "clusters":
		blocks = append(blocks, clusterTable(clusters))
	case "activities":
		blocks = append(blocks, actTable(acts))
	}

	return &screensv1.GetPageResponse{
		Header:  header,
		Tabs:    tabs,
		Blocks:  blocks,
		WebPath: base,
	}, true, nil
}

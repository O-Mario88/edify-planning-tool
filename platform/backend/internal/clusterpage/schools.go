package clusterpage

import (
	"context"
	"errors"
	"fmt"
	"net/url"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	registry "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// schoolsPath is the list a cluster card loads when it opens
// (cluster_views.cluster_schools_partial).
var schoolsPath = regexp.MustCompile(`^/partials/clusters/([a-z0-9][a-z0-9_-]{0,63})/schools$`)

// scopeGeography is _derive_from_schools' cluster_ids and district_ids: the
// clusters and districts of every school in the reader's scope, a lead's
// team included.
func scopeGeography(ctx context.Context, q schooldirectory.Querier, schoolIDs []string) (clusters, districts []string, err error) {
	if len(schoolIDs) == 0 {
		return nil, nil, nil
	}
	err = each(ctx, q, "the scope's geography", `
SELECT COALESCE(cluster_id, ''), COALESCE(district_id, '') FROM school WHERE id = ANY($1) AND deleted_at IS NULL`,
		func(rows pgx.Rows) error {
			var cluster, district string
			if err := rows.Scan(&cluster, &district); err != nil {
				return err
			}
			if cluster != "" && !in(clusters, cluster) {
				clusters = append(clusters, cluster)
			}
			if district != "" && !in(districts, district) {
				districts = append(districts, district)
			}
			return nil
		}, schoolIDs)
	return clusters, districts, err
}

// clusterRef is the cluster a list is asked for.
type clusterRef struct {
	id, name, owner, districtID, regionID string
}

// readable is scoping.cluster_in_scope(scope, cluster): a country reader's
// country, everything for a summary reader, and otherwise a cluster holding
// one of the scope's schools, one filed under the reader or their team, or
// an ownerless one in the scope's districts.
func readable(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope, c clusterRef) (bool, error) {
	switch {
	case s.CountryScope:
		if s.Country == "" {
			return true, nil
		}
		// The cluster's country, read through the registry
		// (docs/migration/80, §16).
		var ok bool
		err := q.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM (SELECT $2::varchar AS region_id, $3::varchar AS district_id) c WHERE `+registry.ClusterIn("c", "$1")+`)`,
			s.CountryIDs(), c.regionID, c.districtID).Scan(&ok)
		if err != nil {
			return false, fmt.Errorf("clusterpage: reading the cluster's country: %w", err)
		}
		return ok, nil
	case s.SummaryOnly:
		return true, nil
	}
	clusters, districts, err := scopeGeography(ctx, q, s.SchoolIDs)
	if err != nil {
		return false, err
	}
	if in(clusters, c.id) {
		return true, nil
	}
	if owner := strings.TrimSpace(c.owner); owner != "" {
		owners, err := teamOwnerIDs(ctx, q, s)
		if err != nil {
			return false, err
		}
		return in(owners, owner), nil
	}
	return c.districtID != "" && in(districts, c.districtID), nil
}

// teamOwnerIDs is cluster_owner_ids(scope) for reading: the reader's ids
// and their team's, each matched to the other id space.
func teamOwnerIDs(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope) ([]string, error) {
	ids := []string{}
	for _, id := range append([]string{s.UserID, s.StaffID}, s.SupervisedStaffIDs...) {
		if id != "" && !in(ids, id) {
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return nil, nil
	}
	asked := slices.Clone(ids)
	err := each(ctx, q, "the owner ids", `
SELECT id, COALESCE(user_id, '') FROM staff_profile
WHERE deleted_at IS NULL AND (id = ANY($1) OR user_id = ANY($1))`, func(rows pgx.Rows) error {
		var profileID, userID string
		if err := rows.Scan(&profileID, &userID); err != nil {
			return err
		}
		for _, id := range []string{profileID, userID} {
			if id != "" && !in(ids, id) {
				ids = append(ids, id)
			}
		}
		return nil
	}, asked)
	return ids, err
}

// listedSchool is one row of the list (services.cluster_schools).
type listedSchool struct {
	ID, Code, Name, Type, DistrictID, District string
	HasDistrict                                bool
	Shipping, Contact, Phone                   string
	OwnerID, OwnerRaw                          string
	Enrolment                                  int
	LastVisit, LastTraining                    *time.Time
	scores                                     []schooldirectory.SSAScore
	gate                                       visitgate.Gate
}

// supportRuleOn is support_responsibility.visibility_enabled(reader).
func supportRuleOn(p auth.Principal) bool {
	r := rules.SupportRule
	if r.Enabled || in(r.PilotRoles, p.ActiveRole) {
		return true
	}
	email := strings.ToLower(p.Email)
	return email != "" && in(r.PilotUsers, email)
}

// schools answers a cluster card's schools for p.
func (s *Service) schools(ctx context.Context, p auth.Principal, clusterID string, query url.Values) (*screensv1.GetPageResponse, error) {
	doors, ok := rules.Doors[p.ActiveRole]
	if !ok || !doors.SchoolsList {
		return nil, pagegate.ErrNotAvailable
	}
	now := s.now()
	scope, err := schooldirectory.ResolveScope(ctx, s.db, p, now)
	if err != nil {
		return nil, err
	}
	var c clusterRef
	err = s.db.QueryRow(ctx, `
SELECT id, COALESCE(name, ''), COALESCE(responsible_staff_id, ''), COALESCE(district_id, ''), COALESCE(region_id, '')
FROM cluster WHERE id = $1 AND deleted_at IS NULL`, clusterID).Scan(&c.id, &c.name, &c.owner, &c.districtID, &c.regionID)
	if errors.Is(err, pgx.ErrNoRows) {
		return nil, pagegate.ErrNotAvailable
	}
	if err != nil {
		return nil, fmt.Errorf("clusterpage: reading the cluster: %w", err)
	}
	if ok, err := readable(ctx, s.db, scope, c); err != nil {
		return nil, err
	} else if !ok {
		return nil, pagegate.ErrNotAvailable
	}

	list, err := s.listSchools(ctx, c.id)
	if err != nil {
		return nil, err
	}
	operational := schooldirectory.OperationalFY(now)
	opYear, _ := strconv.Atoi(operational)
	fy := strings.TrimSpace(query.Get("fy"))
	if fy == "" {
		fy = operational
	}
	horizon, err := schoolplanning.Horizon(ctx, s.db, p.Country, fy, opYear, schooldirectory.FYOptions(now), now)
	if err != nil {
		return nil, err
	}
	ids := make([]string, len(list))
	for i, sc := range list {
		ids[i] = sc.ID
	}
	badges, counted, err := schoolplanning.ForSchools(ctx, s.db, ids, horizon)
	if err != nil {
		return nil, err
	}
	support := supportRuleOn(p)
	partner := map[string]bool{}
	next := map[string]schoolplanning.Next{}
	if support {
		if partner, err = schoolplanning.PartnerSupported(ctx, s.db, ids, operational); err != nil {
			return nil, err
		}
		if next, err = schoolplanning.NextActivities(ctx, s.db, counted, now); err != nil {
			return nil, err
		}
	}
	gates := schoolprofile.GateRules()
	for i := range list {
		sc := &list[i]
		school := visitgate.School{ID: sc.ID, Code: sc.Code, Name: sc.Name, Type: sc.Type}
		if sc.gate, err = visitgate.Of(ctx, s.db, gates, school, operational, operational); err != nil {
			return nil, err
		}
	}
	return schoolsPage(c, list, badges, partner, next, support, doors, gates), nil
}

// listSchools is cluster_schools' roster: the cluster's operating schools
// by name, Champion schools left out, each with its latest confirmed
// assessment's scores and its last completed visit and training.
func (s *Service) listSchools(ctx context.Context, clusterID string) ([]listedSchool, error) {
	out := []listedSchool{}
	at := map[string]int{}
	err := each(ctx, s.db, "the cluster's schools", `
SELECT s.id, COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''),
  s.district_id IS NOT NULL, COALESCE(s.district_id, ''), COALESCE(d.name, ''),
  COALESCE(s.shipping_address, ''), COALESCE(s.primary_contact_name, ''),
  COALESCE(NULLIF(s.primary_contact_phone, ''), NULLIF(s.school_phone, ''), ''),
  COALESCE(s.account_owner_id, ''), COALESCE(s.account_owner_name_raw, ''), COALESCE(s.enrollment, 0)
FROM school s LEFT JOIN district d ON d.id = s.district_id
WHERE s.cluster_id = $1 AND s.deleted_at IS NULL AND s.operational_status = ANY($2)
  AND NOT (s.school_type = ANY($3) AND s.school_type IS NOT NULL)
ORDER BY s.name`, func(rows pgx.Rows) error {
		var r listedSchool
		if err := rows.Scan(&r.ID, &r.Code, &r.Name, &r.Type, &r.HasDistrict, &r.DistrictID, &r.District, &r.Shipping, &r.Contact,
			&r.Phone, &r.OwnerID, &r.OwnerRaw, &r.Enrolment); err != nil {
			return err
		}
		at[r.ID] = len(out)
		out = append(out, r)
		return nil
	}, clusterID, rules.OperatingStatuses, rules.OwnTableSchoolTypes)
	if err != nil || len(out) == 0 {
		return out, err
	}
	ids := make([]string, len(out))
	for i, r := range out {
		ids[i] = r.ID
	}
	latest := map[string]string{}
	records := []string{}
	if err := each(ctx, s.db, "the schools' latest assessments", `
SELECT DISTINCT ON (school_id) school_id, id FROM ssa_record
WHERE school_id = ANY($1) AND deleted_at IS NULL AND verification_status = 'confirmed'
ORDER BY school_id, date_of_ssa DESC, created_at DESC`, func(rows pgx.Rows) error {
		var school, record string
		if err := rows.Scan(&school, &record); err != nil {
			return err
		}
		latest[record] = school
		records = append(records, record)
		return nil
	}, ids); err != nil {
		return nil, err
	}
	if len(records) > 0 {
		if err := each(ctx, s.db, "the schools' scores", `
SELECT ssa_record_id, intervention, score::float8 FROM ssa_score WHERE ssa_record_id = ANY($1)`, func(rows pgx.Rows) error {
			var record, intervention string
			var score *float64
			if err := rows.Scan(&record, &intervention, &score); err != nil {
				return err
			}
			i := at[latest[record]]
			out[i].scores = append(out[i].scores, schooldirectory.SSAScore{Intervention: intervention, Score: score})
			return nil
		}, records); err != nil {
			return nil, err
		}
	}
	err = each(ctx, s.db, "the schools' last visit and training", `
SELECT school_id, MAX(planned_date) FILTER (WHERE activity_type = ANY($3)), MAX(planned_date) FILTER (WHERE activity_type = ANY($4))
FROM activity WHERE school_id = ANY($1) AND deleted_at IS NULL AND status = ANY($2) AND planned_date IS NOT NULL
GROUP BY school_id`, func(rows pgx.Rows) error {
		var school string
		var visit, training *time.Time
		if err := rows.Scan(&school, &visit, &training); err != nil {
			return err
		}
		out[at[school]].LastVisit, out[at[school]].LastTraining = visit, training
		return nil
	}, ids, rules.CompletedWorkStatuses, rules.VisitTypes, rules.TrainingTypes)
	return out, err
}

// ── The blocks ───────────────────────────────────────────────────────────

// joinedChips is a badge cell's text: the chips sit side by side with
// nothing between them, and the feed reads a cell's text as written.
func joinedChips(chips ...[]schoolplanning.Chip) string {
	parts := []string{}
	for _, list := range chips {
		for _, c := range list {
			parts = append(parts, c.Label)
		}
	}
	return collapse(strings.Join(parts, ""))
}

// factTone is the feed's colour for a fact whose holder carries words
// (records.FACT_TONES).
func factTone(classes string) string {
	for _, pair := range [][2]string{{"danger", "alert"}, {"critical", "alert"}, {"warning", "caution"},
		{"needs_attention", "caution"}, {"success", "good"}, {"healthy", "good"}} {
		if strings.Contains(classes, pair[0]) {
			return pair[1]
		}
	}
	return ""
}

func dash(value string) string { return orDefault(value, "—") }

// schoolsPage is partials/clusters/cluster_schools_table.html as the feed
// reads it.
func schoolsPage(c clusterRef, list []listedSchool, badges map[string]*schoolplanning.Badges, partner map[string]bool,
	next map[string]schoolplanning.Next, support bool, d Doors, gates visitgate.Rules) *screensv1.GetPageResponse {
	head := &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
		{Kind: &screensv1.PagePanelItem_Heading{Heading: fmt.Sprintf("Schools in Cluster (%d)", len(list))}},
		textItem("Click a school to see its SSA intervention scores."),
	}}}}
	page := &screensv1.GetPageResponse{Header: &screensv1.PageHeader{}, WebPath: "/partials/clusters/" + c.id + "/schools"}
	if len(list) == 0 {
		page.Blocks = []*screensv1.PageBlock{head, {Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			textItem("This cluster has no schools yet."),
			{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
				{Text: "Add Schools to Cluster", Href: "/clusters/" + c.id + "/bulk-assign-drawer", Drawer: true},
			}}}},
		}}}}}
		return page
	}
	anyAssign := false
	for _, sc := range list {
		anyAssign = anyAssign || sc.gate.CanAssignPartner
	}
	tick := d.BulkSchedule || (d.AssignPartner && anyAssign)
	columns := []string{"ID", "School Name", "Visit Plan Status", "Training Plan Status", "Visit Lock"}
	if support {
		columns = append(columns, "Responsible")
	}
	columns = append(columns, "Actions")
	table := &screensv1.PageTable{}
	for _, label := range columns {
		table.Columns = append(table.Columns, &screensv1.PageColumn{Label: label})
	}
	for _, sc := range list {
		table.Rows = append(table.Rows, schoolRow(c, sc, badges[sc.ID], partner[sc.ID], next, support, d, gates, tick))
	}
	page.Blocks = []*screensv1.PageBlock{head, {Kind: &screensv1.PageBlock_Table{Table: table}}}
	if tick {
		actions := []*screensv1.PageSelectionAction{}
		if d.AssignPartner {
			actions = append(actions, &screensv1.PageSelectionAction{Label: "Assign to partner", Href: "/planning/bulk-assign-partner-drawer", Param: "school_ids"})
		}
		if d.BulkSchedule {
			actions = append(actions, &screensv1.PageSelectionAction{Label: "Schedule visit", Href: "/planning/bulk-schedule-drawer", Param: "school_ids"})
		}
		if len(actions) > 0 {
			page.Selection = &screensv1.PageSelection{Noun: "selected", Actions: actions}
		}
	}
	return page
}

// schoolRow is one school's row, its menu and what opening it shows. Only
// the menu items the feed can open are named: a greyed Schedule or Assign
// has no address, and Remove posts.
func schoolRow(c clusterRef, sc listedSchool, b *schoolplanning.Badges, isPartner bool, next map[string]schoolplanning.Next,
	support bool, d Doors, gates visitgate.Rules, tick bool) *screensv1.PageRow {
	if b == nil {
		b = &schoolplanning.Badges{}
	}
	nameCell := &screensv1.PageCell{Text: collapse(sc.Name)}
	if d.OpenSchool && sc.Name != "" && strings.TrimSpace(sc.ID) != "" {
		nameCell.Href = "/schools/" + sc.ID
	}
	lock := sc.gate.LockStateLabel(gates)
	if lock == "" {
		lock = "—"
	}
	cells := []*screensv1.PageCell{
		{Text: collapse(sc.Code)},
		nameCell,
		{Text: joinedChips(b.VisitChips()), Pills: ChipPills(b.VisitChips())},
		{Text: joinedChips(b.TrainingChips(), b.ClusterMeetingChips()), Pills: ChipPills(b.TrainingChips(), b.ClusterMeetingChips())},
		{Text: lock, Pills: LockPills(sc.gate, gates)},
	}
	if support {
		who := "Staff"
		if isPartner {
			who = "Partner"
		}
		cells = append(cells, &screensv1.PageCell{Text: who})
	}
	menu := func(label, href string) *screensv1.PageAction {
		return &screensv1.PageAction{Key: "menu", Label: label, Enabled: true, Href: href, Drawer: true}
	}
	actions := []*screensv1.PageAction{}
	if d.Schedule {
		actions = append(actions, menu("Schedule", "/planning/schedule-modal?school_id="+sc.Code))
	}
	if d.AssignPartner && sc.gate.CanAssignPartner {
		actions = append(actions, menu("Assign", "/planning/assign-partner-modal?school_id="+sc.Code))
	}
	if d.BulkSchedule && support && isPartner {
		actions = append(actions,
			menu("Add to Meeting", "/planning/schedule-modal?cluster_id="+c.id+"&action=meeting&school_id="+sc.Code),
			menu("Add to Training", "/planning/schedule-modal?cluster_id="+c.id+"&action=training&school_id="+sc.Code))
	}
	cells = append(cells, &screensv1.PageCell{Actions: actions})

	row := &screensv1.PageRow{Cells: cells}
	if tick && (d.BulkSchedule || sc.gate.CanAssignPartner) {
		row.PickId = sc.Code
	}
	row.Details = schoolFacts(c, sc, next, support)
	if d.OpenSchool {
		row.DetailsHref = "/schools/" + sc.ID
	}
	row.DetailBlocks = []*screensv1.PageBlock{schoolScores(sc.scores)}
	return row
}

// schoolFacts is the opened row's "Label: value" list.
func schoolFacts(c clusterRef, sc listedSchool, next map[string]schoolplanning.Next, support bool) []*screensv1.PageFact {
	staff := "Unassigned"
	if sc.OwnerID != "" {
		staff = orDefault(sc.OwnerRaw, sc.OwnerID)
	}
	average, tone := schooldirectory.SSAAverage(sc.scores)
	ssa := "Not assessed"
	if average != nil {
		ssa = scoreText(*average) + "/10"
	}
	ssaTone := ""
	if tone != "" {
		ssaTone = factTone("is-" + tone)
	}
	district := "—"
	if sc.HasDistrict {
		district = dash(sc.District)
	}
	fact := func(label, value, href, tone string) *screensv1.PageFact {
		return &screensv1.PageFact{Label: label, Value: collapse(value), Href: href, Tone: tone}
	}
	day := func(at *time.Time) (string, string) {
		if at == nil {
			return "Never", "alert"
		}
		return at.Format("2006-01-02"), ""
	}
	visit, visitTone := day(sc.LastVisit)
	training, trainingTone := day(sc.LastTraining)
	districtHref := ""
	if sc.HasDistrict && sc.DistrictID != "" && district != "—" {
		districtHref = "/districts/" + sc.DistrictID
	}
	clusterHref := ""
	if c.id != "" && c.name != "" {
		clusterHref = "/clusters/" + c.id
	}
	staffHref := ""
	if sc.OwnerID != "" {
		staffHref = "/staff/" + sc.OwnerID
	}
	facts := []*screensv1.PageFact{
		fact("District", district, districtHref, ""),
		fact("Shipping Address", dash(sc.Shipping), "", ""),
		fact("School Type", schoolprofile.SchoolTypeLabel(sc.Type), "", ""),
		fact("Cluster", c.name, clusterHref, ""),
		fact("Enrollment", strconv.Itoa(sc.Enrolment), "", ""),
		fact("Primary Contact", dash(sc.Contact), "", ""),
		fact("Phone", dash(sc.Phone), "", ""),
		fact("Staff Name", staff, staffHref, ""),
		fact("SSA", ssa, "", ssaTone),
		fact("Last Visit", visit, "", visitTone),
		fact("Last Training", training, "", trainingTone),
	}
	if support {
		value := "—"
		if n, ok := next[sc.ID]; ok {
			value = fmt.Sprintf("%s · %d %s", n.Label, n.Day.Day(), n.Day.Format("Jan"))
		}
		facts = append(facts, fact("Next Activity", value, "", ""))
	}
	return facts
}

// schoolScores is partials/schools/ssa_score_groups.html for one school's
// latest confirmed assessment (no year named).
func schoolScores(scores []schooldirectory.SSAScore) *screensv1.PageBlock {
	items := []*screensv1.PagePanelItem{textItem("Latest confirmed assessment")}
	groups, has := schooldirectory.SSAGroups(scores)
	if !has {
		items = append(items, textItem("No confirmed SSA scores are available yet."))
	} else {
		items = append(items, groupItems(groups)...)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{
		Title: "Intervention scores", Subtitle: "SSA detail", Items: items,
	}}}
}

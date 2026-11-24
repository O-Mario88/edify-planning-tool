package programmerollout

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The schools behind a Programme Rollout figure (programme_rollout_views.
// school_list_drawer, programme_rollout_service.school_list): read-only, an
// officer's, a cluster's or the team's schools in one SSA state, or not yet
// trained this year. The feed never served it, so the figures were dead ends
// on the web with or without Django.

// DrawerPath is the drawer's address.
const DrawerPath = "/programme-rollout/schools"

// listKinds are LIST_KINDS, in their order.
var listKinds = [][2]string{
	{"ssa_confirmed", "Confirmed SSA this FY"},
	{"ssa_awaiting", "Collected, awaiting IA verification"},
	{"ssa_scheduled", "Collection scheduled or with a partner"},
	{"ssa_not_planned", "No SSA collection planned"},
	{"not_trained", "Not yet trained this FY"},
}

// drawerRows is DRAWER_ROWS.
const drawerRows = 200

func rolloutDay(d *time.Time) string {
	if d == nil {
		return ""
	}
	return d.Format("2 Jan 2006")
}

func statusWords(status string) string {
	if label, ok := rules.StatusLabels[status]; ok {
		return strings.ToLower(label)
	}
	return strings.ToLower(status)
}

// collectionFact is a planned or scheduled collection's line.
func collectionFact(status string, planned *time.Time, partner string) string {
	out := "Collection " + statusWords(status)
	if when := rolloutDay(planned); when != "" {
		out += " " + when
	}
	if partner != "" {
		out += " with " + partner
	}
	return out
}

// heldFact is a collection already held's line.
func heldFact(status string, planned *time.Time) string {
	out := "Collection held"
	if when := rolloutDay(planned); when != "" {
		out += " " + when
	}
	return out + ", " + statusWords(status)
}

type schoolState struct{ state, detail string }

// stateOf is a school's state and the first fact behind it.
func stateOf(confirmed bool, day *time.Time, awaiting, scheduled []string) schoolState {
	switch {
	case confirmed:
		return schoolState{stateConfirmed, strings.TrimSpace("Confirmed " + rolloutDay(day))}
	case len(awaiting) > 0:
		return schoolState{stateAwaiting, awaiting[0]}
	case len(scheduled) > 0:
		return schoolState{stateScheduled, scheduled[0]}
	}
	return schoolState{stateNotPlanned, "No SSA collection planned this FY"}
}

func countLine(total, shown int) string {
	plural := "s"
	if total == 1 {
		plural = ""
	}
	out := fmt.Sprintf("%d school%s", total, plural)
	if total > shown {
		out += fmt.Sprintf(", the first %d shown", shown)
	}
	return out
}

// ssaDetails is ssa_states with the fact behind each state, in its order:
// records newest first, collections by planned day, then hand-overs.
func (s *Service) ssaDetails(ctx context.Context, sc *scope, fy string) (map[string]schoolState, error) {
	out := map[string]schoolState{}
	if len(sc.schools) == 0 {
		return out, nil
	}
	portfolio := sc.schoolIDs()
	confirmed, confirmedOn := map[string]bool{}, map[string]*time.Time{}
	awaiting, scheduled := map[string][]string{}, map[string][]string{}
	rows, err := s.db.Query(ctx, `SELECT school_id, COALESCE(verification_status, ''), date_of_ssa FROM ssa_record
WHERE school_id = ANY($1) AND fy = $2 AND deleted_at IS NULL ORDER BY school_id, date_of_ssa DESC NULLS LAST`, portfolio, fy)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the year's SSA records: %w", err)
	}
	for rows.Next() {
		var school, status string
		var taken *time.Time
		if err := rows.Scan(&school, &status, &taken); err != nil {
			rows.Close()
			return nil, err
		}
		switch {
		case status == rules.SSA.ConfirmedStatus:
			if !confirmed[school] {
				confirmed[school], confirmedOn[school] = true, taken
			}
		case slices.Contains(rules.SSA.AwaitingRecordStatuses, status):
			awaiting[school] = append(awaiting[school], "Uploaded "+rolloutDay(taken)+", not yet verified")
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	clusters := sc.clusterIDs()
	members := sc.membersOfCluster()
	where, args := sc.activityFilter([]any{fy, rules.SSA.CollectionTypes, rules.NotPlannedStatuses, clusters})
	type collection struct {
		id, school, cluster, status, delivery, partner string
		planned                                        *time.Time
		attended                                       []string
	}
	collections := []collection{}
	rows, err = s.db.Query(ctx, `SELECT a.id, COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.status, ''),
  COALESCE(a.delivery_type, ''), COALESCE(a.assigned_partner_id, ''), a.planned_date, COALESCE(a.attended_school_ids, '{}')
FROM activity a
WHERE (`+where+` OR (a.school_id IS NULL AND a.cluster_id = ANY($4))) AND a.fy = $1 AND a.deleted_at IS NULL
  AND a.activity_type = ANY($2) AND NOT COALESCE(a.status = ANY($3), FALSE)
ORDER BY a.planned_date NULLS LAST, a.id`, args...)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the SSA collections: %w", err)
	}
	sessions, partnerIDs := []string{}, []string{}
	for rows.Next() {
		var c collection
		if err := rows.Scan(&c.id, &c.school, &c.cluster, &c.status, &c.delivery, &c.partner, &c.planned, &c.attended); err != nil {
			rows.Close()
			return nil, err
		}
		collections = append(collections, c)
		if c.school == "" {
			sessions = append(sessions, c.id)
		}
		partnerIDs = append(partnerIDs, c.partner)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	invited := map[string][]string{}
	if len(sessions) > 0 {
		rows, err = s.db.Query(ctx, `SELECT activity_id, school_id FROM cluster_activity_attendance WHERE activity_id = ANY($1)`, sessions)
		if err != nil {
			return nil, fmt.Errorf("programmerollout: reading the collections' schools: %w", err)
		}
		for rows.Next() {
			var id, school string
			if err := rows.Scan(&id, &school); err != nil {
				rows.Close()
				return nil, err
			}
			invited[id] = append(invited[id], school)
		}
		rows.Close()
	}
	start, _ := strconv.Atoi(fy)
	from := time.Date(start-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	type handOver struct{ school, cluster, partner string }
	handOvers := []handOver{}
	rows, err = s.db.Query(ctx, `SELECT COALESCE(pa.school_id, ''), COALESCE(pa.cluster_id, ''), COALESCE(pa.partner_id, '') FROM partner_assignment pa
LEFT JOIN activity_catalogue_item ci ON ci.id = pa.catalogue_item_id
WHERE (pa.school_id = ANY($1) OR (pa.school_id IS NULL AND pa.cluster_id = ANY($2))) AND pa.status = ANY($3)
  AND pa.created_at >= $4 AND pa.created_at < $5 AND (pa.expected_activity_type = ANY($6) OR ci.workflow_kind = ANY($6))
ORDER BY pa.created_at, pa.id`,
		portfolio, clusters, rules.SSA.UnscheduledAssignmentStatuses, from, from.AddDate(1, 0, 0), rules.SSA.CollectionTypes)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the partner hand-overs: %w", err)
	}
	for rows.Next() {
		var h handOver
		if err := rows.Scan(&h.school, &h.cluster, &h.partner); err != nil {
			rows.Close()
			return nil, err
		}
		handOvers = append(handOvers, h)
		partnerIDs = append(partnerIDs, h.partner)
	}
	rows.Close()
	names, err := s.partnerNames(ctx, partnerIDs)
	if err != nil {
		return nil, err
	}
	named := func(id string) string {
		if n, ok := names[id]; ok {
			return n
		}
		return "a partner"
	}
	inPortfolio := func(ids []string) []string {
		seen, out := map[string]bool{}, []string{}
		for _, id := range ids {
			if _, ok := sc.schools[id]; ok && !seen[id] {
				seen[id] = true
				out = append(out, id)
			}
		}
		return out
	}
	for _, c := range collections {
		schools := []string{c.school}
		if c.school == "" {
			schools = append(append([]string{}, invited[c.id]...), c.attended...)
			if len(schools) == 0 {
				schools = members[c.cluster]
			}
		}
		partner := ""
		if c.delivery == "partner" {
			partner = named(c.partner)
		}
		for _, id := range inPortfolio(schools) {
			if slices.Contains(rules.LiveStatuses, c.status) {
				scheduled[id] = append(scheduled[id], collectionFact(c.status, c.planned, partner))
			} else {
				awaiting[id] = append(awaiting[id], heldFact(c.status, c.planned))
			}
		}
	}
	for _, h := range handOvers {
		schools := []string{h.school}
		if h.school == "" {
			schools = members[h.cluster]
		}
		for _, id := range inPortfolio(schools) {
			scheduled[id] = append(scheduled[id], "Handed to "+named(h.partner)+", not yet scheduled")
		}
	}
	for _, id := range portfolio {
		out[id] = stateOf(confirmed[id], confirmedOn[id], awaiting[id], scheduled[id])
	}
	return out, nil
}

// partnerNames is _partner_names (Partner.all_objects: deleted ones too).
func (s *Service) partnerNames(ctx context.Context, ids []string) (map[string]string, error) {
	out := map[string]string{}
	wanted := []string{}
	for _, id := range ids {
		if id != "" {
			wanted = append(wanted, id)
		}
	}
	if len(wanted) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(name, '') FROM partner WHERE id = ANY($1)`, wanted)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the partners' names: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, err
		}
		out[id] = name
	}
	return out, rows.Err()
}

func (sc *scope) memberName(m *member) string {
	if !m.isLead {
		return m.name
	}
	if sc.support {
		return m.name + " (own portfolio)"
	}
	return "Your own portfolio"
}

func refusalDrawer(reason string) *screensv1.PageDrawer {
	return &screensv1.PageDrawer{Title: "Schools", Subtitle: "Programme Rollout", CancelLabel: "Close",
		Items: []*screensv1.DrawerItem{{Kind: &screensv1.DrawerItem_Note{Note: &screensv1.DrawerNote{Text: reason, Tone: "warning"}}}}}
}

// Drawer is school_list_drawer for p: the drawer, and whether Go serves it.
func (s *Service) Drawer(ctx context.Context, p auth.Principal, query url.Values) (*screensv1.PageDrawer, bool, error) {
	if !slices.Contains(rules.PageRoles, p.ActiveRole) || p.InActingAppointment {
		return nil, false, nil
	}
	chooser := slices.Contains(rules.LeadChoosers, p.ActiveRole)
	lead := leadChoice{staffID: p.StaffProfileID, userID: p.UserID}
	switch {
	case chooser:
		var found bool
		var err error
		if lead, _, found, err = s.chooseLead(ctx, strings.TrimSpace(query.Get("lead"))); err != nil || !found {
			return nil, err != nil, err
		}
	case p.ActiveRole != rules.ProgramLead || p.StaffProfileID == "":
		return nil, false, nil
	}
	kind := strings.TrimSpace(query.Get("kind"))
	title := ""
	for _, k := range listKinds {
		if k[0] == kind {
			title = k[1]
		}
	}
	if title == "" {
		return refusalDrawer("Choose which schools to list."), true, nil
	}
	now := s.now()
	fy := strings.TrimSpace(query.Get("fy"))
	if !slices.Contains(schooldirectory.FYOptions(now), fy) {
		fy = schooldirectory.OperationalFY(now)
	}
	sc, err := readScope(ctx, s.db, lead.staffID, lead.userID, now)
	if err != nil {
		return nil, true, err
	}
	if chooser {
		sc.support = true
		if sc.lead != nil {
			sc.lead.support = true
		}
	}
	clusterNames, err := s.clusterNames(ctx, sc.clusterIDs())
	if err != nil {
		return nil, true, err
	}
	var chosen map[string]bool
	whose := "Your portfolio"
	if len(sc.officers) > 0 {
		whose = "The whole team"
	}
	member, cluster := strings.TrimSpace(query.Get("member")), strings.TrimSpace(query.Get("cluster"))
	switch {
	case member != "":
		m := sc.member(member)
		if m == nil {
			return refusalDrawer("That officer is not on this team."), true, nil
		}
		chosen, whose = m.schools, sc.memberName(m)
	case cluster != "":
		if cluster != noCluster && !slices.Contains(sc.clusterIDs(), cluster) {
			return refusalDrawer("That cluster holds none of this team's schools."), true, nil
		}
		chosen = map[string]bool{}
		for id, school := range sc.schools {
			key := school.cluster
			if key == "" {
				key = noCluster
			}
			if key == cluster {
				chosen[id] = true
			}
		}
		whose = "Schools not in a cluster"
		if cluster != noCluster {
			whose = clusterNames[cluster]
			if whose == "" {
				whose = "Cluster"
			}
		}
	default:
		chosen = map[string]bool{}
		for id := range sc.schools {
			chosen[id] = true
		}
	}
	details := map[string]string{}
	if kind == "not_trained" {
		trained := map[string]bool{}
		if len(chosen) > 0 {
			if trained, err = sc.trainedSchools(ctx, s.db, fy); err != nil {
				return nil, true, err
			}
		}
		for id := range chosen {
			if !trained[id] {
				details[id] = "No verified training this FY"
			}
		}
	} else {
		states, err := s.ssaDetails(ctx, sc, fy)
		if err != nil {
			return nil, true, err
		}
		wanted := strings.TrimPrefix(kind, "ssa_")
		for id := range chosen {
			if st, ok := states[id]; ok && st.state == wanted {
				details[id] = st.detail
			}
		}
	}
	return s.drawerFor(sc, title, whose, fy, details, clusterNames), true, nil
}

func (s *Service) drawerFor(sc *scope, title, whose, fy string, details, clusterNames map[string]string) *screensv1.PageDrawer {
	ids := []string{}
	for id := range details {
		if _, ok := sc.schools[id]; ok {
			ids = append(ids, id)
		}
	}
	sort.Slice(ids, func(i, j int) bool {
		a, b := sc.schools[ids[i]], sc.schools[ids[j]]
		if a.name != b.name {
			return a.name < b.name
		}
		return ids[i] < ids[j]
	})
	total := len(ids)
	if len(ids) > drawerRows {
		ids = ids[:drawerRows]
	}
	dash := func(v string) string {
		if v == "" {
			return "—"
		}
		return v
	}
	table := &screensv1.PageTable{
		Columns:      []*screensv1.PageColumn{{Label: "School ID"}, {Label: "School"}, {Label: "Officer"}, {Label: "District · cluster"}, {Label: "Where it stands"}},
		EmptyMessage: "No school is in this state.",
	}
	for _, id := range ids {
		school := sc.schools[id]
		officers := []string{}
		for _, o := range sc.ownersBySchool[id] {
			if m := sc.member(o); m != nil {
				officers = append(officers, sc.memberName(m))
			}
		}
		place := dash(school.district)
		if name := clusterNames[school.cluster]; name != "" {
			place += " · " + name
		}
		table.Rows = append(table.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: dash(school.code)}, {Text: school.name, Href: "/schools/" + id}, {Text: dash(strings.Join(officers, ", "))},
			{Text: place}, {Text: details[id]},
		}})
	}
	return &screensv1.PageDrawer{Title: title, Subtitle: whose + " · FY " + fy, CancelLabel: "Close", Items: []*screensv1.DrawerItem{
		{Kind: &screensv1.DrawerItem_Text{Text: countLine(total, len(ids))}},
		{Kind: &screensv1.DrawerItem_Block{Block: &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: table}}}},
	}}
}

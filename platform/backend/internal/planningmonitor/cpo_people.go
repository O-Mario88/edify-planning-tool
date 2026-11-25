package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The people plan's own rows (people.py).
const (
	cpoOtherTeam      = "__other__"
	cpoOtherTeamLabel = "Other staff"
	cpoUnrecorded     = "__unrecorded__"
	cpoUnrecordedName = "No responsible person recorded"
)

// cpoNarrow is people.Narrow: the page's filters as the people-first read
// applies them.
type cpoNarrow struct {
	region, district, schoolType, clusterStatus, channel, partner string
	schoolIDs                                                     []string // nil for every school kept
}

// cpoPerson is people.PersonPlan: one person's own year.
type cpoPerson struct {
	key, name, role, teamKey, teamName string
	schools                            map[string]int
	visits                             map[string]int
	visitsByType                       map[string]int
	outreach, trainings                int
	clusterTrainings, meetings         int
	partnerSchools                     map[string]bool
	partnerAssigned, partnerPlanned    int
	byPartner                          map[string]*cpoHand
	partnerOrder                       []string
}

type cpoHand struct {
	assigned, planned int
	schools           map[string]bool
}

func newPerson(key, name, role, team, teamName string) *cpoPerson {
	return &cpoPerson{key: key, name: name, role: role, teamKey: team, teamName: teamName, schools: map[string]int{},
		visits: map[string]int{}, visitsByType: map[string]int{}, partnerSchools: map[string]bool{}, byPartner: map[string]*cpoHand{}}
}

// hand is PersonPlan.hand: one piece of work put in a Partner's hands.
func (p *cpoPerson) hand(partner, school string, planned int) {
	p.partnerAssigned++
	p.partnerPlanned += planned
	p.partnerSchools[school] = true
	h, ok := p.byPartner[partner]
	if !ok {
		h = &cpoHand{schools: map[string]bool{}}
		p.byPartner[partner] = h
		p.partnerOrder = append(p.partnerOrder, partner)
	}
	h.assigned++
	h.planned += planned
	h.schools[school] = true
}

func (p *cpoPerson) visitsPlanned() int {
	n := 0
	for _, v := range p.visits {
		n += v
	}
	return n
}

func (p *cpoPerson) schoolCount() int {
	n := 0
	for _, v := range p.schools {
		n += v
	}
	return n
}

func (p *cpoPerson) hasAnything() bool {
	return p.schoolCount() > 0 || p.visitsPlanned() > 0 || p.outreach > 0 || p.trainings > 0 || p.clusterTrainings > 0 ||
		p.meetings > 0 || p.partnerAssigned > 0
}

// cpoTeam is people.TeamPlan.
type cpoTeam struct {
	key, name string
	people    []*cpoPerson
}

// cpoPeople is people._People: the roster, and a row for anyone else the
// year's records name.
type cpoPeople struct {
	teams     map[string]*cpoTeam
	teamOrder []string
	byID      map[string]*cpoPerson
	pending   map[string]bool
}

func (pp *cpoPeople) note(ids ...string) {
	for _, id := range ids {
		if id != "" && pp.byID[id] == nil {
			pp.pending[id] = true
		}
	}
}

func (pp *cpoPeople) otherTeam() *cpoTeam {
	t, ok := pp.teams[cpoOtherTeam]
	if !ok {
		t = &cpoTeam{key: cpoOtherTeam, name: cpoOtherTeamLabel}
		pp.teams[cpoOtherTeam] = t
		pp.teamOrder = append(pp.teamOrder, cpoOtherTeam)
	}
	return t
}

// resolve is _People.resolve over _other_people: ids the roster does not
// name, in either id space (soft-deleted People records included).
func (pp *cpoPeople) resolve(ctx context.Context, db schooldirectory.Querier) error {
	ids := make([]string, 0, len(pp.pending))
	for id := range pp.pending {
		ids = append(ids, id)
	}
	pp.pending = map[string]bool{}
	if len(ids) == 0 {
		return nil
	}
	rows, err := db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, ''), COALESCE(NULLIF(u.name, ''), NULLIF(u.email, ''), sp.id)
FROM staff_profile sp LEFT JOIN "user" u ON u.id = sp.user_id WHERE sp.id = ANY($1) OR sp.user_id = ANY($1)`, ids)
	if err != nil {
		return fmt.Errorf("planningmonitor: the other people: %w", err)
	}
	type entry struct{ profile, name string }
	found := map[string]entry{}
	order := []string{}
	for rows.Next() {
		var profile, user, name string
		if err := rows.Scan(&profile, &user, &name); err != nil {
			rows.Close()
			return err
		}
		for _, k := range []string{profile, user} {
			if k != "" {
				if _, seen := found[k]; !seen {
					order = append(order, k)
				}
				found[k] = entry{profile, name}
			}
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	for _, raw := range order {
		e := found[raw]
		if pp.byID[raw] != nil {
			continue
		}
		row := pp.byID[e.profile]
		if row == nil {
			row = newPerson(e.profile, e.name, "", cpoOtherTeam, cpoOtherTeamLabel)
			pp.otherTeam().people = append(pp.otherTeam().people, row)
			pp.byID[e.profile] = row
		}
		pp.byID[raw] = row
	}
	return nil
}

// get is _People.get: the person a raw id names, else the fallback row.
func (pp *cpoPeople) get(raw, fallback string) *cpoPerson {
	if row := pp.byID[raw]; row != nil && raw != "" {
		return row
	}
	if row := pp.byID[fallback]; row != nil {
		return row
	}
	name := cpoUnrecordedName
	if fallback == rules.CountryOversight.NoOwner[0] {
		name = rules.CountryOversight.NoOwner[1]
	}
	row := newPerson(fallback, name, "", cpoOtherTeam, cpoOtherTeamLabel)
	pp.byID[fallback] = row
	pp.otherTeam().people = append(pp.otherTeam().people, row)
	return row
}

// first is _People.first: the first raw id the people know.
func (pp *cpoPeople) first(raws ...string) *cpoPerson {
	for _, raw := range raws {
		if row := pp.byID[raw]; row != nil && raw != "" {
			return row
		}
	}
	return nil
}

// visitKindCase is rules.visit_kind_case over the activity alias a.
func (b *sql) visitKindCase() string {
	var w strings.Builder
	w.WriteString("CASE")
	purposes := make([]string, 0, len(rules.PurposeKinds))
	for p := range rules.PurposeKinds {
		purposes = append(purposes, p)
	}
	slices.Sort(purposes)
	for _, p := range purposes {
		fmt.Fprintf(&w, " WHEN a.purpose_type = %s THEN %s", b.arg(p), b.arg(rules.PurposeKinds[p]))
	}
	for _, p := range rules.DataCollectionPurposes {
		fmt.Fprintf(&w, " WHEN a.purpose_type = %s THEN %s", b.arg(p), b.arg(rules.KindSSA))
	}
	types := make([]string, 0, len(rules.TypeKinds))
	for t := range rules.TypeKinds {
		types = append(types, t)
	}
	slices.Sort(types)
	for _, t := range types {
		fmt.Fprintf(&w, " WHEN a.activity_type = %s THEN %s", b.arg(t), b.arg(rules.TypeKinds[t]))
	}
	for _, t := range rules.DataCollectionTypes {
		fmt.Fprintf(&w, " WHEN a.activity_type = %s THEN %s", b.arg(t), b.arg(rules.KindSSA))
	}
	fmt.Fprintf(&w, " ELSE %s END", b.arg(kindFollowUp))
	return w.String()
}

// kindFollowUp is rules.KIND_FOLLOW_UP.
const kindFollowUp = "follow_up"

// outreachVisit is rules.outreach_visit_q: donor, story, invitation and
// social visits, and a Partner's SSA Support, at a school.
func (b *sql) outreachVisit() string {
	shaped := "a.activity_type = ANY(" + b.arg(rules.VisitShapeTypes) + ")"
	return `(a.school_id IS NOT NULL AND a.cluster_id IS NULL AND (a.activity_type = ANY(` + b.arg(rules.OutreachTypes) + `)
  OR (` + shaped + ` AND a.purpose_type = ANY(` + b.arg(rules.OutreachPurposes) + `))
  OR (` + shaped + ` AND a.purpose_type IS DISTINCT FROM ` + b.arg(rules.CompanionPurpose) + ` AND ` + b.ssaKind() + ` AND a.delivery_type = 'partner')))`
}

// cpoPlanned is rules.planned_q and not deleted, filed under the year.
func (b *sql) yearPlanned(fy string) string {
	return "a.fy = " + b.arg(fy) + " AND " + b.planned()
}

// peopleWindow is _in_window for the people read: the year keeps
// everything filed under it; any other window the rows dated inside it.
func (b *sql) peopleWindow(w cpoWindow) string {
	if w.isAnnual() {
		return "TRUE"
	}
	return b.insideWindow(cpoDay("a"), w)
}

// cpoPeoplePlan is people.people_plan with portfolio=False: every Programme
// Lead's and CCEO's own year over the schools kept.
func cpoPeoplePlan(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope, schools []*cpoSchool,
	w cpoWindow, n cpoNarrow, outside []string) ([]*cpoTeam, error) {
	pp, err := rosterPeople(ctx, db, scope)
	if err != nil {
		return nil, err
	}
	ids := keptSchoolIDs(schools, n)
	staffSide, partnerSide := n.channel != "partner", n.channel != "staff"
	type visitRow struct {
		staff, schoolType, kind string
		n                       int
	}
	type countRow struct {
		staff, kind string
		n           int
	}
	var visits []visitRow
	var outreach, trainings, sessions []countRow
	query := func(q string, args []any, scan func(func(...any) error) error) error {
		rows, err := db.Query(ctx, q, args...)
		if err != nil {
			return fmt.Errorf("planningmonitor: the people's plan: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			if err := scan(rows.Scan); err != nil {
				return err
			}
		}
		return rows.Err()
	}
	if staffSide {
		b := &sql{}
		q := `SELECT COALESCE(a.responsible_staff_id, ''), COALESCE(s.school_type, ''), ` + b.visitKindCase() + `, count(*)
FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE ` + b.yearPlanned(w.fy) + ` AND a.school_id = ANY(` + b.arg(ids) + `) AND a.delivery_type IS DISTINCT FROM 'partner'
  AND ` + b.countedVisit(outside) + ` AND ` + b.peopleWindow(w) + ` GROUP BY 1, 2, 3`
		if err := query(q, b.args, func(scan func(...any) error) error {
			var r visitRow
			err := scan(&r.staff, &r.schoolType, &r.kind, &r.n)
			visits = append(visits, r)
			return err
		}); err != nil {
			return nil, err
		}
		for _, part := range []struct {
			where string
			into  *[]countRow
		}{
			{"outreach", &outreach}, {"trainings", &trainings},
		} {
			b := &sql{}
			extra := ""
			switch part.where {
			case "outreach":
				extra = b.outreachVisit()
			case "trainings":
				extra = "a.activity_type = ANY(" + b.arg(rules.SchoolTrainingTypes) + ") AND a.cluster_id IS NULL"
			}
			q := `SELECT COALESCE(a.responsible_staff_id, ''), count(*) FROM activity a
WHERE ` + b.yearPlanned(w.fy) + ` AND a.school_id = ANY(` + b.arg(ids) + `) AND a.delivery_type IS DISTINCT FROM 'partner' AND ` + extra + `
  AND ` + b.peopleWindow(w) + ` GROUP BY 1`
			into := part.into
			if err := query(q, b.args, func(scan func(...any) error) error {
				var r countRow
				err := scan(&r.staff, &r.n)
				*into = append(*into, r)
				return err
			}); err != nil {
				return nil, err
			}
		}
		b = &sql{}
		where := ""
		if n.region != "" {
			where += " AND c.region_id = " + b.arg(n.region)
		}
		if n.district != "" {
			where += " AND c.district_id = " + b.arg(n.district)
		}
		q = `SELECT COALESCE(a.responsible_staff_id, ''), a.activity_type, count(*) FROM activity a LEFT JOIN cluster c ON c.id = a.cluster_id
WHERE ` + b.yearPlanned(w.fy) + ` AND a.delivery_type IS DISTINCT FROM 'partner' AND a.cluster_id IS NOT NULL
  AND a.activity_type = ANY(` + b.arg(append(slices.Clone(rules.TrainingTypes), rules.ClusterMeetingTypes...)) + `)` + where + `
  AND ` + b.peopleWindow(w) + ` GROUP BY 1, 2`
		if err := query(q, b.args, func(scan func(...any) error) error {
			var r countRow
			err := scan(&r.staff, &r.kind, &r.n)
			sessions = append(sessions, r)
			return err
		}); err != nil {
			return nil, err
		}
	}
	type handover struct {
		school, partner, status, monitor, assigner, scheduled, source, holder string
		created                                                               *time.Time
	}
	type work struct {
		id, school, partner, monitor, responsible, holder string
		planned                                           int
	}
	var handovers []handover
	var partnerWork []work
	if partnerSide {
		b := &sql{}
		where := ""
		if n.partner != "" {
			where = " AND pa.partner_id = " + b.arg(n.partner)
		}
		q := `SELECT pa.school_id, COALESCE(pa.partner_id, ''), pa.status, COALESCE(pa.monitoring_staff_id, ''), COALESCE(pa.assigning_staff_id, ''),
  COALESCE(pa.scheduled_activity_id, ''), COALESCE(pa.source_activity_id, ''), COALESCE(s.account_owner_id, ''), pa.created_at
FROM partner_assignment pa LEFT JOIN school s ON s.id = pa.school_id
WHERE pa.school_id = ANY(` + b.arg(ids) + `) AND NOT COALESCE(pa.status = ANY(` + b.arg(rules.CountryOversight.ClosedHandoverStatuses) + `), false)
  AND ` + b.notOutside("pa.project_id", outside) + where
		if err := query(q, b.args, func(scan func(...any) error) error {
			var h handover
			err := scan(&h.school, &h.partner, &h.status, &h.monitor, &h.assigner, &h.scheduled, &h.source, &h.holder, &h.created)
			handovers = append(handovers, h)
			return err
		}); err != nil {
			return nil, err
		}
		b = &sql{}
		where = ""
		if n.partner != "" {
			where = " AND a.assigned_partner_id = " + b.arg(n.partner)
		}
		q = `SELECT a.id, a.school_id, COALESCE(a.assigned_partner_id, ''), COALESCE(a.monitored_by_staff_id, ''), COALESCE(a.responsible_staff_id, ''),
  COALESCE(s.account_owner_id, ''), CASE WHEN ` + b.partnerPlanned() + ` THEN 1 ELSE 0 END
FROM activity a LEFT JOIN school s ON s.id = a.school_id
WHERE a.fy = ` + b.arg(w.fy) + ` AND a.deleted_at IS NULL AND a.school_id = ANY(` + b.arg(ids) + `) AND ` + b.partnerHeld() + `
  AND ` + b.notOutside("a.project_id", outside) + where + ` AND ` + b.peopleWindow(w)
		if err := query(q, b.args, func(scan func(...any) error) error {
			var r work
			err := scan(&r.id, &r.school, &r.partner, &r.monitor, &r.responsible, &r.holder, &r.planned)
			partnerWork = append(partnerWork, r)
			return err
		}); err != nil {
			return nil, err
		}
	}
	for _, r := range visits {
		pp.note(r.staff)
	}
	for _, r := range outreach {
		pp.note(r.staff)
	}
	for _, r := range trainings {
		pp.note(r.staff)
	}
	for _, r := range sessions {
		pp.note(r.staff)
	}
	for _, h := range handovers {
		pp.note(h.monitor, h.assigner, h.holder)
	}
	for _, r := range partnerWork {
		pp.note(r.monitor, r.responsible, r.holder)
	}
	if err := pp.resolve(ctx, db); err != nil {
		return nil, err
	}
	for _, r := range visits {
		p := pp.get(r.staff, cpoUnrecorded)
		p.visits[r.kind] += r.n
		p.visitsByType[r.schoolType] += r.n
	}
	for _, r := range outreach {
		pp.get(r.staff, cpoUnrecorded).outreach += r.n
	}
	for _, r := range trainings {
		pp.get(r.staff, cpoUnrecorded).trainings += r.n
	}
	for _, r := range sessions {
		p := pp.get(r.staff, cpoUnrecorded)
		if slices.Contains(rules.ClusterMeetingTypes, r.kind) {
			p.meetings += r.n
		} else {
			p.clusterTrainings += r.n
		}
	}
	fy := 0
	fmt.Sscan(w.fy, &fy)
	readsHandovers := !w.fyStart.Before(w.start) && w.fyStart.Before(w.end)
	handedBy := map[string][2]string{}
	carried := map[string]bool{}
	for _, h := range handovers {
		if h.scheduled != "" {
			handedBy[h.scheduled] = [2]string{h.monitor, h.assigner}
			continue
		}
		waiting := slices.Contains(rules.CountryOversight.UnscheduledHandoverStatuses, h.status) && h.created != nil &&
			cpoOperationalFY(*h.created) <= fy
		if !waiting {
			continue
		}
		if h.source != "" {
			carried[h.source] = true
			handedBy[h.source] = [2]string{h.monitor, h.assigner}
		}
		if !readsHandovers {
			continue
		}
		p := pp.first(h.monitor, h.assigner, h.holder)
		if p == nil {
			p = pp.get("", cpoUnrecorded)
		}
		p.hand(h.partner, h.school, 0)
	}
	for _, r := range partnerWork {
		if carried[r.id] {
			continue
		}
		by := handedBy[r.id]
		p := pp.first(by[0], by[1], r.monitor, r.responsible, r.holder)
		if p == nil {
			p = pp.get("", cpoUnrecorded)
		}
		p.hand(r.partner, r.school, r.planned)
	}
	teams := []*cpoTeam{}
	for _, key := range pp.teamOrder {
		t := pp.teams[key]
		if key == cpoOtherTeam {
			kept := []*cpoPerson{}
			for _, p := range t.people {
				if p.hasAnything() {
					kept = append(kept, p)
				}
			}
			sort.SliceStable(kept, func(i, j int) bool {
				ai, aj := strings.HasPrefix(kept[i].key, "__"), strings.HasPrefix(kept[j].key, "__")
				if ai != aj {
					return !ai
				}
				return kept[i].name < kept[j].name
			})
			if len(kept) == 0 {
				continue
			}
			t.people = kept
		}
		teams = append(teams, t)
	}
	return teams, nil
}

// keptSchoolIDs is Narrow.schools over the eligible schools.
func keptSchoolIDs(schools []*cpoSchool, n cpoNarrow) []string {
	ids := []string{}
	for _, s := range schools {
		if n.schoolIDs != nil && !slices.Contains(n.schoolIDs, s.id) {
			continue
		}
		if (n.region != "" && s.regionID != n.region) || (n.district != "" && s.districtID != n.district) ||
			(n.schoolType != "" && s.schoolType != n.schoolType) {
			continue
		}
		if n.clusterStatus == "clustered" && !s.clustered() || n.clusterStatus == "unclustered" && s.clustered() {
			continue
		}
		ids = append(ids, s.id)
	}
	return ids
}

// rosterPeople is _People(country): the roster's teams and people, every id
// they go by pointing at their row.
func rosterPeople(ctx context.Context, db schooldirectory.Querier, scope schooldirectory.Scope) (*cpoPeople, error) {
	m := &monitor{db: db}
	roster, err := m.roster(ctx, lensOf(scope))
	if err != nil {
		return nil, err
	}
	pp := &cpoPeople{teams: map[string]*cpoTeam{}, byID: map[string]*cpoPerson{}, pending: map[string]bool{}}
	for _, t := range roster {
		key, name := t.lead.Key, t.lead.Name
		if t.noLead {
			key, name = rules.NoLead[0], rules.NoLead[1]
		}
		team := &cpoTeam{key: key, name: name}
		pp.teams[key] = team
		pp.teamOrder = append(pp.teamOrder, key)
		for _, person := range t.people {
			role := rules.CCEORole
			if person.lead {
				role = rules.ProgramLeadRole
			}
			row := newPerson(person.key, person.name, role, key, name)
			team.people = append(team.people, row)
			for _, id := range person.ids {
				pp.byID[id] = row
			}
		}
	}
	return pp, nil
}

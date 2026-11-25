package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"strings"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The people-first tables: the year's activity records as people.Reads
// defines each set, one row an activity (tables._Book, _read).

// cpoActivity is one activity as _read loads it.
type cpoActivity struct {
	id, school, cluster, responsible, monitor, partner, project string
	activityType, purpose, delivery, status, kind               string
	course, catalogue, snapshot, focus, purposeIntervention     string
	courseID, catalogueID                                       string
	code, name, schoolType, district, schoolCluster, owner      string
	on                                                          *time.Time
	created                                                     time.Time
	partnerPlanned                                              bool
}

const cpoActivityColumns = `a.id, COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.responsible_staff_id, ''),
  COALESCE(a.monitored_by_staff_id, ''), COALESCE(a.assigned_partner_id, ''), COALESCE(a.project_id, ''),
  COALESCE(a.activity_type, ''), COALESCE(a.purpose_type, ''), COALESCE(a.delivery_type, ''), COALESCE(a.status, ''),
  COALESCE(NULLIF(tc.display_name, ''), tc.source_name, ''), COALESCE(NULLIF(ci.display_name, ''), ci.source_name, ''),
  COALESCE(a.activity_name_snapshot, ''), COALESCE(a.focus_intervention, ''), COALESCE(a.purpose_intervention, ''),
  COALESCE(a.training_course_id, ''), COALESCE(a.catalogue_item_id, ''),
  COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''), COALESCE(s.district_id, ''),
  COALESCE(s.cluster_id, ''), COALESCE(s.account_owner_id, ''), `

const cpoActivityJoins = ` FROM activity a LEFT JOIN school s ON s.id = a.school_id
  LEFT JOIN activity_catalogue_item tc ON tc.id = a.training_course_id
  LEFT JOIN activity_catalogue_item ci ON ci.id = a.catalogue_item_id
  LEFT JOIN cluster c ON c.id = a.cluster_id`

// readActivities is _read over one set, in Activity's own order (newest
// first, a tie by id where the existing page leaves it to the database):
// where is the set's condition, kind and planned the expressions
// its rows are annotated with.
func readActivities(ctx context.Context, db schooldirectory.Querier, b *sql, where, kind, planned string) ([]*cpoActivity, error) {
	q := `SELECT ` + cpoActivityColumns + cpoDay("a") + `, a.created_at, ` + kind + `, ` + planned + cpoActivityJoins + ` WHERE ` + where + ` ORDER BY a.created_at DESC, a.id`
	rows, err := db.Query(ctx, q, b.args...)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the year's activities: %w", err)
	}
	defer rows.Close()
	out := []*cpoActivity{}
	for rows.Next() {
		a := &cpoActivity{}
		if err := rows.Scan(&a.id, &a.school, &a.cluster, &a.responsible, &a.monitor, &a.partner, &a.project,
			&a.activityType, &a.purpose, &a.delivery, &a.status, &a.course, &a.catalogue, &a.snapshot, &a.focus,
			&a.purposeIntervention, &a.courseID, &a.catalogueID, &a.code, &a.name, &a.schoolType, &a.district,
			&a.schoolCluster, &a.owner, &a.on, &a.created, &a.kind, &a.partnerPlanned); err != nil {
			return nil, err
		}
		out = append(out, a)
	}
	return out, rows.Err()
}

// cpoBook is tables._Book: one table's reading of the year.
type cpoBook struct {
	ctx      context.Context
	db       schooldirectory.Querier
	snap     *cpoSnapshot
	places   *cpoPlaces
	extra    cpoExtra
	staff    *cpoPeople
	window   cpoWindow
	ids      []string
	partners map[string]string
	projects map[string]string
	invited  map[string]int
	fixed    map[string]string
}

func newBook(ctx context.Context, db schooldirectory.Querier, snap *cpoSnapshot, places *cpoPlaces, e cpoExtra) (*cpoBook, error) {
	staff, err := rosterPeople(ctx, db, snap.scope)
	if err != nil {
		return nil, err
	}
	fixed, err := cpoFixedInterventions(ctx, db)
	if err != nil {
		return nil, err
	}
	return &cpoBook{ctx: ctx, db: db, snap: snap, places: places, extra: e, staff: staff,
		window: peopleWindow(cpoWindowOf(snap.filters)), ids: keptSchoolIDs(snap.data.schools, snap.narrow),
		partners: map[string]string{}, projects: map[string]string{}, invited: map[string]int{}, fixed: fixed}, nil
}

func (k *cpoBook) staffSide() bool   { return k.snap.narrow.channel != "partner" }
func (k *cpoBook) partnerSide() bool { return k.snap.narrow.channel != "staff" }

// cpoFixedInterventions is training_intervention.fixed_interventions.
func cpoFixedInterventions(ctx context.Context, db schooldirectory.Querier) (map[string]string, error) {
	out := map[string]string{}
	rows, err := db.Query(ctx, `SELECT catalogue_item_id, intervention FROM activity_intervention_mapping
WHERE active AND mapping_mode = 'fixed' AND intervention IS NOT NULL AND intervention <> ''
ORDER BY is_primary DESC, priority, id`)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the courses' interventions: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, intervention string
		if err := rows.Scan(&id, &intervention); err != nil {
			return nil, err
		}
		if _, seen := out[id]; !seen {
			out[id] = intervention
		}
	}
	return out, rows.Err()
}

// learn is _Book.learn: who and what these rows name, in one read each.
func (k *cpoBook) learn(acts []*cpoActivity, staffIDs, partnerIDs, projectIDs []string) error {
	partners, projects, sessions := slices.Clone(partnerIDs), slices.Clone(projectIDs), []string{}
	k.staff.note(staffIDs...)
	for _, a := range acts {
		k.staff.note(a.responsible, a.monitor)
		partners = append(partners, a.partner)
		projects = append(projects, a.project)
		if a.school == "" {
			k.staff.note(k.places.clusters[a.cluster][2])
			sessions = append(sessions, a.id)
		} else {
			k.staff.note(a.owner)
		}
	}
	if err := k.staff.resolve(k.ctx, k.db); err != nil {
		return err
	}
	for table, into := range map[string]map[string]string{"partner": k.partners, "project": k.projects} {
		ids := partners
		if table == "project" {
			ids = projects
		}
		want := []string{}
		for _, id := range ids {
			if _, known := into[id]; id != "" && !known {
				want = append(want, id)
			}
		}
		names, err := cpoNames(k.ctx, k.db, table, want)
		if err != nil {
			return err
		}
		for _, o := range names {
			into[o.value] = o.label
		}
	}
	if len(sessions) == 0 {
		return nil
	}
	rows, err := k.db.Query(k.ctx, `SELECT activity_id, count(*) FROM cluster_activity_attendance
		WHERE activity_id = ANY($1) AND invited GROUP BY 1`, sessions)
	if err != nil {
		return fmt.Errorf("planningmonitor: the sessions' invitations: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			return err
		}
		k.invited[id] = n
	}
	return rows.Err()
}

// keepsPerson is _keeps_person.
func (k *cpoBook) keepsPerson(p *cpoPerson) bool {
	f := k.snap.filters
	if f.programLead != "" && (p == nil || p.teamKey != f.programLead) {
		return false
	}
	return f.cceo == "" || p != nil && p.key == f.cceo
}

// keeps is _Book.keeps.
func (k *cpoBook) keeps(p *cpoPerson, place cpoRow, project string) bool {
	e := k.extra
	return k.keepsPerson(p) && (e.subRegion == "" || place["_sub_region"] == e.subRegion) &&
		(e.cluster == "" || place["_cluster"] == e.cluster) && (e.project == "" || project == e.project)
}

// who is _who: (Programme Lead, name) for a row.
func who(p *cpoPerson) (string, string) {
	labels := rules.CountryOversight.Page.TableLabels
	if p == nil {
		return labels["no_lead"], labels["nobody"]
	}
	if p.teamKey == cpoOtherTeam {
		return labels["no_lead"], p.name
	}
	return p.teamName, p.name
}

// ofSchool is _Places.of_school for an activity's school: the dataset's
// record, else the school's own columns.
func (k *cpoBook) ofSchool(a *cpoActivity) cpoRow {
	if s := k.snap.data.byID[a.school]; s != nil {
		return k.places.ofRecord(s)
	}
	labels := rules.CountryOversight.Page.TableLabels
	d := k.places.districts[a.district]
	cluster, clusterID := labels["unclustered"], ""
	if c, ok := k.places.clusters[a.schoolCluster]; ok {
		cluster, clusterID = c[0], a.schoolCluster
		if cluster == "" {
			cluster = "Cluster"
		}
	}
	kind := ""
	if a.schoolType != "" {
		kind = typeLabel(a.schoolType)
	}
	return cpoRow{"holder_lead": labels["no_lead"], "holder": labels["no_owner"], "sub_region": d[2], "district": d[0],
		"cluster": cluster, "school_id": a.code, "school": a.name, "type": kind, "_sub_region": d[1], "_cluster": clusterID,
		"_school": a.school}
}

// ofCluster is _Places.of_cluster: a session under the person responsible
// for its cluster, in the cluster's own district.
func (k *cpoBook) ofCluster(cluster string, p *cpoPerson) cpoRow {
	c := k.places.clusters[cluster]
	d := k.places.districts[c[1]]
	lead, name := who(p)
	label := c[0]
	if label == "" {
		label = "Cluster"
	}
	return cpoRow{"holder_lead": lead, "holder": name, "sub_region": d[2], "district": d[0], "cluster": label,
		"school_id": "", "school": label + " (cluster)", "type": "", "_sub_region": d[1], "_cluster": cluster, "_school": ""}
}

// typeLabelOf is _Book.type_label.
func typeLabelOf(t string) string {
	if l := rules.CountryOversight.Page.TableWords.Types[t]; l != "" {
		return l
	}
	return pyTitleWords(strings.ReplaceAll(t, "_", " "))
}

// pyTitleWords is str.title.
func pyTitleWords(s string) string {
	out := []rune{}
	prev := false
	for _, r := range s {
		letter := r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z'
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

// intervention is _Book.describe's SSA intervention.
func (k *cpoBook) intervention(a *cpoActivity) string {
	_, _, v := partneroversight.DescribeActivity(a.purpose, a.activityType, a.course, a.catalogue, a.snapshot, a.focus, a.purposeIntervention)
	if v == "" && slices.Contains(rules.TrainingTypes, a.activityType) {
		code := k.fixed[a.courseID]
		if code == "" {
			code = k.fixed[a.catalogueID]
		}
		v = rules.CountryOversight.Page.TableWords.Interventions[code]
	}
	return v
}

func (k *cpoBook) course(a *cpoActivity) string {
	c, _, _ := partneroversight.DescribeActivity(a.purpose, a.activityType, a.course, a.catalogue, a.snapshot, a.focus, a.purposeIntervention)
	return c
}

// row is _Book.row: one listed activity, or nil where the selection drops it.
func (k *cpoBook) row(a *cpoActivity, p *cpoPerson, channel, label, counted string, holder *cpoPerson) cpoRow {
	var place cpoRow
	if a.school == "" {
		h := holder
		if h == nil {
			h = p
		}
		place = k.ofCluster(a.cluster, h)
	} else {
		place = k.ofSchool(a)
	}
	if !k.keeps(p, place, a.project) {
		return nil
	}
	_, name := who(p)
	if label == "" {
		label = typeLabelOf(a.activityType)
	}
	status := rules.CountryOversight.Page.TableWords.Statuses[a.status]
	if status == "" {
		status = a.status
	}
	row := cpoRow{}
	for key, v := range place {
		row[key] = v
	}
	var on any
	if a.on != nil {
		on = *a.on
	}
	partner := ""
	if channel == "Partner" {
		partner = k.partners[a.partner]
	}
	row["lead"], row["staff"], row["by_name"], row["channel"] = place["holder_lead"], name, name, channel
	row["activity"], row["course"], row["intervention"] = label, k.course(a), k.intervention(a)
	row["date"], row["status"], row["counted"] = on, status, counted
	row["project"], row["_project"], row["partner"] = k.projects[a.project], a.project, partner
	row["is_training"] = slices.Contains(rules.TrainingTypes, a.activityType)
	row["is_visit"] = visitKind(a.activityType, a.purpose, a.project, a.delivery, k.snap.outside) != ""
	if a.school == "" {
		row["invited"] = k.invited[a.id]
	}
	return row
}

// staffRows is the rows of one staff set, each under its responsible person.
func (k *cpoBook) staffRows(acts []*cpoActivity, label func(*cpoActivity) string, counted string, sessions bool) ([]cpoRow, error) {
	if err := k.learn(acts, nil, nil, nil); err != nil {
		return nil, err
	}
	out := []cpoRow{}
	for _, a := range acts {
		p := k.staff.first(a.responsible)
		var holder *cpoPerson
		if sessions {
			if holder = k.staff.first(k.places.clusters[a.cluster][2]); holder == nil {
				holder = p
			}
		}
		if r := k.row(a, p, "Staff", label(a), counted, holder); r != nil {
			out = append(out, r)
		}
	}
	return out, nil
}

// staffSet is people.Reads._staff narrowed to one set at the kept schools.
func (k *cpoBook) staffSet(b *sql, set string) string {
	return b.yearPlanned(k.window.fy) + ` AND a.school_id = ANY(` + b.arg(k.ids) + `) AND a.delivery_type IS DISTINCT FROM 'partner'
  AND ` + set + ` AND ` + b.peopleWindow(k.window)
}

// visitRows is _visit_rows: the counted staff visits, by kind.
func (k *cpoBook) visitRows() ([]cpoRow, error) {
	if !k.staffSide() {
		return nil, nil
	}
	b := &sql{}
	acts, err := readActivities(k.ctx, k.db, b, k.staffSet(b, b.countedVisit(k.snap.outside)), b.visitKindCase(), "false")
	if err != nil {
		return nil, err
	}
	kinds := rules.CountryOversight.Page.TableWords.Kinds
	return k.staffRows(acts, func(a *cpoActivity) string {
		if l := kinds[a.kind]; l != "" {
			return l
		}
		return a.kind
	}, "Yes", false)
}

// sessionRows is _session_rows: the staff cluster sessions, meetings true
// for the meetings alone, false for the trainings alone.
func (k *cpoBook) sessionRows(meetings *bool) ([]cpoRow, error) {
	if !k.staffSide() {
		return nil, nil
	}
	b := &sql{}
	n := k.snap.narrow
	where := b.yearPlanned(k.window.fy) + ` AND a.delivery_type IS DISTINCT FROM 'partner' AND a.cluster_id IS NOT NULL
  AND a.activity_type = ANY(` + b.arg(append(slices.Clone(rules.TrainingTypes), rules.ClusterMeetingTypes...)) + `)`
	if n.region != "" {
		where += " AND c.region_id = " + b.arg(n.region)
	}
	if n.district != "" {
		where += " AND c.district_id = " + b.arg(n.district)
	}
	if meetings != nil {
		op := "= ANY("
		if !*meetings {
			op = "<> ALL("
		}
		where += " AND a.activity_type " + op + b.arg(rules.ClusterMeetingTypes) + ")"
	}
	where += " AND " + b.peopleWindow(k.window)
	acts, err := readActivities(k.ctx, k.db, b, where, "''", "false")
	if err != nil {
		return nil, err
	}
	return k.staffRows(acts, func(*cpoActivity) string { return "" }, "", true)
}

// twiceCodes is _twice_codes: the School IDs of every school planned twice.
func twiceCodes(snap *cpoSnapshot) map[string]bool {
	out := map[string]bool{}
	for _, s := range snap.data.schools {
		if v := cpoTally(snap.data.vectors[s.id]); len(v) > 0 && v.n("duplicates") != 0 {
			out[s.code] = true
		}
	}
	return out
}

func flagRows(rows []cpoRow, codes map[string]bool) []cpoRow {
	for _, r := range rows {
		code, _ := r["school_id"].(string)
		r["flag"] = ""
		if codes[code] {
			r["flag"] = "Planned twice"
		}
	}
	return rows
}

// balance is _balance.
func balance(planned, expected int) string {
	if expected == 0 {
		return "no target"
	}
	return cpoFmt(planned) + " of " + cpoFmt(expected) + " · " + cpoFmt(max(0, expected-planned)) + " to plan"
}

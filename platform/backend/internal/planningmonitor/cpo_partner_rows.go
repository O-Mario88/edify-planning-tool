package planningmonitor

import (
	"fmt"
	"slices"
	"strconv"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/partneroversight"
)

// The Partner side of the people-first tables: the hand-overs that still
// put a school in a Partner's hands and the Partner work itself
// (tables._partner_rows, _partner_session_rows, _partner_state).

// cpoHandoverRow is one hand-over as _partner_rows reads it.
type cpoHandoverRow struct {
	school, partner, project, status, monitor, assigner, scheduled, source string
	support, visitNumber, trainingNumber, expected, purpose, focus         string
	course, catalogue, sourceCourse, sourceSnapshot, sourceType            string
	code, name, schoolType, district, schoolCluster, owner                 string
	created                                                                time.Time
}

// handovers is Reads.handovers: the open hand-overs at the kept schools.
func (k *cpoBook) handovers(every bool) ([]*cpoHandoverRow, error) {
	b := &sql{}
	where := `pa.school_id = ANY(` + b.arg(k.ids) + `) AND NOT COALESCE(pa.status = ANY(` +
		b.arg(rules.CountryOversight.ClosedHandoverStatuses) + `), false)`
	if !every {
		where += " AND " + b.notOutside("pa.project_id", k.snap.outside)
	}
	if p := k.snap.narrow.partner; p != "" {
		where += " AND pa.partner_id = " + b.arg(p)
	}
	rows, err := k.db.Query(k.ctx, `SELECT COALESCE(pa.school_id, ''), COALESCE(pa.partner_id, ''), COALESCE(pa.project_id, ''),
  COALESCE(pa.status, ''), COALESCE(pa.monitoring_staff_id, ''), COALESCE(pa.assigning_staff_id, ''),
  COALESCE(pa.scheduled_activity_id, ''), COALESCE(pa.source_activity_id, ''), COALESCE(pa.support_type, ''),
  COALESCE(pa.visit_number::text, ''), COALESCE(pa.training_number::text, ''), COALESCE(pa.expected_activity_type, ''),
  COALESCE(pa.purpose_of_visit, ''), COALESCE(pa.focus_intervention, ''),
  COALESCE(NULLIF(tc.display_name, ''), tc.source_name, ''), COALESCE(NULLIF(ci.display_name, ''), ci.source_name, ''),
  COALESCE(NULLIF(stc.display_name, ''), stc.source_name, ''), COALESCE(sa.activity_name_snapshot, ''), COALESCE(sa.activity_type, ''),
  COALESCE(s.school_id, ''), COALESCE(s.name, ''), COALESCE(s.school_type, ''), COALESCE(s.district_id, ''),
  COALESCE(s.cluster_id, ''), COALESCE(s.account_owner_id, ''), pa.created_at
FROM partner_assignment pa LEFT JOIN school s ON s.id = pa.school_id
  LEFT JOIN activity_catalogue_item tc ON tc.id = pa.training_course_id
  LEFT JOIN activity_catalogue_item ci ON ci.id = pa.catalogue_item_id
  LEFT JOIN activity sa ON sa.id = pa.source_activity_id
  LEFT JOIN activity_catalogue_item stc ON stc.id = sa.training_course_id
WHERE `+where+` ORDER BY pa.created_at DESC, pa.id`, b.args...)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the open hand-overs: %w", err)
	}
	defer rows.Close()
	out := []*cpoHandoverRow{}
	for rows.Next() {
		h := &cpoHandoverRow{}
		if err := rows.Scan(&h.school, &h.partner, &h.project, &h.status, &h.monitor, &h.assigner, &h.scheduled, &h.source,
			&h.support, &h.visitNumber, &h.trainingNumber, &h.expected, &h.purpose, &h.focus, &h.course, &h.catalogue,
			&h.sourceCourse, &h.sourceSnapshot, &h.sourceType, &h.code, &h.name, &h.schoolType, &h.district,
			&h.schoolCluster, &h.owner, &h.created); err != nil {
			return nil, err
		}
		out = append(out, h)
	}
	return out, rows.Err()
}

// partnerWork is Reads.partner_work: live Partner activities at the kept
// schools, each marked partner_planned.
func (k *cpoBook) partnerWork(every bool) ([]*cpoActivity, error) {
	b := &sql{}
	where := `a.fy = ` + b.arg(k.window.fy) + ` AND a.deleted_at IS NULL AND a.school_id = ANY(` + b.arg(k.ids) + `) AND ` + b.partnerHeld()
	if !every {
		where += " AND " + b.notOutside("a.project_id", k.snap.outside)
	}
	if p := k.snap.narrow.partner; p != "" {
		where += " AND a.assigned_partner_id = " + b.arg(p)
	}
	where += " AND " + b.peopleWindow(k.window)
	return readActivities(k.ctx, k.db, b, where, "''", "("+b.partnerPlanned()+")")
}

// partnerSessions is Reads.partner_sessions: the cluster sessions a Partner
// delivers, meetings as for sessionRows.
func (k *cpoBook) partnerSessions(meetings *bool) ([]*cpoActivity, error) {
	b := &sql{}
	n := k.snap.narrow
	where := `a.fy = ` + b.arg(k.window.fy) + ` AND a.deleted_at IS NULL AND ` + b.partnerHeld() + ` AND a.cluster_id IS NOT NULL
  AND a.school_id IS NULL AND a.activity_type = ANY(` + b.arg(append(slices.Clone(rules.TrainingTypes), rules.ClusterMeetingTypes...)) + `)`
	if n.region != "" {
		where += " AND c.region_id = " + b.arg(n.region)
	}
	if n.district != "" {
		where += " AND c.district_id = " + b.arg(n.district)
	}
	if n.partner != "" {
		where += " AND a.assigned_partner_id = " + b.arg(n.partner)
	}
	where += meetingFilter(b, meetings) + " AND " + b.peopleWindow(k.window)
	return readActivities(k.ctx, k.db, b, where, "''", "("+b.partnerPlanned()+")")
}

func meetingFilter(b *sql, meetings *bool) string {
	if meetings == nil {
		return ""
	}
	op := "= ANY("
	if !*meetings {
		op = "<> ALL("
	}
	return " AND a.activity_type " + op + b.arg(rules.ClusterMeetingTypes) + ")"
}

// partnerState is _partner_state: what a Partner activity's row says of its
// date.
func partnerState(r cpoRow, a *cpoActivity) {
	labels := rules.CountryOversight.Page.TableLabels
	if a.partnerPlanned {
		r["state"], r["staff_date"] = labels["partner_planned"], nil
		return
	}
	waiting := slices.Contains(rules.CountryOversight.Page.TableWords.WaitingStates, a.status)
	r["state"] = labels["awaiting_partner"]
	var on any
	if a.on != nil {
		on = *a.on
	}
	r["staff_date"] = on
	if waiting {
		r["date"], r["status"] = nil, labels["assigned"]
	} else {
		r["date"] = on
	}
}

// waiting is Reads.waiting: a hand-over still waiting for the Partner's
// date, this year.
func (k *cpoBook) waiting(status string, created time.Time) bool {
	fy, _ := strconv.Atoi(k.window.fy)
	return slices.Contains(rules.CountryOversight.UnscheduledHandoverStatuses, status) && cpoOperationalFY(created) <= fy
}

// readsHandovers is Reads.reads_handovers: a window that holds the year's
// first day.
func (k *cpoBook) readsHandovers() bool {
	w := k.window
	return !w.start.After(w.fyStart) && w.fyStart.Before(w.end)
}

// localDay is _local: a stored moment as the local day it fell on.
func localDay(t time.Time) time.Time {
	l := t.In(cpoLocation)
	return date(l.Year(), l.Month(), l.Day())
}

// partnerRows is _partner_rows: every piece of work in a Partner's hands,
// under who assigned it.
func (k *cpoBook) partnerRows(every bool) ([]cpoRow, error) {
	if !k.partnerSide() {
		return nil, nil
	}
	hs, err := k.handovers(every)
	if err != nil {
		return nil, err
	}
	work, err := k.partnerWork(every)
	if err != nil {
		return nil, err
	}
	staff, partners, projects := []string{}, []string{}, []string{}
	for _, h := range hs {
		staff = append(staff, h.monitor, h.assigner, h.owner)
		partners = append(partners, h.partner)
		projects = append(projects, h.project)
	}
	if err := k.learn(work, staff, partners, projects); err != nil {
		return nil, err
	}
	labels := rules.CountryOversight.Page.TableLabels
	type origin struct {
		monitor, assigner string
		created           time.Time
	}
	handedBy, carried := map[string]origin{}, map[string]bool{}
	rows := []cpoRow{}
	for _, h := range hs {
		o := origin{h.monitor, h.assigner, h.created}
		if h.scheduled != "" {
			handedBy[h.scheduled] = o
			continue
		}
		if !k.waiting(h.status, h.created) {
			continue
		}
		if h.source != "" {
			carried[h.source] = true
			handedBy[h.source] = o
		}
		if !k.readsHandovers() || h.school == "" {
			continue
		}
		p := k.staff.first(h.monitor, h.assigner, h.owner)
		place := k.ofSchool(&cpoActivity{school: h.school, code: h.code, name: h.name, schoolType: h.schoolType,
			district: h.district, schoolCluster: h.schoolCluster})
		if !k.keeps(p, place, h.project) {
			continue
		}
		isVisit := handoverKind(h.schoolType, cpoHandover{supportType: h.support, visitNumber: h.visitNumber,
			trainingNumber: h.trainingNumber, projectID: h.project, expected: h.expected, purpose: h.purpose}, k.snap.outside) == "visit"
		expected := h.expected
		shape := expected
		if shape == "" {
			shape = "school_visit"
		}
		kind := handoverVisitKind(shape, h.purpose)
		dataCollection := isDataCollection(expected, h.purpose)
		_, _, intervention := partneroversight.DescribeHandover(h.purpose, expected, h.course, h.catalogue, h.focus,
			h.source != "", h.sourceCourse, h.sourceSnapshot, h.sourceType)
		course, purpose, _ := partneroversight.DescribeHandover(h.purpose, expected, h.course, h.catalogue, h.focus,
			h.source != "", h.sourceCourse, h.sourceSnapshot, h.sourceType)
		lead, name := who(p)
		partner := k.partners[h.partner]
		if partner == "" {
			partner = "Unrecorded Partner"
		}
		activity := ""
		switch {
		case dataCollection:
			activity = labels["data_collection"]
		case isVisit:
			activity = rules.CountryOversight.Page.TableWords.Kinds[kind]
			if activity == "" {
				activity = "Visit"
			}
		default:
			if expected != "" {
				activity = typeLabelOf(expected)
			}
			if activity == "" {
				activity = "Training"
			}
		}
		counted := ""
		if dataCollection {
			counted = "No"
		}
		row := cpoRow{}
		for key, v := range place {
			row[key] = v
		}
		row["lead"], row["staff"], row["channel"], row["by_name"] = place["holder_lead"], name, "Partner", partner
		row["partner"], row["assigned_by"], row["activity"], row["course"] = partner, name, activity, course
		row["intervention"], row["is_training"], row["is_visit"] = intervention, !isVisit && !dataCollection, isVisit
		row["assigned_on"], row["date"], row["staff_date"] = localDay(h.created), nil, nil
		row["state"], row["status"], row["counted"] = labels["awaiting_partner"], labels["assigned"], counted
		row["project"], row["_project"] = k.projects[h.project], h.project
		monitor := ""
		if h.monitor != "" {
			monitor = name
		}
		// What only the workbook prints: nothing is scheduled yet.
		row["planner_lead"], row["role"], row["purpose"], row["facilitator"] = lead, roleOf(p), purpose, ""
		row["monitor"], row["quarter"], row["participants"], row["cost"] = monitor, "", "", int64(0)
		row["salesforce"], row["evidence"], row["ia"], row["payment"] = "", "", "", ""
		row["rescheduled"], row["recorded"] = 0, localDay(h.created)
		rows = append(rows, row)
	}
	for _, a := range work {
		if carried[a.id] {
			continue // listed once, as the hand-over that carries it
		}
		o, handed := handedBy[a.id]
		p := k.staff.first(o.monitor, o.assigner, a.monitor, a.responsible, a.owner)
		label := ""
		counted := ""
		if isDataCollection(a.activityType, a.purpose) {
			label, counted = labels["data_collection"], "No"
		} else {
			label = rules.CountryOversight.Page.TableWords.Kinds[handoverVisitKind(a.activityType, a.purpose)]
		}
		row := k.row(a, p, "Partner", label, counted, nil)
		if row == nil {
			continue
		}
		partnerState(row, a)
		if row["partner"] == "" {
			row["partner"] = "Unrecorded Partner"
		}
		row["by_name"], row["assigned_by"] = row["partner"], row["staff"]
		if handed {
			row["assigned_on"] = localDay(o.created)
		} else {
			row["assigned_on"] = localDay(a.created)
		}
		rows = append(rows, row)
	}
	return rows, nil
}

// partnerSessionRows is _partner_session_rows: the cluster sessions a
// Partner delivers.
func (k *cpoBook) partnerSessionRows(meetings *bool) ([]cpoRow, error) {
	if !k.partnerSide() {
		return nil, nil
	}
	acts, err := k.partnerSessions(meetings)
	if err != nil {
		return nil, err
	}
	if err := k.learn(acts, nil, nil, nil); err != nil {
		return nil, err
	}
	rows := []cpoRow{}
	for _, a := range acts {
		responsible := k.staff.first(k.places.clusters[a.cluster][2])
		p := k.staff.first(a.monitor, a.responsible)
		if p == nil {
			p = responsible
		}
		holder := responsible
		if holder == nil {
			holder = p
		}
		row := k.row(a, p, "Partner", "", "", holder)
		if row == nil {
			continue
		}
		partnerState(row, a)
		row["assigned_by"] = row["staff"]
		row["by_name"] = row["partner"]
		if row["by_name"] == "" {
			row["by_name"] = "Unrecorded Partner"
		}
		rows = append(rows, row)
	}
	return rows, nil
}

// outreachRows is _outreach_rows: donor, story, invitation and social
// visits, shown and never counted.
func (k *cpoBook) outreachRows() ([]cpoRow, error) {
	if !k.staffSide() {
		return nil, nil
	}
	b := &sql{}
	acts, err := readActivities(k.ctx, k.db, b, k.staffSet(b, b.outreachVisit()), "''", "false")
	if err != nil {
		return nil, err
	}
	dc := rules.CountryOversight.Page.TableLabels["data_collection"]
	return k.staffRows(acts, func(a *cpoActivity) string {
		if isDataCollection(a.activityType, a.purpose) {
			return dc
		}
		return ""
	}, "No", false)
}

// trainingRows is _training_rows: staff trainings at a school, leaving out
// the in-school trainings a visit list already holds when asked.
func (k *cpoBook) trainingRows(skipCountedVisits bool) ([]cpoRow, error) {
	if !k.staffSide() {
		return nil, nil
	}
	b := &sql{}
	acts, err := readActivities(k.ctx, k.db, b, k.staffSet(b, "a.activity_type = ANY("+b.arg(rules.SchoolTrainingTypes)+") AND a.cluster_id IS NULL"), "''", "false")
	if err != nil {
		return nil, err
	}
	kept := acts[:0]
	for _, a := range acts {
		// visit_kind without a delivery: SSA Support is no staff kind then.
		if !skipCountedVisits || visitKind(a.activityType, a.purpose, a.project, "partner", k.snap.outside) == "" {
			kept = append(kept, a)
		}
	}
	return k.staffRows(kept, func(*cpoActivity) string { return "" }, "", false)
}

// otherRows is _other_rows: staff work at a school that is neither a
// counted visit, an outreach visit nor a training.
func (k *cpoBook) otherRows() ([]cpoRow, error) {
	if !k.staffSide() {
		return nil, nil
	}
	b := &sql{}
	set := `a.cluster_id IS NULL AND NOT COALESCE(` + b.countedVisit(k.snap.outside) + `, false) AND NOT COALESCE(` + b.outreachVisit() +
		`, false) AND NOT COALESCE(a.activity_type = ANY(` + b.arg(rules.SchoolTrainingTypes) + `), false) AND a.purpose_type IS DISTINCT FROM ` +
		b.arg(rules.CompanionPurpose)
	acts, err := readActivities(k.ctx, k.db, b, k.staffSet(b, set), "''", "false")
	if err != nil {
		return nil, err
	}
	return k.staffRows(acts, func(*cpoActivity) string { return "" }, "", false)
}

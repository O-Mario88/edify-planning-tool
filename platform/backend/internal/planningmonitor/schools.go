package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"strconv"
	"strings"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"
)

// School is one school's year (SchoolState).
type School struct {
	ID, Code, Name, Type, District    string
	ClusterID, ClusterName            string
	Clustered                         bool
	OfficerID, OfficerName            string
	LeadID, LeadName                  string
	StaffVisits, StaffSSAVisits       int
	StaffVisitsDone                   int
	PartnerVisits, PartnerVisitsDone  int
	PartnerVisitsUndated              int
	PartnerPending                    int
	GroupTraining, Meeting            bool
	InSchoolTraining, TrainingDone    bool
	InProject                         bool
	ProjectPlaces                     int
	CorePartnerVisits, CorePartnerTrn int
	CoreStaffTrainings                int
	SSADone                           bool
}

func (s *School) isCore() bool          { return isCore(s.Type) }
func (s *School) hasVisit() bool        { return s.StaffVisits > 0 || s.PartnerVisits > 0 }
func (s *School) hasPartner() bool      { return s.PartnerVisits > 0 || s.PartnerPending > 0 }
func (s *School) visitDone() bool       { return s.StaffVisitsDone > 0 || s.PartnerVisitsDone > 0 }
func (s *School) awaitingPartner() bool { return s.hasPartner() && !s.hasVisit() }
func (s *School) hasTraining() bool     { return s.GroupTraining || s.InSchoolTraining }
func (s *School) staffScheduled() bool  { return s.StaffVisits > 0 }
func (s *School) staffAndPartner() bool { return s.staffScheduled() && s.hasPartner() }
func (s *School) needsTraining() bool   { return takesTraining(s.Type) }

func (s *School) partnerVisitsAssigned() int { return s.PartnerVisits + s.PartnerVisitsUndated }

// coreVisitsOver is a Core school with more visits than its package takes.
func (s *School) coreVisitsOver() bool {
	return s.isCore() && (s.StaffVisits > rules.CoreStaffVisits || s.partnerVisitsAssigned() > rules.CorePartner)
}

// hasGap is SchoolState.has_gap.
func (s *School) hasGap(gap string) bool {
	switch gap {
	case "not_clustered":
		return !s.Clustered
	case "no_visit":
		return !s.hasVisit() && !s.hasPartner()
	case "no_training":
		return s.needsTraining() && !s.hasTraining()
	case "no_both":
		return !(s.hasVisit() || s.hasPartner() || s.hasTraining())
	case "staff_scheduled":
		return s.staffScheduled()
	case "staff_and_partner":
		return s.staffAndPartner()
	case "no_partner":
		return !s.isCore() && s.StaffVisits == 0 && !s.hasPartner()
	}
	return true
}

// sql numbers a statement's parameters and writes the rulebook's filters
// (apps.planning.country_oversight.rules) over the activity alias a.
type sql struct{ args []any }

func (b *sql) arg(v any) string {
	b.args = append(b.args, v)
	return "$" + strconv.Itoa(len(b.args))
}

// planned is planned_q and not deleted.
func (b *sql) planned() string {
	return fmt.Sprintf(`(a.deleted_at IS NULL AND a.status = ANY(%s) AND (a.planned_date IS NOT NULL OR a.scheduled_date IS NOT NULL))`,
		b.arg(rules.PlannedStates))
}

// notOutside is not_outside_ssa_q over the column given.
func (b *sql) notOutside(column string, outside []string) string {
	return fmt.Sprintf(`NOT COALESCE(%s = ANY(%s), false)`, column, b.arg(outside))
}

// ssaKind is _ssa_kind_q.
func (b *sql) ssaKind() string {
	kinds := make([]string, 0, len(rules.PurposeKinds))
	for k := range rules.PurposeKinds {
		kinds = append(kinds, k)
	}
	slices.Sort(kinds)
	return fmt.Sprintf(`(COALESCE(a.purpose_type = ANY(%s), false) OR (a.activity_type = ANY(%s) AND NOT COALESCE(a.purpose_type = ANY(%s), false)))`,
		b.arg(rules.DataCollectionPurposes), b.arg(rules.DataCollectionTypes), b.arg(kinds))
}

// countedVisit is counted_visit_q: a visit at a school that is not a
// companion, an outreach visit or outside the SSA, and (SSA Support) staff's.
func (b *sql) countedVisit(outside []string) string {
	return fmt.Sprintf(`(a.activity_type = ANY(%s) AND a.school_id IS NOT NULL AND a.cluster_id IS NULL
  AND a.purpose_type IS DISTINCT FROM %s AND NOT COALESCE(a.purpose_type = ANY(%s), false) AND %s
  AND (NOT %s OR a.delivery_type IS DISTINCT FROM 'partner'))`,
		b.arg(rules.VisitShapeTypes), b.arg(rules.CompanionPurpose), b.arg(rules.OutreachPurposes),
		b.notOutside("a.project_id", outside), b.ssaKind())
}

// partnerPlanned is partner_planned_q: Partner work the Partner dated.
func (b *sql) partnerPlanned() string {
	return fmt.Sprintf(`(a.delivery_type = 'partner' AND %s AND (a.partner_date_set_by = %s
  OR (a.partner_date_set_by = '' AND a.executor_type IS DISTINCT FROM %s)))`,
		b.planned(), b.arg(rules.DatedByPartner), b.arg(rules.CertifiedPartnerAgency))
}

// partnerHeld is partner_held_q: live Partner work, handed over or later.
func (b *sql) partnerHeld() string {
	return fmt.Sprintf(`(a.delivery_type = 'partner' AND a.status = ANY(%s))`,
		b.arg(append(slices.Clone(rules.PlannedStates), rules.AssignedToPartner)))
}

// staffOrPartnerPlanned is staff_delivery_q | partner_planned_q.
func (b *sql) staffOrPartnerPlanned() string {
	return "(a.delivery_type IS DISTINCT FROM 'partner' OR " + b.partnerPlanned() + ")"
}

// readSchools is _school_states: every operating school in base, monitored
// (the types the requirement asks a visit of) and outreach (the rest), each
// filed under its holder and the Lead the directory files them with.
func (m *monitor) readSchools(ctx context.Context, base string, baseArgs []any) error {
	rows, err := m.db.Query(ctx, `SELECT s.id, COALESCE(s.school_id, ''), s.name, COALESCE(s.school_type, ''), COALESCE(d.name, ''),
  COALESCE(s.cluster_id, ''), COALESCE(s.account_owner_id, '')
FROM school s LEFT JOIN district d ON d.id = s.district_id
WHERE `+base+` AND s.deleted_at IS NULL AND s.operational_status = ANY($`+strconv.Itoa(len(baseArgs)+1)+`)
ORDER BY s.name ASC`, append(slices.Clone(baseArgs), rules.OperatingStatuses)...)
	if err != nil {
		return fmt.Errorf("planningmonitor: the schools: %w", err)
	}
	type raw struct {
		s     *School
		owner string
	}
	var read []raw
	owners, clusters := []string{}, []string{}
	for rows.Next() {
		s := &School{}
		var owner string
		if err := rows.Scan(&s.ID, &s.Code, &s.Name, &s.Type, &s.District, &s.ClusterID, &owner); err != nil {
			rows.Close()
			return fmt.Errorf("planningmonitor: the schools: %w", err)
		}
		read = append(read, raw{s, owner})
		if owner != "" {
			owners = append(owners, owner)
		}
		if s.ClusterID != "" {
			clusters = append(clusters, s.ClusterID)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	directory, err := m.directory(ctx, owners)
	if err != nil {
		return err
	}
	names, active, err := m.clusters(ctx, clusters)
	if err != nil {
		return err
	}
	m.schools, m.outreach = map[string]*School{}, map[string]*School{}
	for _, r := range read {
		s := r.s
		s.ClusterName, s.Clustered = names[s.ClusterID], active[s.ClusterID]
		s.OfficerID, s.OfficerName = rules.Unassigned[0], rules.Unassigned[1]
		s.LeadID, s.LeadName = rules.NoLead[0], rules.NoLead[1]
		if o, ok := directory[r.owner]; ok {
			s.OfficerID, s.OfficerName, s.LeadID, s.LeadName = o.OfficerID, o.OfficerName, o.LeadID, o.LeadName
		}
		if monitored(s.Type) {
			m.schools[s.ID] = s
			m.schoolOrder = append(m.schoolOrder, s)
		} else {
			m.outreach[s.ID] = s
			m.outreachOrder = append(m.outreachOrder, s)
		}
	}
	if len(m.schools) > 0 {
		ids := m.monitoredIDs()
		for _, count := range []func(context.Context, []string) error{
			m.countActivities, m.countHandovers, m.countSessions, m.markProjects, m.countCorePackages, m.markSSA,
		} {
			if err := count(ctx, ids); err != nil {
				return err
			}
		}
	}
	if len(m.outreach) > 0 {
		ids := make([]string, 0, len(m.outreach))
		for id := range m.outreach {
			ids = append(ids, id)
		}
		if err := m.markProjectsIn(ctx, ids, m.outreach); err != nil {
			return err
		}
	}
	return nil
}

func (m *monitor) monitoredIDs() []string {
	ids := make([]string, 0, len(m.schools))
	for id := range m.schools {
		ids = append(ids, id)
	}
	return ids
}

// clusters is _cluster_names and _active_clusters: live clusters' names, and
// which of them are active.
func (m *monitor) clusters(ctx context.Context, ids []string) (map[string]string, map[string]bool, error) {
	names, active := map[string]string{}, map[string]bool{}
	if len(ids) == 0 {
		return names, active, nil
	}
	rows, err := m.db.Query(ctx, `SELECT id, name, COALESCE(status, '') FROM cluster WHERE id = ANY($1) AND deleted_at IS NULL`, ids)
	if err != nil {
		return nil, nil, fmt.Errorf("planningmonitor: the clusters: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id, name, status string
		if err := rows.Scan(&id, &name, &status); err != nil {
			return nil, nil, fmt.Errorf("planningmonitor: the clusters: %w", err)
		}
		names[id] = name
		if status == "active" {
			active[id] = true
		}
	}
	return names, active, rows.Err()
}

// countActivities is _count_activities: counted visits and in-school
// trainings at each school, planned and delivered, and the Partner work a
// Partner has not dated.
func (m *monitor) countActivities(ctx context.Context, ids []string) error {
	b := &sql{}
	at := fmt.Sprintf(`a.school_id = ANY(%s) AND a.fy = %s AND %s`, b.arg(ids), b.arg(m.fy), b.notOutside("a.project_id", m.outside))
	q := fmt.Sprintf(`SELECT a.school_id, COALESCE(a.delivery_type, ''), COALESCE(a.status, ''), count(*), count(*) FILTER (WHERE %s)
FROM activity a WHERE %s AND %s AND %s AND %s GROUP BY 1, 2, 3`,
		b.ssaKind(), at, b.planned(), b.countedVisit(m.outside), b.staffOrPartnerPlanned())
	if err := m.each(ctx, q, b.args, func(scan func(...any) error) error {
		var school, delivery, status string
		var n, ssa int
		if err := scan(&school, &delivery, &status, &n, &ssa); err != nil {
			return err
		}
		s := m.schools[school]
		if s == nil {
			return nil
		}
		done := slices.Contains(rules.DeliveredStatuses, status)
		if delivery == "partner" {
			s.PartnerVisits += n
			if done {
				s.PartnerVisitsDone += n
			}
			return nil
		}
		s.StaffVisits += n
		s.StaffSSAVisits += ssa
		if done {
			s.StaffVisitsDone += n
		}
		return nil
	}); err != nil {
		return err
	}
	b = &sql{}
	at = fmt.Sprintf(`a.school_id = ANY(%s) AND a.fy = %s AND %s`, b.arg(ids), b.arg(m.fy), b.notOutside("a.project_id", m.outside))
	q = fmt.Sprintf(`SELECT a.school_id, COALESCE(a.status, '') FROM activity a WHERE %s AND %s
AND a.activity_type = ANY(%s) AND a.cluster_id IS NULL AND %s`,
		at, b.planned(), b.arg(rules.SchoolTrainingTypes), b.staffOrPartnerPlanned())
	if err := m.each(ctx, q, b.args, func(scan func(...any) error) error {
		var school, status string
		if err := scan(&school, &status); err != nil {
			return err
		}
		if s := m.schools[school]; s != nil {
			s.InSchoolTraining = true
			if slices.Contains(rules.DeliveredStatuses, status) {
				s.TrainingDone = true
			}
		}
		return nil
	}); err != nil {
		return err
	}
	b = &sql{}
	at = fmt.Sprintf(`a.school_id = ANY(%s) AND a.fy = %s AND %s`, b.arg(ids), b.arg(m.fy), b.notOutside("a.project_id", m.outside))
	q = fmt.Sprintf(`SELECT a.school_id, count(*), count(*) FILTER (WHERE %s) FROM activity a
WHERE %s AND a.deleted_at IS NULL AND %s AND NOT COALESCE(%s, false) GROUP BY 1`,
		b.countedVisit(m.outside), at, b.partnerHeld(), b.partnerPlanned())
	return m.each(ctx, q, b.args, func(scan func(...any) error) error {
		var school string
		var n, visits int
		if err := scan(&school, &n, &visits); err != nil {
			return err
		}
		if s := m.schools[school]; s != nil {
			s.PartnerPending += n
			s.PartnerVisitsUndated += visits
		}
		return nil
	})
}

// countHandovers is _count_partner_handovers: hand-overs a Partner has not
// dated yet.
func (m *monitor) countHandovers(ctx context.Context, ids []string) error {
	b := &sql{}
	q := fmt.Sprintf(`SELECT h.school_id, count(*) FROM partner_assignment h WHERE h.school_id = ANY(%s)
AND h.status = ANY(%s) AND %s GROUP BY 1`, b.arg(ids), b.arg(rules.UnscheduledHandoverStatuses), b.notOutside("h.project_id", m.outside))
	return m.each(ctx, q, b.args, func(scan func(...any) error) error {
		var school string
		var n int
		if err := scan(&school, &n); err != nil {
			return err
		}
		if s := m.schools[school]; s != nil {
			s.PartnerPending += n
		}
		return nil
	})
}

// countSessions is _count_cluster_sessions: the group trainings and cluster
// meetings each school is invited to by name.
func (m *monitor) countSessions(ctx context.Context, ids []string) error {
	b := &sql{}
	q := fmt.Sprintf(`SELECT t.school_id, a.activity_type, COALESCE(a.status, ''), COALESCE(t.attended, false)
FROM cluster_activity_attendance t JOIN activity a ON a.id = t.activity_id
WHERE t.school_id = ANY(%s) AND a.fy = %s AND a.cluster_id IS NOT NULL AND %s
AND (a.activity_type = ANY(%s) OR a.activity_type = ANY(%s)) AND (t.invited OR t.attended)`,
		b.arg(ids), b.arg(m.fy), b.planned(), b.arg(rules.ClusterMeetingTypes), b.arg(rules.TrainingTypes))
	return m.each(ctx, q, b.args, func(scan func(...any) error) error {
		var school, kind, status string
		var attended bool
		if err := scan(&school, &kind, &status, &attended); err != nil {
			return err
		}
		s := m.schools[school]
		if s == nil {
			return nil
		}
		if slices.Contains(rules.ClusterMeetingTypes, kind) {
			s.Meeting = true
			return nil
		}
		s.GroupTraining = true
		if attended && slices.Contains(rules.DeliveredStatuses, status) {
			s.TrainingDone = true
		}
		return nil
	})
}

func (m *monitor) markProjects(ctx context.Context, ids []string) error {
	return m.markProjectsIn(ctx, ids, m.schools)
}

// markProjectsIn is _mark_projects: schools enrolled in an open project.
func (m *monitor) markProjectsIn(ctx context.Context, ids []string, in map[string]*School) error {
	q := `SELECT DISTINCT e.school_id FROM project_school_assignment e JOIN project p ON p.id = e.project_id
WHERE e.school_id = ANY($1) AND p.deleted_at IS NULL AND p.status = ANY($2)`
	return m.each(ctx, q, []any{ids, rules.OpenProjectStatuses}, func(scan func(...any) error) error {
		var school string
		if err := scan(&school); err != nil {
			return err
		}
		if s := in[school]; s != nil {
			s.InProject = true
		}
		return nil
	})
}

// markSSA is _mark_ssa: schools with a confirmed SSA of the year.
func (m *monitor) markSSA(ctx context.Context, ids []string) error {
	q := `SELECT DISTINCT school_id FROM ssa_record WHERE school_id = ANY($1) AND fy = $2 AND deleted_at IS NULL
AND verification_status = ANY($3)`
	return m.each(ctx, q, []any{ids, m.fy, rules.CurrentSSAStatuses}, func(scan func(...any) error) error {
		var school string
		if err := scan(&school); err != nil {
			return err
		}
		if s := m.schools[school]; s != nil {
			s.SSADone = true
		}
		return nil
	})
}

// countCorePackages is _count_core_packages: the Partner's half, and the
// staff half's trainings, of each Core school's package, each to the two it
// takes.
func (m *monitor) countCorePackages(ctx context.Context, _ []string) error {
	gate := schoolprofile.GateRules()
	for _, s := range m.schoolOrder {
		if !s.isCore() || s.Code == "" {
			continue
		}
		split, err := visitgate.SplitOf(ctx, m.db, gate, visitgate.School{ID: s.ID, Code: s.Code, Name: s.Name, Type: s.Type}, m.fy, m.operational)
		if err != nil {
			return err
		}
		s.CorePartnerVisits = min(split.PartnerHeldVisits(), rules.CorePartner)
		s.CorePartnerTrn = min(split.PartnerHeldTrainings(), rules.CorePartner)
		s.CoreStaffTrainings = min(split.StaffTrainings, rules.CoreStaffVisits)
	}
	return nil
}

// each runs q and hands each row's scan to read.
func (m *monitor) each(ctx context.Context, q string, args []any, read func(scan func(...any) error) error) error {
	rows, err := m.db.Query(ctx, q, args...)
	if err != nil {
		return fmt.Errorf("planningmonitor: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		if err := read(rows.Scan); err != nil {
			return fmt.Errorf("planningmonitor: %w", err)
		}
	}
	return rows.Err()
}

// pyTitle is str.title() after "_" became " ".
func pyTitle(value string) string {
	words := strings.Fields(strings.ReplaceAll(value, "_", " "))
	for i, w := range words {
		words[i] = strings.ToUpper(w[:1]) + strings.ToLower(w[1:])
	}
	return strings.Join(words, " ")
}

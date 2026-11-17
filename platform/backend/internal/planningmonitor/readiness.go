package planningmonitor

import (
	"context"
	"fmt"
	"slices"
	"sort"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Planned and remaining (apps.planning.readiness): one person's year in four
// parts — visits, trainings, Partner assignment, project assignment — and
// one score, read from the monitor's own rows, and a team's or the total's
// as the sum of their people's.

// Line is a target, what is planned against it, and how much of that is
// credited (no further than each person's own target).
type Line struct{ Target, Planned, Credited int }

func (l Line) remaining() int { return max(0, l.Target-l.Credited) }
func (l Line) over() int      { return max(0, l.Planned-l.Credited) }

// percent is _share: whole percent rounded down, 100 for nothing to reach.
func (l Line) percent() int {
	if l.Target <= 0 {
		return 100
	}
	return max(0, min(100, l.Credited*100/l.Target))
}

func (l Line) required() bool { return l.Target > 0 }

func (l Line) tone() string {
	switch {
	case !l.required():
		return "neutral"
	case l.remaining() == 0:
		return "success"
	case l.percent() >= 50:
		return "info"
	}
	return "warning"
}

// TypeInventory is one school type's schools, each in one of three states.
type TypeInventory struct {
	Key, Label                         string
	Total, Fully, Partly, NotYet, InPj int
}

// Readiness is one person's figures, or the sum of several people's.
type Readiness struct {
	People, Ceiling                                                    int
	StaffVisitTarget, StaffVisitsPlanned, StaffVisitsCredited          int
	PartnerVisitTarget, PartnerVisitsPlanned, PartnerVisitsCredited    int
	PartnerVisitsAwaiting                                              int
	StaffTrainingTarget, StaffTrainingsPlanned, StaffTrainingsCredited int
	PartnerTrainingTarget, PartnerTrainingsPlanned                     int
	PartnerTrainingsCredited                                           int
	PartnerRequired, PartnerAssigned, PartnerCredited                  int
	PartnerCoreSchools, PartnerBeyondStaff                             int
	PortfolioVisits, SchoolsToRecruit, ShortPeople                     int
	SchoolsStaffScheduled, SchoolsStaffAndPartner                      int
	ClientStaffAndPartner, CoreVisitsOver                              int
	ProjectTotal, ProjectAssigned                                      int
	ProjectCeiling, ProjectAdded, ProjectCredited                      int
	Duplicates, OverCeilingPeople, OverCeilingVisits                   int
	CoreMissingPartnerHalf                                             int
	Inventory                                                          map[string]*TypeInventory
}

func (r Readiness) StaffVisits() Line {
	return Line{r.StaffVisitTarget, r.StaffVisitsPlanned, r.StaffVisitsCredited}
}
func (r Readiness) PartnerVisits() Line {
	return Line{r.PartnerVisitTarget, r.PartnerVisitsPlanned, r.PartnerVisitsCredited}
}
func (r Readiness) StaffTrainings() Line {
	return Line{r.StaffTrainingTarget, r.StaffTrainingsPlanned, r.StaffTrainingsCredited}
}
func (r Readiness) PartnerTrainings() Line {
	return Line{r.PartnerTrainingTarget, r.PartnerTrainingsPlanned, r.PartnerTrainingsCredited}
}
func (r Readiness) PartnerAssignment() Line {
	return Line{r.PartnerRequired, r.PartnerAssigned, r.PartnerCredited}
}
func (r Readiness) ProjectAssignment() Line {
	return Line{r.ProjectCeiling, r.ProjectAdded, r.ProjectCredited}
}

// applicable is whether there is anything to be ready with.
func (r Readiness) applicable() bool {
	return r.StaffTrainingTarget > 0 || r.PartnerRequired > 0 || r.ProjectTotal > 0 || r.ProjectCeiling > 0
}

// score is the plain average of the four parts, rounded down.
func (r Readiness) score() int {
	parts := []Line{r.StaffVisits(), r.StaffTrainings(), r.PartnerAssignment(), r.ProjectAssignment()}
	n := 0
	for _, p := range parts {
		n += p.percent()
	}
	return n / len(parts)
}

// types are the inventory in the rulebook's order, then any other type.
func (r Readiness) types() []*TypeInventory {
	var known, other []*TypeInventory
	for _, key := range rules.TypeOrder {
		if row, ok := r.Inventory[key]; ok {
			known = append(known, row)
		}
	}
	for key, row := range r.Inventory {
		if !slices.Contains(rules.TypeOrder, key) {
			other = append(other, row)
		}
	}
	sort.Slice(other, func(i, j int) bool { return other[i].Key < other[j].Key })
	return append(known, other...)
}

func (r Readiness) schools(of func(*TypeInventory) int) int {
	n := 0
	for _, row := range r.Inventory {
		n += of(row)
	}
	return n
}

// add is Readiness.__add__.
func (r Readiness) add(o Readiness) Readiness {
	t := Readiness{
		People: r.People + o.People, Ceiling: r.Ceiling + o.Ceiling,
		StaffVisitTarget: r.StaffVisitTarget + o.StaffVisitTarget, StaffVisitsPlanned: r.StaffVisitsPlanned + o.StaffVisitsPlanned,
		StaffVisitsCredited: r.StaffVisitsCredited + o.StaffVisitsCredited,
		PartnerVisitTarget:  r.PartnerVisitTarget + o.PartnerVisitTarget, PartnerVisitsPlanned: r.PartnerVisitsPlanned + o.PartnerVisitsPlanned,
		PartnerVisitsCredited: r.PartnerVisitsCredited + o.PartnerVisitsCredited,
		PartnerVisitsAwaiting: r.PartnerVisitsAwaiting + o.PartnerVisitsAwaiting,
		StaffTrainingTarget:   r.StaffTrainingTarget + o.StaffTrainingTarget, StaffTrainingsPlanned: r.StaffTrainingsPlanned + o.StaffTrainingsPlanned,
		StaffTrainingsCredited:   r.StaffTrainingsCredited + o.StaffTrainingsCredited,
		PartnerTrainingTarget:    r.PartnerTrainingTarget + o.PartnerTrainingTarget,
		PartnerTrainingsPlanned:  r.PartnerTrainingsPlanned + o.PartnerTrainingsPlanned,
		PartnerTrainingsCredited: r.PartnerTrainingsCredited + o.PartnerTrainingsCredited,
		PartnerRequired:          r.PartnerRequired + o.PartnerRequired, PartnerAssigned: r.PartnerAssigned + o.PartnerAssigned,
		PartnerCredited: r.PartnerCredited + o.PartnerCredited, PartnerCoreSchools: r.PartnerCoreSchools + o.PartnerCoreSchools,
		PartnerBeyondStaff: r.PartnerBeyondStaff + o.PartnerBeyondStaff, PortfolioVisits: r.PortfolioVisits + o.PortfolioVisits,
		SchoolsToRecruit: r.SchoolsToRecruit + o.SchoolsToRecruit, ShortPeople: r.ShortPeople + o.ShortPeople,
		SchoolsStaffScheduled:  r.SchoolsStaffScheduled + o.SchoolsStaffScheduled,
		SchoolsStaffAndPartner: r.SchoolsStaffAndPartner + o.SchoolsStaffAndPartner,
		ClientStaffAndPartner:  r.ClientStaffAndPartner + o.ClientStaffAndPartner, CoreVisitsOver: r.CoreVisitsOver + o.CoreVisitsOver,
		ProjectTotal: r.ProjectTotal + o.ProjectTotal, ProjectAssigned: r.ProjectAssigned + o.ProjectAssigned,
		ProjectCeiling: r.ProjectCeiling + o.ProjectCeiling, ProjectAdded: r.ProjectAdded + o.ProjectAdded,
		ProjectCredited: r.ProjectCredited + o.ProjectCredited, Duplicates: r.Duplicates + o.Duplicates,
		OverCeilingPeople: r.OverCeilingPeople + o.OverCeilingPeople, OverCeilingVisits: r.OverCeilingVisits + o.OverCeilingVisits,
		CoreMissingPartnerHalf: r.CoreMissingPartnerHalf + o.CoreMissingPartnerHalf,
		Inventory:              map[string]*TypeInventory{},
	}
	for _, source := range []Readiness{r, o} {
		for key, row := range source.Inventory {
			mine := t.Inventory[key]
			if mine == nil {
				mine = &TypeInventory{Key: key, Label: row.Label}
				t.Inventory[key] = mine
			}
			mine.Total += row.Total
			mine.Fully += row.Fully
			mine.Partly += row.Partly
			mine.NotYet += row.NotYet
			mine.InPj += row.InPj
		}
	}
	return t
}

// schoolState is readiness.school_state: fully, partly or not yet planned.
func schoolState(s *School) string {
	n := need(s.Type)
	if n.visits() == 0 && n.trainings() == 0 {
		return "fully"
	}
	if s.isCore() {
		c := need("core")
		held := min(s.StaffVisits, c.StaffVisits) + min(s.CorePartnerVisits, c.PartnerVisits) +
			min(s.CoreStaffTrainings, c.StaffTrainings) + min(s.CorePartnerTrn, c.PartnerTrainings)
		if held >= c.visits()+c.trainings() {
			return "fully"
		}
		if held > 0 || s.hasPartner() || s.hasTraining() {
			return "partly"
		}
		return "not_yet"
	}
	visit := s.StaffVisits > 0 || s.hasPartner()
	switch {
	case visit && s.hasTraining():
		return "fully"
	case visit || s.hasTraining():
		return "partly"
	}
	return "not_yet"
}

// isDuplicate is readiness.is_duplicate: a Client-rule school booked twice.
func isDuplicate(s *School) bool {
	if s.isCore() {
		return false
	}
	ssa := s.StaffSSAVisits
	return s.StaffVisits-ssa > 1 || ssa > 1 || s.PartnerVisits > 1 || (s.StaffVisits > 0 && s.hasPartner())
}

// coreMissingPartnerHalf is readiness.core_missing_partner_half.
func coreMissingPartnerHalf(s *School) bool {
	c := need("core")
	return s.isCore() && (s.CorePartnerVisits < c.PartnerVisits || s.CorePartnerTrn < c.PartnerTrainings)
}

// Readiness is person_readiness: one person's figures.
func (o *Officer) Readiness() Readiness {
	var core, client []*School
	for _, s := range o.Schools {
		if s.isCore() {
			core = append(core, s)
		} else {
			client = append(client, s)
		}
	}
	c := need("core")
	w := workload{cap: max(0, o.VisitsTarget), core: len(core), client: len(client)}
	partnerClient := w.partnerClientVisits()
	partnerTarget := w.partnerCoreVisits() + partnerClient
	partnerVisits := 0
	for _, s := range core {
		partnerVisits += min(s.PartnerVisits, c.PartnerVisits)
	}
	for _, s := range client {
		partnerVisits += min(s.PartnerVisits, 1)
	}
	trainingTarget := o.count((*School).needsTraining)
	trainings := o.count(func(s *School) bool { return s.needsTraining() && s.hasTraining() })
	partnerTrainings := 0
	coreAssigned, clientAssigned, missingHalf := 0, 0, 0
	for _, s := range core {
		partnerTrainings += s.CorePartnerTrn
		if s.CorePartnerVisits > 0 || s.CorePartnerTrn > 0 || s.hasPartner() {
			coreAssigned++
		}
		if coreMissingPartnerHalf(s) {
			missingHalf++
		}
	}
	duplicates := 0
	for _, s := range client {
		if s.hasPartner() {
			clientAssigned++
		}
		if isDuplicate(s) {
			duplicates++
		}
	}
	held := append(slices.Clone(o.Schools), o.Outreach...)
	inventory := map[string]*TypeInventory{}
	inProject := 0
	for _, s := range held {
		row := inventory[s.Type]
		if row == nil {
			row = &TypeInventory{Key: s.Type, Label: typeLabel(s.Type)}
			inventory[s.Type] = row
		}
		row.Total++
		switch schoolState(s) {
		case "fully":
			row.Fully++
		case "partly":
			row.Partly++
		default:
			row.NotYet++
		}
		if s.InProject {
			row.InPj++
			inProject++
		}
	}
	awaiting := o.count(func(s *School) bool { return s.PartnerPending > 0 && s.PartnerVisits == 0 })
	staff := o.staffVisits()
	return Readiness{
		People: 1, Ceiling: max(0, o.VisitsTarget),
		StaffVisitTarget: max(0, o.VisitsTarget), StaffVisitsPlanned: staff, StaffVisitsCredited: min(staff, max(0, o.VisitsTarget)),
		PartnerVisitTarget: partnerTarget, PartnerVisitsPlanned: partnerVisits, PartnerVisitsCredited: min(partnerVisits, partnerTarget),
		PartnerVisitsAwaiting: awaiting,
		StaffTrainingTarget:   trainingTarget, StaffTrainingsPlanned: trainings, StaffTrainingsCredited: min(trainings, trainingTarget),
		PartnerTrainingTarget: w.partnerCoreTrainings(), PartnerTrainingsPlanned: partnerTrainings,
		PartnerTrainingsCredited: min(partnerTrainings, w.partnerCoreTrainings()),
		PartnerRequired:          len(core) + partnerClient, PartnerAssigned: coreAssigned + clientAssigned,
		PartnerCredited: coreAssigned + min(clientAssigned, partnerClient), PartnerCoreSchools: len(core),
		PartnerBeyondStaff: partnerClient, PortfolioVisits: w.portfolioVisits(), SchoolsToRecruit: w.shortOfTarget(),
		ShortPeople: boolInt(w.shortOfTarget() > 0), SchoolsStaffScheduled: o.count((*School).staffScheduled),
		SchoolsStaffAndPartner: o.count((*School).staffAndPartner),
		ClientStaffAndPartner:  o.count(func(s *School) bool { return !s.isCore() && s.staffAndPartner() }),
		CoreVisitsOver:         o.count((*School).coreVisitsOver),
		ProjectTotal:           len(held), ProjectAssigned: inProject,
		ProjectCeiling: o.ProjectCeiling, ProjectAdded: o.ProjectAdded, ProjectCredited: min(o.ProjectAdded, o.ProjectCeiling),
		Duplicates: duplicates, OverCeilingPeople: boolInt(o.overCeiling() > 0), OverCeilingVisits: o.overCeiling(),
		CoreMissingPartnerHalf: missingHalf, Inventory: inventory,
	}
}

// Readiness is the team's figures: its people's added up.
func (l *Lead) Readiness() Readiness {
	t := Readiness{Inventory: map[string]*TypeInventory{}}
	for _, o := range l.Officers {
		t = t.add(o.Readiness())
	}
	return t
}

// Readiness is everyone's figures (for_monitor's total).
func (m *Monitor) Readiness() Readiness {
	t := Readiness{Inventory: map[string]*TypeInventory{}}
	for _, o := range m.Officers() {
		t = t.add(o.Readiness())
	}
	return t
}

// AsDict is Readiness.as_dict: the figures as plain data.
func (r Readiness) AsDict() map[string]any {
	line := func(l Line) map[string]any {
		return map[string]any{"target": l.Target, "planned": l.Planned, "remaining": l.remaining(), "over": l.over(), "percent": l.percent()}
	}
	with := func(base map[string]any, extra map[string]any) map[string]any {
		for k, v := range extra {
			base[k] = v
		}
		return base
	}
	var overall any
	if r.applicable() {
		overall = r.score()
	}
	byType := []any{}
	for _, row := range r.types() {
		byType = append(byType, map[string]any{"type": row.Key, "label": row.Label, "total": row.Total,
			"fully_planned": row.Fully, "partly_planned": row.Partly, "not_yet_planned": row.NotYet, "in_project": row.InPj})
	}
	return map[string]any{
		"rules_version": rules.RulesVersion,
		"ceiling":       r.Ceiling,
		"visits": map[string]any{
			"staff":                      line(r.StaffVisits()),
			"schools_held_can_take":      r.PortfolioVisits,
			"schools_to_recruit":         r.SchoolsToRecruit,
			"schools_scheduled_by_staff": r.SchoolsStaffScheduled,
			"schools_scheduled_by_staff_and_with_partner":        r.SchoolsStaffAndPartner,
			"client_schools_scheduled_by_staff_and_with_partner": r.ClientStaffAndPartner,
			"core_schools_past_two_staff_or_two_partner_visits":  r.CoreVisitsOver,
			"partner":       with(line(r.PartnerVisits()), map[string]any{"awaiting_partner_date": r.PartnerVisitsAwaiting}),
			"net_remaining": r.StaffVisits().remaining() + r.PartnerVisits().remaining(),
		},
		"trainings": map[string]any{"schools": line(r.StaffTrainings()), "partner_core_package": line(r.PartnerTrainings())},
		"partner_assignment": with(line(r.PartnerAssignment()),
			map[string]any{"core_schools": r.PartnerCoreSchools, "beyond_staff_capacity": r.PartnerBeyondStaff}),
		"project_assignment": with(line(r.ProjectAssignment()),
			map[string]any{"schools_held": r.ProjectTotal, "schools_held_in_a_project": r.ProjectAssigned}),
		"completion": map[string]any{
			"visits": r.StaffVisits().percent(), "trainings": r.StaffTrainings().percent(),
			"partner_assignment": r.PartnerAssignment().percent(), "project_assignment": r.ProjectAssignment().percent(),
			"overall": overall,
		},
		"schools": map[string]any{
			"total":           r.schools(func(t *TypeInventory) int { return t.Total }),
			"fully_planned":   r.schools(func(t *TypeInventory) int { return t.Fully }),
			"partly_planned":  r.schools(func(t *TypeInventory) int { return t.Partly }),
			"not_yet_planned": r.schools(func(t *TypeInventory) int { return t.NotYet }),
			"by_type":         byType,
		},
		"flags": map[string]any{
			"duplicate_bookings": r.Duplicates, "staff_past_ceiling": r.OverCeilingPeople,
			"visits_past_ceiling": r.OverCeilingVisits, "core_missing_partner_half": r.CoreMissingPartnerHalf,
		},
	}
}

// SchoolChecks are a school's state and two checks by the existing names.
func (s *School) SchoolChecks() map[string]any {
	return map[string]any{"state": schoolState(s), "duplicate": isDuplicate(s), "core_missing_partner_half": coreMissingPartnerHalf(s)}
}

// Ledger is readiness.ledger for a team: every planned activity of the year
// of the monitor's people and schools, each in one line.
func (m *Monitor) Ledger(ctx context.Context, db schooldirectory.Querier) (map[string]any, error) {
	officers := m.Officers()
	people := map[string]bool{}
	var ids []string
	for _, o := range officers {
		for _, id := range o.IDs {
			people[id] = true
			ids = append(ids, id)
		}
	}
	schools, counted := map[string]bool{}, map[string]bool{}
	var schoolIDs []string
	for _, o := range officers {
		for _, s := range o.Schools {
			schools[s.ID], counted[s.ID] = true, true
			schoolIDs = append(schoolIDs, s.ID)
		}
		for _, s := range o.Outreach {
			schools[s.ID] = true
			schoolIDs = append(schoolIDs, s.ID)
		}
	}
	if ids == nil {
		ids = []string{}
	}
	if schoolIDs == nil {
		schoolIDs = []string{}
	}
	outside := m.outside
	b := &sql{}
	q := fmt.Sprintf(`SELECT COALESCE(a.activity_type, ''), COALESCE(a.purpose_type, ''), COALESCE(a.delivery_type, ''),
  COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.responsible_staff_id, ''), COALESCE(a.project_id, '')
FROM activity a WHERE a.fy = %s AND %s`, b.arg(m.FY), b.planned())
	if !m.wholeCountry {
		q += fmt.Sprintf(` AND (a.responsible_staff_id = ANY(%s) OR a.school_id = ANY(%s))`, b.arg(ids), b.arg(schoolIDs))
	}
	counts := map[string]int{}
	rows, err := db.Query(ctx, q, b.args...)
	if err != nil {
		return nil, fmt.Errorf("planningmonitor: the ledger: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var r ledgerRow
		if err := rows.Scan(&r.kind, &r.purpose, &r.delivery, &r.school, &r.cluster, &r.responsible, &r.project); err != nil {
			return nil, fmt.Errorf("planningmonitor: the ledger: %w", err)
		}
		counts[r.key(people, schools, counted, outside)]++
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	total, unaccounted := 0, 0
	lines := []any{}
	for _, l := range rules.Ledger {
		key, label := fmt.Sprint(l[0]), fmt.Sprint(l[1])
		flagged, _ := l[2].(bool)
		total += counts[key]
		if flagged {
			unaccounted += counts[key]
		}
		if counts[key] > 0 || flagged {
			lines = append(lines, map[string]any{"key": key, "label": label, "count": counts[key], "flagged": flagged})
		}
	}
	return map[string]any{"total": total, "lines": lines, "unaccounted": unaccounted, "staff_visits": counts["staff_visit"]}, nil
}

type ledgerRow struct{ kind, purpose, delivery, school, cluster, responsible, project string }

// visitKind is rules.visit_kind: the counted kind of a visit, or "".
func visitKind(kind, purpose, project, delivery string, outside []string) string {
	if !slices.Contains(rules.VisitShapeTypes, kind) {
		return ""
	}
	if project != "" && slices.Contains(outside, project) {
		return ""
	}
	if purpose == rules.CompanionPurpose || slices.Contains(rules.OutreachPurposes, purpose) {
		return ""
	}
	k, ok := rules.PurposeKinds[purpose]
	if !ok {
		if slices.Contains(rules.DataCollectionPurposes, purpose) {
			k = rules.KindSSA
		} else if t, ok := rules.TypeKinds[kind]; ok {
			k = t
		} else {
			k = rules.KindSSA
		}
	}
	if k == rules.KindSSA && delivery == "partner" {
		return ""
	}
	return k
}

// key is _ledger_key: where one planned activity goes.
func (r ledgerRow) key(people, schools, counted map[string]bool, outside []string) string {
	if r.cluster != "" {
		return "cluster"
	}
	if r.purpose == rules.CompanionPurpose {
		return "companion"
	}
	delivery := r.delivery
	if delivery == "" {
		delivery = "staff"
	}
	shaped := r.school != "" && slices.Contains(rules.VisitShapeTypes, r.kind)
	kind := visitKind(r.kind, r.purpose, r.project, delivery, outside)
	switch {
	case shaped && kind != "" && delivery == "partner":
		if counted[r.school] {
			return "partner_visit"
		}
		if schools[r.school] {
			return "partner_no_visit_school"
		}
		return "off_schools"
	case shaped && kind != "":
		if people[r.responsible] {
			return "staff_visit"
		}
		return "off_roster"
	case slices.Contains(rules.DataCollectionTypes, r.kind) || slices.Contains(rules.DataCollectionPurposes, r.purpose):
		return "data_collection"
	case isUncountedVisit(r.kind, r.purpose, delivery, outside):
		return "outreach"
	case shaped && r.project != "" && slices.Contains(outside, r.project):
		return "outside_ssa"
	case slices.Contains(rules.SchoolTrainingTypes, r.kind):
		return "training"
	}
	return "other"
}

// isUncountedVisit is rules.is_uncounted_visit.
func isUncountedVisit(kind, purpose, delivery string, outside []string) bool {
	if slices.Contains(rules.OutreachTypes, kind) {
		return true
	}
	if !slices.Contains(rules.VisitShapeTypes, kind) {
		return false
	}
	if slices.Contains(rules.OutreachPurposes, purpose) {
		return true
	}
	if purpose == rules.CompanionPurpose {
		return false
	}
	return visitKind(kind, purpose, "", "staff", outside) == rules.KindSSA && delivery == "partner"
}

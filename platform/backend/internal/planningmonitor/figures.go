package planningmonitor

import "math"

// A person's figures (OfficerMonitor's properties), each folded from their
// schools, and a team's (LeadMonitor), each the sum of its people's but for
// its own progress and tones.

// percentage is apps.core.metrics.percentage: round(n / d * 100), nil for
// nothing to be a percentage of.
func percentage(n, d int) *int {
	if d == 0 {
		return nil
	}
	v := int(math.RoundToEven(float64(n) / float64(d) * 100))
	return &v
}

// tone is _tone over a progress.
func tone(progress *int) string {
	switch {
	case progress == nil:
		return "neutral"
	case *progress >= 100:
		return "success"
	case *progress >= 50:
		return "info"
	}
	return "warning"
}

// shareTone is _share_tone: a count against what it should reach.
func shareTone(part, whole int) string {
	if whole == 0 {
		return "neutral"
	}
	if part >= whole {
		return "success"
	}
	return "warning"
}

func (o *Officer) count(keep func(*School) bool) int {
	n := 0
	for _, s := range o.Schools {
		if keep(s) {
			n++
		}
	}
	return n
}

func (o *Officer) sum(of func(*School) int) int {
	n := 0
	for _, s := range o.Schools {
		n += of(s)
	}
	return n
}

// workload is rules.workload over the person's target and schools.
type workload struct{ cap, core, client int }

func (w workload) staffCoreVisits() int      { return need("core").StaffVisits * w.core }
func (w workload) partnerCoreVisits() int    { return need("core").PartnerVisits * w.core }
func (w workload) partnerCoreTrainings() int { return need("core").PartnerTrainings * w.core }
func (w workload) remainingCapacity() int    { return max(0, w.cap-w.staffCoreVisits()) }
func (w workload) staffClientVisits() int    { return min(w.client, w.remainingCapacity()) }
func (w workload) partnerClientVisits() int  { return w.client - w.staffClientVisits() }
func (w workload) portfolioVisits() int      { return w.staffCoreVisits() + w.client }
func (w workload) shortOfTarget() int        { return max(0, w.cap-w.portfolioVisits()) }
func (w workload) coreOnly() bool {
	return w.cap > 0 && w.core > 0 && w.staffCoreVisits() >= w.cap
}

func (o *Officer) workload() workload {
	return workload{cap: max(0, o.VisitsTarget), core: max(0, o.coreSchools()), client: max(0, o.clientSchools())}
}

func (o *Officer) schoolCount() int   { return len(o.Schools) }
func (o *Officer) coreSchools() int   { return o.count((*School).isCore) }
func (o *Officer) clientSchools() int { return o.schoolCount() - o.coreSchools() }
func (o *Officer) coreVisitTarget() int {
	return min(rules.CoreStaffVisits*o.coreSchools(), o.VisitsTarget)
}
func (o *Officer) clientVisitTarget() int { return max(0, o.VisitsTarget-o.coreVisitTarget()) }
func (o *Officer) staffVisits() int       { return o.PlannedCore + o.PlannedClient }

// overCeiling is rules.over_ceiling: counted visits planned past the target.
func (o *Officer) overCeiling() int {
	if o.VisitsTarget == 0 {
		return 0
	}
	return max(0, o.staffVisits()-o.VisitsTarget)
}

func (o *Officer) partnerNeeded() int { return max(0, o.clientSchools()-o.clientVisitTarget()) }
func (o *Officer) partnerSchools() int {
	return o.count(func(s *School) bool { return !s.isCore() && s.hasPartner() })
}
func (o *Officer) corePartnerTarget() int { return rules.CorePartner * o.coreSchools() }

// figures are the person's figures by the existing service's names.
func (o *Officer) figures() map[string]any {
	visitProgress := percentage(o.staffVisits(), o.VisitsTarget)
	w := o.workload()
	partnerTone := "neutral"
	if o.partnerNeeded() > 0 {
		partnerTone = "warning"
		if max(0, o.partnerNeeded()-o.partnerSchools()) == 0 {
			partnerTone = "success"
		}
	}
	corePartnerVisits := o.sum(func(s *School) int {
		if s.isCore() {
			return s.CorePartnerVisits
		}
		return 0
	})
	corePartnerTrainings := o.sum(func(s *School) int {
		if s.isCore() {
			return s.CorePartnerTrn
		}
		return 0
	})
	coreStaffTrainings := o.sum(func(s *School) int {
		if s.isCore() {
			return s.CoreStaffTrainings
		}
		return 0
	})
	visitTone := tone(visitProgress)
	if o.overCeiling() > 0 {
		visitTone = "danger"
	}
	schoolsWithVisit := o.count((*School).hasVisit)
	awaiting := o.count((*School).awaitingPartner)
	trainingSchools := o.count((*School).needsTraining)
	withTraining := o.count(func(s *School) bool { return s.needsTraining() && s.hasTraining() })
	short := 0
	if w.shortOfTarget() > 0 {
		short = 1
	}
	return map[string]any{
		"key": o.Key, "name": o.Name, "role": o.Role, "visits_target": o.VisitsTarget,
		"is_lead": o.Role == rules.RoleCodes[rules.ProgramLeadRole], "role_label": rules.RoleLabels[o.Role],
		"planned_core": o.PlannedCore, "planned_client": o.PlannedClient, "planned_done": o.PlannedDone,
		"partner_assigned_schools": o.PartnerAssignedSchools, "partner_scheduled": o.PartnerScheduled,
		"partner_delivered": o.PartnerDelivered, "partner_awaiting": o.PartnerAwaiting,
		"project_ceiling": o.ProjectCeiling, "project_added": o.ProjectAdded,
		"school_count": o.schoolCount(), "core_schools": o.coreSchools(), "client_schools": o.clientSchools(),
		"outreach_count":    len(o.Outreach),
		"core_visit_target": o.coreVisitTarget(), "client_visit_target": o.clientVisitTarget(),
		"core_visits": o.PlannedCore, "client_visits": o.PlannedClient, "staff_visits": o.staffVisits(),
		"visits_done": o.PlannedDone, "visit_progress": visitProgress,
		"delivery_progress": percentage(o.PlannedDone, o.staffVisits()),
		"over_ceiling":      o.overCeiling(), "over_ceiling_people": boolInt(o.overCeiling() > 0),
		"core_only_people": boolInt(workload{cap: o.VisitsTarget, core: o.coreSchools()}.coreOnly()),
		"portfolio_visits": w.portfolioVisits(), "schools_to_recruit": w.shortOfTarget(), "short_people": short,
		"partner_needed": o.partnerNeeded(), "partner_schools": o.partnerSchools(),
		"partner_remaining": max(0, o.partnerNeeded()-o.partnerSchools()), "partner_tone": partnerTone,
		"core_partner_target": o.corePartnerTarget(), "core_partner_visits": corePartnerVisits,
		"core_partner_trainings":      corePartnerTrainings,
		"core_partner_visits_tone":    shareTone(corePartnerVisits, o.corePartnerTarget()),
		"core_partner_trainings_tone": shareTone(corePartnerTrainings, o.corePartnerTarget()),
		"core_staff_training_target":  rules.CoreStaffVisits * o.coreSchools(), "core_staff_trainings": coreStaffTrainings,
		"core_staff_trainings_tone": shareTone(coreStaffTrainings, rules.CoreStaffVisits*o.coreSchools()),
		"partner_visit_target":      o.corePartnerTarget() + o.partnerNeeded(),
		"schools_with_visit":        schoolsWithVisit, "training_schools": trainingSchools, "schools_with_training": withTraining,
		"schools_group_training":     o.count(func(s *School) bool { return s.GroupTraining }),
		"schools_meeting":            o.count(func(s *School) bool { return s.Meeting }),
		"schools_trained":            o.count(func(s *School) bool { return s.TrainingDone }),
		"not_clustered":              o.count(func(s *School) bool { return !s.Clustered }),
		"schools_staff_scheduled":    o.count((*School).staffScheduled),
		"schools_staff_and_partner":  o.count((*School).staffAndPartner),
		"client_staff_and_partner":   o.count(func(s *School) bool { return !s.isCore() && s.staffAndPartner() }),
		"core_visits_over":           o.count((*School).coreVisitsOver),
		"schools_in_school_training": o.count(func(s *School) bool { return s.InSchoolTraining }),
		"schools_awaiting_partner":   awaiting, "schools_covered": schoolsWithVisit + awaiting,
		"no_visit": o.schoolCount() - schoolsWithVisit, "unplanned": o.schoolCount() - (schoolsWithVisit + awaiting),
		"no_training": trainingSchools - withTraining,
		"no_both":     o.count(func(s *School) bool { return s.hasGap("no_both") }),
		"in_projects": o.count(func(s *School) bool { return s.InProject }),
		"visit_tone":  visitTone,
	}
}

func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

// leadFigures is LeadMonitor's: its key and name, every person's count added
// up (their booleans counted), and its own progress and tones.
func (l *Lead) figures() map[string]any {
	out := map[string]any{"key": l.Key, "name": l.Name}
	for _, o := range l.Officers {
		for name, v := range o.figures() {
			switch name {
			case "key", "name", "role", "role_label", "visit_tone", "partner_tone",
				"core_partner_visits_tone", "core_partner_trainings_tone", "core_staff_trainings_tone",
				"visit_progress", "delivery_progress":
				continue
			}
			n, _ := out[name].(int)
			switch x := v.(type) {
			case int:
				out[name] = n + x
			case bool:
				out[name] = n + boolInt(x)
			}
		}
	}
	get := func(name string) int { n, _ := out[name].(int); return n }
	for _, name := range []string{"visits_target", "staff_visits", "visits_done", "partner_needed", "partner_remaining",
		"core_partner_visits", "core_partner_target", "core_partner_trainings", "core_staff_trainings", "core_staff_training_target"} {
		if _, ok := out[name]; !ok {
			out[name] = 0
		}
	}
	visitProgress := percentage(get("staff_visits"), get("visits_target"))
	out["visit_progress"] = visitProgress
	out["delivery_progress"] = percentage(get("visits_done"), get("staff_visits"))
	out["visit_tone"] = tone(visitProgress)
	partnerTone := "neutral"
	if get("partner_needed") > 0 {
		partnerTone = "warning"
		if get("partner_remaining") == 0 {
			partnerTone = "success"
		}
	}
	out["partner_tone"] = partnerTone
	out["core_partner_visits_tone"] = shareTone(get("core_partner_visits"), get("core_partner_target"))
	out["core_partner_trainings_tone"] = shareTone(get("core_partner_trainings"), get("core_partner_target"))
	out["core_staff_trainings_tone"] = shareTone(get("core_staff_trainings"), get("core_staff_training_target"))
	return out
}

// Figures are the person's figures by the existing service's names.
func (o *Officer) Figures() map[string]any { return o.figures() }

// Figures are the team's figures by the existing service's names.
func (l *Lead) Figures() map[string]any { return l.figures() }

// Figures are the school's state by the existing service's names, with how
// far it is planned and its two checks (apps.planning.readiness).
func (s *School) Figures() map[string]any {
	return map[string]any{
		"id": s.ID, "code": s.Code, "name": s.Name, "school_type": s.Type, "district": s.District,
		"cluster_id": s.ClusterID, "cluster_name": s.ClusterName, "clustered": s.Clustered,
		"officer_id": s.OfficerID, "officer_name": s.OfficerName, "lead_id": s.LeadID, "lead_name": s.LeadName,
		"staff_visits": s.StaffVisits, "staff_ssa_visits": s.StaffSSAVisits, "staff_visits_done": s.StaffVisitsDone,
		"partner_visits": s.PartnerVisits, "partner_visits_done": s.PartnerVisitsDone,
		"partner_visits_undated": s.PartnerVisitsUndated, "partner_pending": s.PartnerPending,
		"group_training": s.GroupTraining, "meeting": s.Meeting, "in_school_training": s.InSchoolTraining,
		"training_done": s.TrainingDone, "in_project": s.InProject, "project_places": s.ProjectPlaces,
		"core_partner_visits": s.CorePartnerVisits, "core_partner_trainings": s.CorePartnerTrn,
		"core_staff_trainings": s.CoreStaffTrainings, "ssa_done": s.SSADone,
	}
}

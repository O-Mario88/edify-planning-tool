package planningmonitor

import "slices"

// cpoIdx is hierarchy.IDX: each figure's place in a vector.
var cpoIdx = func() map[string]int {
	m := map[string]int{}
	for i, f := range rules.CountryOversight.Fields {
		m[f] = i
	}
	return m
}()

func cpoBlank() []int { return make([]int, len(rules.CountryOversight.Fields)) }

// planningState is hierarchy.planning_state.
func planningState(cl cpoClaims) string {
	if cl.outside {
		return "outside"
	}
	planned := cl.cumStaff + cl.cumPartnerScheduled
	switch {
	case cl.visitSlots <= 0:
		if planned == 0 {
			return "none"
		}
		return "full"
	case planned >= cl.visitSlots:
		return "full"
	case planned > 0:
		return "partial"
	}
	return "none"
}

// duplicated is coverage.duplicate_reasons non-empty: a school planned more
// often than it should be, from the year's counts (a Partner's side with
// what it has not dated yet).
func duplicated(s *cpoSchool) bool { return len(duplicateReasons(s)) > 0 }

// duplicateReasons is coverage.duplicate_reasons over rules.duplicate_reasons:
// why a school's year is planned more often than it should be.
func duplicateReasons(s *cpoSchool) []string {
	c := rules.CountryOversight
	if s.family != c.ClientFamily && s.family != c.CoreFamily {
		return nil
	}
	staffAll, staffSSA := s.staff[2], s.staffSSA
	partnerAll, partnerSSA := 0, 0
	for _, p := range s.partners {
		partnerAll += p[pSchedT] + p[pPendT]
		partnerSSA += p[pSSAT]
	}
	staffPools := []int{staffSSA, staffAll - staffSSA}
	partnerPools := []int{partnerSSA, partnerAll - partnerSSA}
	over := func(pools []int) bool { return slices.ContainsFunc(pools, func(n int) bool { return n > 1 }) }
	reasons := []string{}
	if slices.Contains(rules.ClientTypes, s.schoolType) {
		if staffAll > 0 && partnerAll > 0 {
			reasons = append(reasons, "both")
		}
		if over(staffPools) {
			reasons = append(reasons, "staff")
		}
		if over(partnerPools) {
			reasons = append(reasons, "partner")
		}
		return reasons
	}
	n := need(s.schoolType)
	if n.StaffVisits > 0 && staffAll > n.StaffVisits {
		reasons = append(reasons, "staff_over")
	}
	if n.PartnerVisits > 0 && partnerAll > n.PartnerVisits {
		reasons = append(reasons, "partner_over")
	}
	return reasons
}

// schoolValues is hierarchy.school_values: one school's contribution to every
// figure.
func schoolValues(s *cpoSchool, cl cpoClaims) []int {
	v := cpoBlank()
	set := func(name string, value int) { v[cpoIdx[name]] = value }
	if !s.governed() {
		set("unmapped_schools", 1)
		return v
	}
	isCore := s.family == rules.CountryOversight.CoreFamily
	set("schools", 1)
	if f, ok := rules.CountryOversight.TypeFields[s.schoolType]; ok {
		set(f, 1)
	}
	if s.clustered() {
		set("clustered", 1)
		if cl.meetingCovered {
			set("meeting_covered_clustered", 1)
		} else {
			set("clustered_no_meeting", 1)
		}
	} else {
		set("unclustered", 1)
	}
	set("meeting_covered", one(cl.meetingCovered))
	set("cum_meeting_covered", one(cl.cumMeetingCovered))
	if s.withPartner {
		set("with_partner", 1)
	}
	if cl.trainingSlots > 0 {
		set("training_schools", 1)
		set("training_slots", cl.trainingSlots)
		set("training", cl.training)
		set("training_verified", cl.trainingVerified)
		set("cum_training", cl.cumTraining)
		set("any_training", one(cl.anyTraining))
		set("no_training", one(!cl.anyTraining))
		set("training_gap", max(0, cl.trainingSlots-cl.cumTraining))
		set("training_staff_slots", cl.trainingStaffSlots)
		set("training_partner_slots", cl.trainingPartnerSlots)
		set("training_staff", cl.trainingStaff)
		set("training_partner", cl.trainingPartner)
		set("training_partner_assigned", cl.trainingPartnerAssigned)
	}
	if cl.outside {
		return v
	}
	set("visit_schools", 1)
	set("visit_slots", cl.visitSlots)
	set("staff_expected", cl.staffExpected)
	set("partner_expected", cl.partnerExpected)
	if isCore {
		set("core_staff_slots", cl.staffExpected)
		set("core_partner_slots", cl.partnerExpected)
		set("partner_core_assigned", cl.partnerAssigned)
		set("partner_core_scheduled", cl.partnerScheduled)
	} else {
		set("client_slots", cl.visitSlots)
		set("client_staff_expected", cl.staffExpected)
		set("client_partner_expected", cl.partnerExpected)
		set("partner_client_assigned", cl.partnerAssigned)
		set("partner_client_scheduled", cl.partnerScheduled)
	}
	set("deficit", cl.deficit)
	set("staff", cl.staff)
	set("staff_core", cl.staffCore)
	set("staff_client", cl.staffClient)
	set("partner_assigned", cl.partnerAssigned)
	set("partner_scheduled", cl.partnerScheduled)
	set("staff_verified", cl.staffVerified)
	set("partner_verified", cl.partnerVerified)
	set("returned", cl.returned)
	set("cum_staff", cl.cumStaff)
	set("cum_partner_assigned", cl.cumPartnerAssigned)
	set("cum_partner_scheduled", cl.cumPartnerScheduled)
	set("unallocated", max(0, cl.visitSlots-cl.cumStaff-cl.cumPartnerAssigned))
	set("staff_gap", cl.staffGap)
	set("partner_gap", cl.partnerGap)
	staffPlanned, partnerPlanned := cl.anyStaff, cl.anyPartnerScheduled
	set("any_staff", one(staffPlanned))
	set("any_partner_scheduled", one(partnerPlanned))
	set("any_partner_assigned", one(cl.anyPartnerAssigned))
	set("any_visit", one(staffPlanned || partnerPlanned))
	switch {
	case staffPlanned && partnerPlanned:
		set("both", 1)
	case staffPlanned:
		set("staff_only", 1)
	case partnerPlanned:
		set("partner_only", 1)
	default:
		set("no_visit", 1)
		if !cl.anyPartnerAssigned {
			set("unplanned", 1)
		}
	}
	state := planningState(cl)
	set(map[string]string{"full": "fully_planned", "partial": "partially_planned", "none": "not_planned"}[state], 1)
	if staffPlanned || partnerPlanned {
		if state == "full" {
			set("planned_full", 1)
		} else {
			set("planned_part", 1)
		}
	}
	if isCore && cl.staffExpected > 0 && cl.cumStaff >= cl.staffExpected {
		set("core_staff_done", 1)
	}
	if cl.cumPartnerAssigned > cl.cumPartnerScheduled {
		set("awaiting_partner", 1)
	}
	if duplicated(s) {
		set("duplicates", 1)
	}
	return v
}

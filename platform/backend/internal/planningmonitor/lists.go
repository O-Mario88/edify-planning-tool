package planningmonitor

import (
	"slices"
	"sort"
	"strings"
)

// isListKey is a key of planning_monitor.LISTS: the schools behind a count
// of the monitor and of My Plan, not a gap, so in_list reads each one.
func isListKey(key string) bool {
	for _, l := range rules.Lists {
		if l[0] == key {
			return true
		}
	}
	return false
}

// inList is planning_monitor.in_list: whether s is one of the schools behind
// key, a gap or one of the lists.
func inList(s *School, key string) bool {
	if !isListKey(key) {
		return s.hasGap(key)
	}
	core := s.isCore()
	staffPair, partnerPair := rules.CoreStaffVisits, rules.CorePartner
	partnerHeld := s.hasPartner() || s.CorePartnerVisits > 0 || s.CorePartnerTrn > 0
	switch key {
	case "all":
		return true
	case "core":
		return core
	case "client":
		return !core
	case "visited":
		return s.hasVisit()
	case "staff_queue":
		return core || !(s.hasPartner() && s.StaffVisits == 0)
	case "staff_visits_left":
		if core {
			return s.StaffVisits < staffPair
		}
		return s.StaffVisits == 0 && !s.hasPartner()
	case "core_staff_visits":
		return core && s.StaffVisits > 0
	case "core_staff_visits_left":
		return core && s.StaffVisits < staffPair
	case "client_staff_visits":
		return !core && s.StaffVisits > 0
	case "client_staff_visits_left":
		return !core && s.StaffVisits == 0
	case "core_visits_over":
		return s.coreVisitsOver()
	case "client_staff_and_partner":
		return !core && s.staffAndPartner()
	case "core_staff_trainings":
		return s.CoreStaffTrainings > 0
	case "core_staff_trainings_left":
		return core && s.CoreStaffTrainings < staffPair
	case "training":
		return s.hasTraining()
	case "training_due":
		return s.needsTraining()
	case "with_partner":
		return partnerHeld
	case "partner_queue":
		return core || s.StaffVisits == 0
	case "partner_left":
		if core {
			return !partnerHeld
		}
		return s.StaffVisits == 0 && !s.hasPartner()
	case "partner_dated":
		return s.PartnerVisits > 0
	case "partner_waiting":
		return s.PartnerPending > 0
	case "partner_visits_left":
		if core {
			return s.PartnerVisits < partnerPair
		}
		return s.PartnerVisits == 0 && s.StaffVisits == 0
	case "core_partner_visits":
		return s.CorePartnerVisits > 0
	case "core_partner_visits_left":
		return core && s.CorePartnerVisits < partnerPair
	case "core_partner_trainings":
		return s.CorePartnerTrn > 0
	case "core_partner_trainings_left":
		return core && s.CorePartnerTrn < partnerPair
	case "in_project":
		return s.InProject
	case "not_in_project":
		return !s.InProject
	case "project_added":
		return s.ProjectPlaces > 0
	case "fully_planned", "partly_planned", "not_yet_planned":
		return schoolState(s) == strings.TrimSuffix(key, "_planned")
	case "duplicates":
		return isDuplicate(s)
	case "core_no_partner_half":
		return coreMissingPartnerHalf(s)
	case "not_visited":
		return !s.visitDone()
	case "not_trained":
		return s.needsTraining() && !s.TrainingDone
	case "no_ssa":
		return !s.SSADone
	}
	return false
}

// listSchools is planning_monitor.list_schools: the schools behind key for
// these people, by holder then name. A list reads the outreach-only schools
// a person holds as well, but for the monitored lists.
func listSchools(officers []*Officer, key string) []*School {
	var found []*School
	withOutreach := isListKey(key) && !slices.Contains(rules.MonitoredLists, key)
	for _, o := range officers {
		held := o.Schools
		if withOutreach {
			held = append(slices.Clip(o.Schools), o.Outreach...)
		}
		for _, s := range held {
			if inList(s, key) {
				found = append(found, s)
			}
		}
	}
	sort.SliceStable(found, func(i, j int) bool {
		a, b := strings.ToLower(found[i].OfficerName), strings.ToLower(found[j].OfficerName)
		if a != b {
			return a < b
		}
		return strings.ToLower(found[i].Name) < strings.ToLower(found[j].Name)
	})
	return found
}

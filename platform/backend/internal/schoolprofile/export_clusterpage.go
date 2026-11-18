package schoolprofile

import "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"

// What a cluster's schools list (internal/clusterpage) reads from the
// profile's rules: the visit rule's vocabularies and a school type's label.

// GateRules are the visit rule's vocabularies (rules.Gate), for a cluster's
// schools list and the Programme Schools page (internal/programmeschools).
func GateRules() visitgate.Rules { return rules.Gate }

// SchoolTypeLabel is School.get_school_type_display: the choice's label, or
// the stored value where it names no choice.
func SchoolTypeLabel(value string) string {
	if label, ok := rules.SchoolTypes[value]; ok {
		return label
	}
	return value
}

// MayOpenSchools is whether a role's school names link to their profiles
// (school_links._may_open: can_open_url("/schools/0")).
func MayOpenSchools(role string) bool { return rules.Doors[role].Profile }

// MayPlan is whether a role holds the planning page (the district
// profile's door, can_open_url("/districts/0"), is that page's).
func MayPlan(role string) bool { return rules.Doors[role].OpenDistrict }

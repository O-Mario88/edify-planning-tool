package schoolprofile

import "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"

// What a cluster's schools list (internal/clusterpage) reads from the
// profile's rules: the visit rule's vocabularies and a school type's label.

// GateRules are the visit rule's vocabularies (rules.Gate).
func GateRules() visitgate.Rules { return rules.Gate }

// SchoolTypeLabel is School.get_school_type_display: the choice's label, or
// the stored value where it names no choice.
func SchoolTypeLabel(value string) string {
	if label, ok := rules.SchoolTypes[value]; ok {
		return label
	}
	return value
}

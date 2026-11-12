package schoolprofile

import "github.com/O-Mario88/edify-planning-tool/platform/backend/internal/visitgate"

// GateRules are the visit rule's vocabularies (export_school_profile_rules,
// "gate"), for the Programme Schools page (internal/programmeschools), which
// shows each school's visit entitlement by the same rule.
func GateRules() visitgate.Rules { return rules.Gate }

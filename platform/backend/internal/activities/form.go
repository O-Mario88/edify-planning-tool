package activities

import (
	"net/url"
	"strings"
)

// The drawer's form as Planning's Schedule drawer posts it to
// /planning/schedule-action. formFields are the fields 27.3's case posts:
// the contract's, and the drawer's own constants. Any other field carrying a
// value names a case Go does not take (a partner, a project, a source
// activity, a cluster, a training, an SSA collection flag), and the request
// is handed on whole.
var formFields = map[string]bool{
	"csrfmiddlewaretoken": true, "school_id": true, "purpose_of_visit": true, "scheduled_date": true,
	"activity_goal": true, "activity_purpose_text": true, "expected_outcome": true,
	"ssa_deviation_reason": true, "catalogue_item_id": true, "recommendation_reason": true,
	"require_catalogue": true, "activity_type": true, "delivery_type": true, "executor_type": true,
	"focus_intervention": true, "source_activity_id": true, "visit_justification": true,
}

// RequestFromForm reads the drawer's form; false when Go does not take it.
// The posted activity_type (the drawer script's SSA-led default) is only the
// view's fallback for a missing purpose: a purpose of the six replaces it
// (purpose_activity_type, 2207), so it is not read.
func RequestFromForm(form url.Values) (Request, bool) {
	for name, values := range form {
		if formFields[name] {
			continue
		}
		for _, v := range values {
			if strings.TrimSpace(v) != "" {
				return Request{}, false
			}
		}
	}
	one := func(name string) string { return form.Get(name) }
	if one("require_catalogue") != "yes" ||
		(one("delivery_type") != "" && one("delivery_type") != "staff") ||
		(strings.TrimSpace(one("executor_type")) != "" && strings.TrimSpace(one("executor_type")) != "staff") {
		return Request{}, false
	}
	goal := one("activity_goal")
	if goal == "" {
		goal = one("activity_purpose_text")
	}
	return Request{
		SchoolID: one("school_id"), Purpose: one("purpose_of_visit"), Date: one("scheduled_date"),
		Goal: goal, Outcome: one("expected_outcome"), DeviationReason: one("ssa_deviation_reason"),
		CatalogueItemID: one("catalogue_item_id"), RecReason: one("recommendation_reason"),
		Focus:            strings.TrimSpace(one("focus_intervention")),
		SourceActivityID: strings.TrimSpace(one("source_activity_id")),
		Justification:    strings.TrimSpace(one("visit_justification")),
	}, true
}

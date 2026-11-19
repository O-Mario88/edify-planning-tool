package fieldpages

import (
	"net/url"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The Schedule School Visit form with nothing chosen yet
// (planning_views.schedule_activity_form_view, pages/planning/schedule.html):
// a school is picked by typing, so the form lists no school, and a visit's
// form lists no cluster. A chosen action, school or cluster (the preselected
// school's recommendations, a cluster's list) is the existing page's.

const schedulePath = "/planning/schedule"

// scheduleAsked are the query keys that change what the form draws.
var scheduleAsked = []string{"action", "school", "cluster"}

// scheduleChosen is whether the request chose anything the form draws.
func scheduleChosen(query url.Values) bool {
	for _, k := range scheduleAsked {
		if query.Get(k) != "" {
			return true
		}
	}
	return false
}

func field(f *screensv1.DrawerField) *screensv1.PageFormItem {
	return &screensv1.PageFormItem{Kind: &screensv1.PageFormItem_Field{Field: f}}
}

func scheduleForm() *screensv1.GetPageResponse {
	options := []*screensv1.DrawerOption{{Value: "", Label: "Select Intervention..."}}
	for _, c := range rules.Interventions {
		options = append(options, &screensv1.DrawerOption{Value: c[0], Label: c[1]})
	}
	h := header("", "Schedule School Visit",
		"Configure activity logistics, purpose, and target interventions. Cost is computed from active CD catalogue.")
	h.BackLabel, h.BackHref = "Back to Planning", "/planning"
	form := &screensv1.PageForm{SubmitLabel: "Confirm & Schedule Activity", Key: "form", Items: []*screensv1.PageFormItem{
		field(&screensv1.DrawerField{Name: "school_id", Label: "Target School", Kind: "text", Required: true,
			Help:        "Type at least two characters, then choose a school in your direct portfolio.",
			Placeholder: "Type a School ID or name", ReloadsPath: "/planning/schedule/schools"}),
		field(&screensv1.DrawerField{Name: "scheduled_date", Label: "Scheduled Date", Kind: "date", Required: true}),
		field(&screensv1.DrawerField{Name: "focus_intervention", Label: "Primary Focus Intervention", Kind: "select",
			Options: options}),
		{Kind: &screensv1.PageFormItem_Text{Text: "Staff make this visit. To have a partner make it, use Assign on the school's row in Planning: the partner chooses the date."}},
		field(&screensv1.DrawerField{Name: "activity_purpose_text", Label: "Purpose Description", Kind: "textarea",
			Placeholder: "What needs to be achieved in this activity?"}),
		field(&screensv1.DrawerField{Name: "expected_outcome", Label: "Expected Outcome / Goal", Kind: "textarea",
			Placeholder: "Target delta or specific checklist outcome..."}),
	}}
	return page(h, schedulePath,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Form{Form: form}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: "Live Costing Breakdown",
			Badges: []*screensv1.PageBadge{}, Items: []*screensv1.PagePanelItem{
				text("Fill out target, date, and participants to see itemized UGX rates fetch live from CD catalogue."),
			}}}})
}

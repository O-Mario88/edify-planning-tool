// Package todosnooze is the Today queue's Snooze, made by Go: a person puts
// one of their To-Dos aside until tomorrow or next week, which hides it from
// their Today until that day without touching the work itself
// (apps.frontend.views.today_views.today_snooze ->
// apps.command_center.today_actions.snooze, docs/migration/50).
//
// Undoing a snooze (today_unsnooze) is Go's too: the row goes through the
// narrow function gateway_todos.unsnooze (the gateway holds no DELETE), and
// the Today panel the answer shows is drawn again by the existing
// application (docs/migration/63). Every decision taken on a Today row
// (today_actions.perform, through each record's own service) is still the
// existing application's; the saves answer ErrHandOn for every reader they
// do not take.
//
// The vocabularies are the existing ones, exported to rules.json by
// `manage.py export_todo_snooze_rules`;
// apps/command_center/test_todo_snooze_rules_export.py fails when they
// differ.
package todosnooze

import (
	_ "embed"
	"encoding/json"
	"fmt"
)

//go:embed rules.json
var rulesJSON []byte

// Door is what a role reaches.
type Door struct {
	// Today is require_page_permission("today") for the role in its own
	// seat; PerPerson is a role whose page map is asked per person (a
	// partner's team member), which Go hands on.
	Today     bool `json:"today"`
	PerPerson bool `json:"per_person"`
}

// Rules are the snooze's vocabularies.
type Rules struct {
	Doors map[string]Door `json:"doors"`
	// SnoozeDays is today_actions.SNOOZE_DAYS: a choice and its days.
	SnoozeDays map[string]int `json:"snooze_days"`
	// Refusal is what snooze answers an empty item or an unknown choice.
	Refusal string `json:"refusal"`
	// Lengths are TodoSnooze's columns, which the save cuts to.
	Lengths struct {
		TodoID int `json:"todo_id"`
		Title  int `json:"title"`
	} `json:"lengths"`
	// Unsnooze is what undoing a snooze answers: the Today panel the
	// existing application draws again (Redraw, today_panel), put in the
	// panel's place (Retarget, Reswap), with the This Week Me tab's field
	// (SectionField) carried to the redraw.
	Unsnooze struct {
		Redraw       string `json:"redraw"`
		Retarget     string `json:"retarget"`
		Reswap       string `json:"reswap"`
		SectionField string `json:"section_field"`
	} `json:"unsnooze"`
}

var rules = mustRules(rulesJSON)

func mustRules(raw []byte) Rules {
	var r Rules
	if err := json.Unmarshal(raw, &r); err != nil {
		panic(fmt.Sprintf("todosnooze: rules.json: %v", err))
	}
	if r.Refusal == "" || len(r.SnoozeDays) == 0 || r.Lengths.TodoID == 0 || r.Lengths.Title == 0 ||
		r.Unsnooze.Redraw == "" || r.Unsnooze.Retarget == "" || r.Unsnooze.Reswap == "" || r.Unsnooze.SectionField == "" {
		panic("todosnooze: rules.json is incomplete")
	}
	return r
}

package main

import (
	"context"
	"net/url"
	"strings"
)

func init() { pageQuestions["/calendar"] = calendarQuestions }

// calendarQuestions are the Calendar's: the month as it opens; months
// before and after it, the year's turn and the FY's, months holding
// holidays, observances and an announced Eid; months and years out of
// range, padded, signed or not numbers; the agenda view; each activity type
// family, status filter and event kind, and ones the page does not know;
// filters together; the special-projects lens; and for a reader with a
// people strip, every calendar on it as it opens, in another month, filtered
// and in the agenda view, and a person not on it.
func calendarQuestions(_ context.Context, r *pageRun, token string) []map[string]string {
	out := []map[string]string{{}}
	for _, q := range []string{
		"month=10&year=2026", "month=12&year=2026", "month=1&year=2027", "month=9&year=2026",
		"month=4&year=2026", "month=3&year=2026", "month=5&year=2026", "month=6&year=2027",
		"month=2&year=2028", "month=12&year=2100", "month=1&year=2000",
		"month=13&year=2026", "month=0", "month=abc", "year=1999", "year=2101", "month=+3&year=2026",
		"month= 3 &year= 2026 ", "month=1_0&year=2026", "month=10", "year=2027", "month=3.0",
		"view=agenda", "view=agenda&month=4&year=2026", "view=agenda&month=12&year=2026", "view=month", "view=AGENDA",
		"activity_type=school_visit", "activity_type=cluster_meeting", "activity_type=core_visit",
		"activity_type=in_school_training", "activity_type=xyz", "activity_type=school_visit&month=4&year=2026",
		"status=scheduled", "status=in_progress", "status=cancelled", "status=xyz",
		"status=cancelled&month=4&year=2026", "status=in_progress&view=agenda",
		"event_kind=activity", "event_kind=leave", "event_kind=holiday", "event_kind=event", "event_kind=xyz",
		"event_kind=holiday&month=12&year=2026&view=agenda",
		"activity_type=school_visit&status=scheduled&event_kind=activity",
		"project_scope=special", "project_scope=special&project=nope", "project_scope=special&month=4&year=2026",
		"project_scope=other", "project=abc", "person=nope", "person= ", "format=csv", "format=json", "x=1",
	} {
		out = append(out, parsed(q))
	}
	// Every calendar the strips offer: the first strip's, and the people of
	// each team it opens (the Country Director's second strip).
	persons, seen := []string{}, map[string]bool{}
	collect := func(query map[string]string) {
		page, err := r.existingPage(token, query)
		if err != nil {
			return
		}
		for _, b := range page.GetBlocks() {
			for _, item := range b.GetPanel().GetItems() {
				for _, l := range item.GetLinks().GetLinks() {
					u, err := url.Parse(l.GetHref())
					if err != nil || !strings.HasPrefix(l.GetHref(), "/calendar?") {
						continue
					}
					if p := u.Query().Get("person"); p != "" && !seen[p] {
						seen[p] = true
						persons = append(persons, p)
					}
				}
			}
		}
	}
	collect(map[string]string{})
	for _, p := range append([]string{}, persons...) {
		collect(map[string]string{"person": p})
	}
	for _, p := range persons {
		for _, q := range []string{"", "&month=12&year=2026", "&month=4&year=2026&status=cancelled",
			"&view=agenda", "&month=10&year=2026&event_kind=holiday", "&activity_type=school_visit"} {
			out = append(out, parsed("person="+p+q))
		}
		out = append(out, parsed("person= "+p+" "))
	}
	return out
}

func parsed(q string) map[string]string {
	out := map[string]string{}
	for _, part := range strings.Split(q, "&") {
		if part == "" {
			continue
		}
		k, v, _ := strings.Cut(part, "=")
		out[k] = v
	}
	return out
}

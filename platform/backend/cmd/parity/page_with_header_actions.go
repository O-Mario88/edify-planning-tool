package main

import (
	"context"
	"maps"
)

// The header buttons (Export, Download CSV, Plan Field Event, Recent
// changes, Scoring, Set Country Targets, the ceiling doors) follow the
// page's query, so every page that offers one is also asked with what a
// header link must leave out or put in order: an export or format the feed
// never passes on, a blank parameter, a search with characters a link must
// escape, and several parameters at once. This file sorts after the pages
// it extends, so their questions are registered when its init runs.
func init() {
	extra := []map[string]string{
		{"export": "xlsx"},
		{"format": "xlsx"},
		{"q": ""},
		{"q": "a b&c/d"},
		{"search": "x y", "tab": "core"},
		{"fy": "2026", "q": "a", "page": "2"},
	}
	for path, also := range map[string][]map[string]string{
		"/planning":                extra,
		"/clusters":                extra,
		"/cluster-oversight/":      append(extra, map[string]string{"view": "courses", "area": "nonsense"}),
		"/core-schools-oversight/": append(extra, map[string]string{"tab": "core_visits", "q": "a"}),
		"/staff-activity":          append(extra, map[string]string{"staff_page": "2", "role": "CCEO"}),
		"/team-performance/":       extra,
		"/team-planning-oversight/": {
			{"view": "trainings", "fy": "2026"},
			{"view": "trainings", "export": "xlsx"},
		},
	} {
		asked, ok := pageQuestions[path]
		if !ok {
			continue
		}
		pageQuestions[path] = func(ctx context.Context, r *pageRun, token string) []map[string]string {
			out := asked(ctx, r, token)
			for _, q := range also {
				out = append(out, maps.Clone(q))
			}
			return out
		}
	}
}

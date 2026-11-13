package main

import (
	"context"
	"net/url"
	"os"
	"strings"
)

func init() { pageQuestions["/team-performance/"] = teamPerformanceQuestions }

// teamPerformanceQuestions are the Team Performance page's: every tab as it
// opens and for each year, every period kind with a week, a quarter and a
// month in and out of range, the Detailed Country Report for each scope the
// reader is offered, every dashboard view, lead chip and sort, the Executive
// Summary at each of its levels and narrowed to each region and team, one
// section's charts on their own, and values that are not values.
//
// Each summary question renders the report once and each of its nine
// sections' charts once more on the existing side, so the full set takes
// many minutes an account; EDIFY_PARITY_TEAM_PERFORMANCE=lean asks a
// smaller set that still opens every tab, view, period kind and level.
func teamPerformanceQuestions(ctx context.Context, r *pageRun, token string) []map[string]string {
	if os.Getenv("EDIFY_PARITY_TEAM_PERFORMANCE") == "lean" {
		return teamPerformanceLean(ctx, r, token)
	}
	out := []map[string]string{{}}
	tabs := []string{"summary", "weekly", "milestones", "dashboard", "month", "core", "nonsense"}
	for _, tab := range tabs {
		out = append(out, map[string]string{"tab": tab})
		for _, fy := range []string{"2026", "2028", "1999", "abc"} {
			out = append(out, map[string]string{"tab": tab, "fy": fy})
		}
	}
	for _, tab := range []string{"summary", "milestones"} {
		for _, kv := range [][2]string{
			{"period", "week"}, {"period", "quarter"}, {"period", "year"}, {"period", "bad"},
		} {
			out = append(out, map[string]string{"tab": tab, kv[0]: kv[1]})
		}
		out = append(out,
			map[string]string{"tab": tab, "period": "week", "week": "2026-10-14"},
			map[string]string{"tab": tab, "period": "week", "week": "2025-01-01"},
			map[string]string{"tab": tab, "period": "week", "week": "2026-W44"},
			map[string]string{"tab": tab, "period": "week", "week": "nope"},
			map[string]string{"tab": tab, "period": "quarter", "quarter": "1"},
			map[string]string{"tab": tab, "period": "quarter", "quarter": "3"},
			map[string]string{"tab": tab, "period": "quarter", "quarter": "9"},
			map[string]string{"tab": tab, "period": "month", "month": "1"},
			map[string]string{"tab": tab, "period": "month", "month": "12"},
			map[string]string{"tab": tab, "period": "month", "month": "13"},
			map[string]string{"tab": tab, "period": "year", "fy": "2026"},
		)
	}
	for _, tab := range []string{"weekly", "dashboard", "month"} {
		for _, m := range []string{"1", "6", "0", "x"} {
			out = append(out, map[string]string{"tab": tab, "month": m})
		}
	}
	out = append(out, map[string]string{"tab": "core", "fy": "2026"}, map[string]string{"tab": "weekly", "scope": "nonsense"})
	for _, view := range []string{"cceos", "deep", "milestones", "leads", "grid", "bad"} {
		out = append(out, map[string]string{"tab": "dashboard", "view": view})
	}
	for _, sort := range []string{"portfolio", "visits", "trainings", "recruitment", "ssa", "bad"} {
		out = append(out, map[string]string{"tab": "dashboard", "view": "cceos", "sort": sort})
	}
	out = append(out,
		map[string]string{"tab": "dashboard", "view": "deep", "officer": "nonsense"},
		map[string]string{"tab": "dashboard", "view": "grid", "lead": "nonsense"},
		map[string]string{"tab": "dashboard", "view": "grid", "lead": "none"},
	)
	for _, by := range []string{"region", "lead", "cceo", "district", "bad"} {
		out = append(out, map[string]string{"by": by})
	}
	out = append(out,
		map[string]string{"by": "lead", "in_region": "Central"},
		map[string]string{"by": "cceo", "in_region": "Central"},
		map[string]string{"by": "lead", "in_region": "Eastern"},
		map[string]string{"by": "cceo", "in_region": "Nowhere"},
		map[string]string{"by": "cceo", "in_lead": "nonsense"},
		map[string]string{"charts": "Program Growth"},
		map[string]string{"charts": "Visits", "by": "lead"},
		map[string]string{"charts": "Nowhere"},
		map[string]string{"tab": "weekly", "charts": "Visits"},
	)

	// What the page offers this reader: the scopes, the officers, the lead
	// chips and the summary's own links.
	for _, tab := range []map[string]string{{"tab": "weekly"}, {"tab": "dashboard"}, {}} {
		page, err := r.goPage(ctx, token, tab)
		if err != nil {
			continue
		}
		for _, block := range page.GetBlocks() {
			for _, f := range block.GetFilters().GetFilters() {
				switch f.GetName() {
				case "scope":
					for _, o := range f.GetOptions() {
						out = append(out, map[string]string{"tab": "weekly", "scope": o.GetValue()})
					}
				case "officer":
					for i, o := range f.GetOptions() {
						if o.GetValue() != "" && i <= 4 {
							out = append(out, map[string]string{"tab": "dashboard", "view": "deep", "officer": o.GetValue()})
						}
					}
				}
			}
			for _, item := range block.GetPanel().GetItems() {
				for _, l := range item.GetLinks().GetLinks() {
					q := tpQueryOf(l.GetHref())
					if q["lead"] != "" {
						out = append(out, q, map[string]string{"by": "cceo", "in_lead": q["lead"]})
					}
				}
			}
		}
	}
	return out
}

// tpQueryOf is a page link's query ("?fy=2027&lead=x") as a question.
func tpQueryOf(href string) map[string]string {
	values, err := url.ParseQuery(strings.TrimPrefix(href, "?"))
	if err != nil {
		return nil
	}
	out := map[string]string{}
	for key := range values {
		out[key] = values.Get(key)
	}
	return out
}

func teamPerformanceLean(ctx context.Context, r *pageRun, token string) []map[string]string {
	out := []map[string]string{{}}
	for _, tab := range []string{"weekly", "milestones", "dashboard", "month", "core", "nonsense"} {
		out = append(out, map[string]string{"tab": tab})
	}
	out = append(out,
		map[string]string{"fy": "2026"}, map[string]string{"fy": "1999"}, map[string]string{"tab": "weekly", "fy": "2026"},
		map[string]string{"tab": "core", "fy": "2028"}, map[string]string{"tab": "month", "month": "1"},
		map[string]string{"period": "week", "week": "2026-W44"}, map[string]string{"period": "quarter", "quarter": "1"},
		map[string]string{"period": "year"}, map[string]string{"tab": "milestones", "period": "week"},
		map[string]string{"tab": "milestones", "period": "quarter", "quarter": "9"}, map[string]string{"tab": "weekly", "month": "13"},
		map[string]string{"by": "lead"}, map[string]string{"by": "cceo"}, map[string]string{"by": "district"},
		map[string]string{"charts": "Visits"}, map[string]string{"charts": "Nowhere"},
	)
	for _, view := range []string{"deep", "milestones", "leads", "grid"} {
		out = append(out, map[string]string{"tab": "dashboard", "view": view})
	}
	out = append(out, map[string]string{"tab": "dashboard", "view": "cceos", "sort": "visits"})
	for _, tab := range []map[string]string{{"tab": "weekly"}, {"tab": "dashboard"}} {
		page, err := r.goPage(ctx, token, tab)
		if err != nil {
			continue
		}
		leads := 0
		for _, block := range page.GetBlocks() {
			for _, f := range block.GetFilters().GetFilters() {
				if f.GetName() == "scope" {
					for i, o := range f.GetOptions() {
						if i < 3 {
							out = append(out, map[string]string{"tab": "weekly", "scope": o.GetValue()})
						}
					}
				}
			}
			for _, item := range block.GetPanel().GetItems() {
				for _, l := range item.GetLinks().GetLinks() {
					if q := tpQueryOf(l.GetHref()); q["lead"] != "" && leads == 0 {
						leads++
						out = append(out, q, map[string]string{"by": "cceo", "in_lead": q["lead"]})
					}
				}
			}
		}
	}
	return out
}

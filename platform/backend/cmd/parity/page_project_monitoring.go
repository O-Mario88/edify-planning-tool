package main

import (
	"context"
	"net/url"
)

func init() { pageQuestions["/projects/monitoring"] = projectMonitoringQuestions }

// projectMonitoringQuestions are Project Monitoring's: the page as it opens,
// every project tab, every stage, every year and bad ones, each column
// filter's values and values no school holds, and two filters together.
func projectMonitoringQuestions(ctx context.Context, r *pageRun, token string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"stage", "not_planned"}, {"stage", "staff_planned"}, {"stage", "delivered"}, {"stage", "verified"},
		{"stage", "none"}, {"stage", "nonsense"}, {"stage", " not_planned "},
		{"fy", "2025"}, {"fy", "2026"}, {"fy", "2028"}, {"fy", "1999"}, {"fy", "abc"},
		{"project", "nonsense"}, {"district", "Nowhere"}, {"partner", "Nobody"}, {"training", "x"},
		{"purpose", "x"}, {"activity", "Scheduled"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	first, err := r.goPage(ctx, token, map[string]string{})
	if err != nil {
		return out
	}
	for _, block := range first.GetBlocks() {
		for _, f := range block.GetFilters().GetFilters() {
			switch f.GetName() {
			case "district", "purpose":
				for _, o := range f.GetOptions() {
					if o.GetValue() != "" {
						out = append(out, map[string]string{f.GetName(): o.GetValue()},
							map[string]string{f.GetName(): o.GetValue(), "stage": "staff_planned"})
					}
				}
			}
		}
		for _, t := range block.GetLinkTabs().GetTabs() {
			if q, err := url.ParseQuery(trimQuery(t.GetHref())); err == nil && q.Get("project") != "" {
				out = append(out, map[string]string{"project": q.Get("project")},
					map[string]string{"project": q.Get("project"), "fy": "2026"})
			}
		}
	}
	return out
}

func trimQuery(href string) string {
	if len(href) > 0 && href[0] == '?' {
		return href[1:]
	}
	return ""
}

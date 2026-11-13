package main

import (
	"context"
	"net/url"
	"strings"
)

func init() { pageQuestions["/partner-oversight/"] = partnerOversightQuestions }

// partnerOversightQuestions are Partner Monitoring's: the page as it opens,
// every period, year, month, quarter and week shape, each status and work
// tab, team members (each on the reader's strip, and one that is not),
// values that are not values, and links the export drawer writes.
func partnerOversightQuestions(ctx context.Context, r *pageRun, token string) []map[string]string {
	out := []map[string]string{{}}
	for _, kv := range [][2]string{
		{"period", "week"}, {"period", "month"}, {"period", "quarter"}, {"period", "fy"}, {"period", "YEAR"},
		{"fy", "2025"}, {"fy", "2026"}, {"fy", "2028"}, {"fy", "1999"}, {"fy", "abc"}, {"fy", " 2026 "},
		{"month", "3"}, {"month", "13"}, {"month", "abc"}, {"quarter", "Q3"}, {"quarter", "q2"}, {"quarter", "Q9"},
		{"week", "2026-W02"}, {"week", "2026-W2"}, {"week", "nonsense"},
		{"status", "awaiting_schedule"}, {"status", "returned"}, {"status", "xyz"},
		{"work", "visits"}, {"work", "clusters"}, {"work", "core"}, {"work", "bogus"},
		{"member", "all"}, {"member", "nobody"}, {"program_lead", "someone"}, {"partner", "nobody"},
		{"period_type", "fy"}, {"engagement_page", "2"},
	} {
		out = append(out, map[string]string{kv[0]: kv[1]})
	}
	out = append(out, map[string]string{"period": "month", "month": "2", "fy": "2026"},
		map[string]string{"period": "quarter", "quarter": "Q4", "status": "scheduled", "work": "trainings"})
	first, err := r.goPage(ctx, token, map[string]string{})
	if err != nil {
		return out
	}
	for _, block := range first.GetBlocks() {
		for _, tab := range block.GetLinkTabs().GetTabs() {
			q, err := url.ParseQuery(strings.TrimPrefix(tab.GetHref(), "?"))
			if err == nil && q.Get("member") != "" && q.Get("member") != "all" {
				out = append(out, map[string]string{"member": q.Get("member")})
			}
		}
	}
	return out
}

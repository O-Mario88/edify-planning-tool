package main

import (
	"context"
	"maps"
)

// A blank parameter (q=) is dropped by the gateway before any page sees it,
// and the parity tool now drops it from its request to the existing
// application too (existingPageURL), so pages whose links keep blank
// parameters are asked with one, alone and beside a value. This file sorts
// after the pages it extends, so their questions are registered when its
// init runs.
func init() {
	for path, also := range map[string][]map[string]string{
		"/core-schools-oversight/": {{"q": ""}, {"q": "", "tab": "core_visits"}},
		"/staff-activity":          {{"q": ""}, {"q": "", "role": "CCEO"}},
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

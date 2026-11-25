package budgetpage

import (
	"context"
	"net/url"
	"sort"
	"strings"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pageaccess"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// CountryBudgetPath is the Monthly General Budget's old address
// (/country-budget): country_budget_view keeps old bookmarks by sending them
// to the unified Budget page with their query (_budget_redirect), behind the
// page's own gate. The page of Go's own design drawn here before is gone
// (docs/migration/189).
const CountryBudgetPath = "/country-budget"

func (s *Service) countryBudget(_ context.Context, p auth.Principal, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	if !pageaccess.CanOpen(p.ActiveRole, false, CountryBudgetPath) {
		return nil, true, pagegate.ErrNotAvailable
	}
	return &screensv1.GetPageResponse{Redirect: Path + encodedQuery(query)}, true, nil
}

// encodedQuery is "?" + QueryDict.urlencode() for a query that has one: each
// value of each key, in the order the gateway hands the query on (by key).
func encodedQuery(query url.Values) string {
	keys := make([]string, 0, len(query))
	for k := range query {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	parts := []string{}
	for _, k := range keys {
		for _, v := range query[k] {
			parts = append(parts, url.QueryEscape(k)+"="+url.QueryEscape(v))
		}
	}
	if len(parts) == 0 {
		return ""
	}
	return "?" + strings.Join(parts, "&")
}

package budgetpage

import (
	"context"
	"errors"
	"net/url"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pagegate"
)

// country_budget_view: a reader the page lets in is sent to the unified
// Budget page with their query; anyone else is refused before it runs.
func TestCountryBudgetSendsOldBookmarksToBudget(t *testing.T) {
	s := NewService(nil, time.Now)
	cases := []struct {
		role  string
		query url.Values
		want  string
	}{
		{"CountryDirector", nil, "/budget"},
		{"CountryDirector", url.Values{"fy": {"2027"}, "month": {"11"}}, "/budget?fy=2027&month=11"},
		{"Accountant", url.Values{"q": {"a b"}}, "/budget?q=a+b"},
	}
	for _, c := range cases {
		for _, path := range []string{CountryBudgetPath, CountryBudgetPath + "/"} {
			page, served, err := s.Build(context.Background(), auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: c.role}}, path, c.query)
			if err != nil || !served || page.GetRedirect() != c.want {
				t.Errorf("%s %s %v: %v %v %q", c.role, path, c.query, err, served, page.GetRedirect())
			}
		}
	}
	if _, served, err := s.Build(context.Background(), auth.Principal{Account: auth.Account{UserID: "u", ActiveRole: "CCEO"}}, CountryBudgetPath, nil); !served || !errors.Is(err, pagegate.ErrNotAvailable) {
		t.Errorf("a CCEO: %v %v, want refused", served, err)
	}
}

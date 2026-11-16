package dashboard

import (
	"net/url"
	"testing"
)

func TestGoDrawsTheOfficersOwnWeekAndHandsOnTheRest(t *testing.T) {
	cases := map[string]bool{
		"":                                  true,
		"view=week":                         true,
		"view=Today":                        true,
		"fy=2027&view=week&week=2026-11-09": true,
		"who=me":                            true,
		"who=nobody":                        true,
		"show=nonsense":                     true,
		"view=map":                          false,
		"view=operations":                   false,
		"who=everyone":                      false,
		"who=partners":                      false,
		"show=behind":                       false,
		"wk_visits_page=2":                  false,
		"wnyn_visits_page=2":                false,
	}
	for raw, want := range cases {
		query, err := url.ParseQuery(raw)
		if err != nil {
			t.Fatal(err)
		}
		if got := served(query); got != want {
			t.Errorf("%q: served %v, want %v", raw, got, want)
		}
	}
}

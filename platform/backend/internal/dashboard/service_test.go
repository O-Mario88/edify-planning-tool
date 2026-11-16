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

func TestGoDrawsTheLeadsThisWeekAndHandsOnTheOtherViews(t *testing.T) {
	cases := map[string]bool{
		"":                                  true,
		"view=week":                         true,
		"view=WEEK":                         true,
		"view=nonsense":                     true,
		"fy=2027&week=2026-11-09":           true,
		"who=cmw9p7bwp00t19mekheun":         true,
		"plans=team":                        true,
		"show=nonsense":                     true,
		"view=today":                        false,
		"view=operations":                   false,
		"view=map":                          false,
		"view=priorities":                   false,
		"view=collaboration":                false,
		"pm=view%3Dexecution":               false,
		"sa=period%3Dweek":                  false,
		"urgent_page=2":                     false,
		"fy=2027&view=team&week=2026-11-09": false,
	}
	for raw, want := range cases {
		query, err := url.ParseQuery(raw)
		if err != nil {
			t.Fatal(err)
		}
		if got := leadServed(query); got != want {
			t.Errorf("%q: served %v, want %v", raw, got, want)
		}
	}
}

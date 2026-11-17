package schooldirectory

import (
	"strings"
	"testing"
)

func TestAnalyticsReachFollowsTheReadersLens(t *testing.T) {
	for _, c := range []struct {
		name  string
		scope Scope
		want  string
		args  int
	}{
		{"a country reader with no country reads everything", Scope{CountryScope: true}, "(true)", 0},
		{"a country reader reads their country through the registry", Scope{CountryScope: true, Country: "Uganda"},
			"WHERE a.alias = $1 AND c.state = 'active'", 1},
		{"a region reader with no regions reads nothing", Scope{RegionScope: true}, "(false)", 0},
		{"a region reader reads their regions", Scope{RegionScope: true, RegionIDs: []string{"r1"}}, "s.region_id = ANY($1)", 1},
		{"a summary reader with no geography reads the deployment", Scope{SummaryOnly: true}, "(true)", 0},
		{"a summary reader with regions reads them", Scope{SummaryOnly: true, RegionIDs: []string{"r1"}}, "s.region_id = ANY($1)", 1},
		{"an officer reads their own and team schools", Scope{OwnSchoolIDs: []string{"a"}, SchoolIDs: []string{"a", "b"}}, "s.id = ANY($1)", 1},
		{"an officer with no schools reads nothing", Scope{}, "(false)", 0},
	} {
		args := []any{}
		got := AnalyticsReach(c.scope, &args)
		if !strings.HasPrefix(got, "s.deleted_at IS NULL AND (") || !strings.Contains(got, c.want) || len(args) != c.args {
			t.Errorf("%s: %s with %d arguments", c.name, got, len(args))
		}
	}
	// Arguments already gathered keep their numbers.
	args := []any{"x", "y"}
	if got := AnalyticsReach(Scope{SchoolIDs: []string{"a"}}, &args); !strings.Contains(got, "ANY($3)") || len(args) != 3 {
		t.Errorf("after two arguments: %s with %d", got, len(args))
	}
}

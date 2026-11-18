//go:build integration

package integration

import (
	"context"
	"testing"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/country"
)

// country.SchoolIn reads under whatever alias its caller gives the school,
// "sc" included: its own subqueries must not shadow it (the IA Work Plan's
// projects query named its school "sc" and failed with "column sc.id does
// not exist").
func TestSchoolInReadsUnderAnyAliasItsCallerChooses(t *testing.T) {
	ctx := context.Background()
	var uganda string
	if err := admin.QueryRow(ctx, `SELECT id::text FROM country_registry.country WHERE code = 'UG'`).Scan(&uganda); err != nil {
		t.Fatal(err)
	}
	counts := map[string]int{}
	for _, alias := range []string{"s", "sc", "school"} {
		var n int
		sql := `SELECT count(*) FROM school ` + alias + ` WHERE ` + country.SchoolIn(alias, "$1")
		if err := admin.QueryRow(ctx, sql, []string{uganda}).Scan(&n); err != nil {
			t.Fatalf("alias %q: %v", alias, err)
		}
		counts[alias] = n
	}
	if counts["s"] == 0 || counts["sc"] != counts["s"] || counts["school"] != counts["s"] {
		t.Fatalf("Uganda's schools by alias: %v, want one count above zero", counts)
	}
}

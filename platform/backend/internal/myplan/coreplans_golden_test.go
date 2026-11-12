package myplan

import (
	"context"
	"encoding/json"
	"os"
	"slices"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// The existing code's own Core School Visits and Core School Trainings
// sheets (testdata/core_plans_golden.py, run against the test database
// with its synthetic records in place), and that database through the
// gateway's read-only role: Go lists the same rows, cell for cell and in
// the same order. Skipped without both.
const (
	coreGoldenEnv   = "EDIFY_MYPLAN_CORE_GOLDEN"
	coreGoldenDBEnv = "EDIFY_MYPLAN_CORE_DB"
)

type goldenSheet struct {
	Title   string     `json:"title"`
	Headers []string   `json:"headers"`
	Rows    [][]string `json:"rows"`
}

type coreGolden struct {
	Now   time.Time `json:"now"`
	Cases []struct {
		Label     string      `json:"label"`
		FY        string      `json:"fy"`
		Schools   [][2]string `json:"schools"`
		Visits    goldenSheet `json:"visits"`
		Trainings goldenSheet `json:"trainings"`
	} `json:"cases"`
}

func sameSheet(t *testing.T, label string, got Sheet, want goldenSheet) bool {
	t.Helper()
	if got.Title != want.Title || !slices.Equal(got.Headers, want.Headers) || len(got.Rows) != len(want.Rows) {
		t.Errorf("%s: %q %d rows, want %q %d rows", label, got.Title, len(got.Rows), want.Title, len(want.Rows))
		return false
	}
	same := true
	for i := range want.Rows {
		if !slices.Equal(got.Rows[i], want.Rows[i]) {
			t.Errorf("%s row %d:\n got %q\nwant %q", label, i, got.Rows[i], want.Rows[i])
			same = false
		}
	}
	return same
}

func TestCoreSchoolPlansAreTheExistingCodesSheets(t *testing.T) {
	path, dsn := os.Getenv(coreGoldenEnv), os.Getenv(coreGoldenDBEnv)
	if path == "" || dsn == "" {
		t.Skipf("set %s and %s to compare with the existing code's sheets", coreGoldenEnv, coreGoldenDBEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden coreGolden
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	db, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	sheets, rows, differing, passed := 0, 0, 0, 0
	for _, c := range golden.Cases {
		var schools []CoreSchool
		for _, s := range c.Schools {
			schools = append(schools, CoreSchool{PK: s[0], Code: s[1]})
		}
		visits, trainings, err := CoreSchoolPlans(context.Background(), db, schools, c.FY, golden.Now)
		if err != nil {
			t.Errorf("%s: %v", c.Label, err)
			differing += 2
			continue
		}
		for _, pair := range []struct {
			name string
			got  Sheet
			want goldenSheet
		}{{"visits", visits, c.Visits}, {"trainings", trainings, c.Trainings}} {
			if pair.got.Unported {
				passed++
				continue
			}
			sheets++
			rows += len(pair.want.Rows)
			if !sameSheet(t, c.Label+" "+pair.name, pair.got, pair.want) {
				differing++
			}
		}
	}
	t.Logf("%d sheets (%d rows) compared, %d differing; %d sheets left to the existing code (a partner's completed work)", sheets, rows, differing, passed)
	if sheets == 0 {
		t.Fatal("nothing compared")
	}
}

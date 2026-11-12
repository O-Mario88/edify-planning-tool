package myplan

import (
	"context"
	"encoding/json"
	"net/url"
	"os"
	"strconv"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// The existing code's own counts of a plan (testdata/counts_golden.py, run
// against a database), and the database it ran against: Go counts the same
// plans there and must show the same figures. Skipped without both.
const (
	countsGoldenEnv   = "EDIFY_MYPLAN_COUNTS_GOLDEN"
	countsGoldenDBEnv = "EDIFY_MYPLAN_COUNTS_DB"
)

type countsAnswer struct {
	Email     string            `json:"email"`
	IDs       []string          `json:"ids"`
	Query     map[string]string `json:"query"`
	Strip     []string          `json:"strip"`
	Core      *int              `json:"core"`
	Client    *int              `json:"client"`
	Breakdown []int             `json:"breakdown"`
	PastDue   int               `json:"past_due"`
	Listed    bool              `json:"listed"`
}

func TestThePlanIsCountedAsTheExistingPageCountsIt(t *testing.T) {
	path, dsn := os.Getenv(countsGoldenEnv), os.Getenv(countsGoldenDBEnv)
	if path == "" || dsn == "" {
		t.Skipf("set %s and %s to compare with the existing code's counts", countsGoldenEnv, countsGoldenDBEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var answers []countsAnswer
	if err := json.Unmarshal(raw, &answers); err != nil {
		t.Fatal(err)
	}
	db, err := pgxpool.New(context.Background(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	now := time.Now()
	differing := 0
	for _, a := range answers {
		query := url.Values{}
		for k, v := range a.Query {
			if v != "" {
				query.Set(k, v)
			}
		}
		p, ok := ReadPeriod(query, now)
		if !ok {
			t.Errorf("%s %v: unreadable", a.Email, a.Query)
			continue
		}
		owners := []string{}
		for _, id := range a.IDs {
			if id != "" {
				owners = append(owners, id)
			}
		}
		plan, err := ReadPlan(context.Background(), db, owners, p, ReadFilters(NewQuery(query)), now)
		if err != nil {
			t.Fatal(err)
		}
		c := plan.Counts
		got := []string{comma(c.Week), comma(c.Month), comma(c.Quarter), comma(c.FY),
			comma(c.Visits), comma(c.Trainings), comma(c.Meetings), share(c.Completed, c.Total)}
		same := len(got) == len(a.Strip)
		for i := range got {
			same = same && got[i] == a.Strip[i]
		}
		same = same && a.Core != nil && *a.Core == c.CoreVisits && a.Client != nil && *a.Client == c.ClientVisits &&
			plan.PastDue == a.PastDue && (plan.Listed > 0) == a.Listed &&
			slicesEqual(a.Breakdown, []int{c.Week, c.Month, c.Quarter, c.FY})
		if !same {
			differing++
			t.Errorf("%s %v: go %v core %d client %d past due %d listed %d; existing %v core %v client %v past due %d listed %v",
				a.Email, a.Query, got, c.CoreVisits, c.ClientVisits, plan.PastDue, plan.Listed,
				a.Strip, deref(a.Core), deref(a.Client), a.PastDue, a.Listed)
		}
	}
	t.Logf("%d plans counted, %d differing", len(answers), differing)
}

func slicesEqual(a, b []int) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func deref(n *int) string {
	if n == nil {
		return "none"
	}
	return strconv.Itoa(*n)
}

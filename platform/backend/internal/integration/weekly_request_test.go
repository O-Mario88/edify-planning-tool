//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"

	"connectrpc.com/connect"
)

// weeklyRequestTables is what the golden files, in the order it files them.
var weeklyRequestTables = []string{"weekly_fund_request", "weekly_fund_request_line"}

// The existing feed's Weekly Advance Request over the development seed's
// weekly requests: the officer who holds them on each of their weeks and
// filters, their supervisor and the country readers on the same week,
// readers whose own week holds no work on today, and four of the officer's
// requests the seed lacks (submitted to the PL, returned and self-funded,
// approved and at the Accountant, submitted to the CD). Skipped unless
// EDIFY_WEEKLY_REQUEST_GOLDEN names a file
// internal/weeklyrequest/testdata/golden.py wrote within the last half hour
// (its due dates and default week are today's).
func TestWeeklyRequestMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_WEEKLY_REQUEST_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_WEEKLY_REQUEST_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Rows    map[string][]json.RawMessage `json:"rows"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden was written at %s; write it again", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(weeklyRequestTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gwr%%'`, weeklyRequestTables[i])); err != nil {
				t.Errorf("clearing %s: %v", weeklyRequestTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range weeklyRequestTables {
		for _, row := range golden.Rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing of the Weekly Advance Request")
	}
	compareGolden(t, "/fund-requests/weekly", golden.Answers)
}

// Every reader the Fund Requests page opens for gets an answer from Go or is
// handed on; none meets a database error. The receipt panel's read of the
// monthly plans once lacked its grant, and only an opened page shows that.
func TestWeeklyRequestOpensWithoutADatabaseError(t *testing.T) {
	for _, who := range []string{"cceo@edify.org", "cd@edify.org", "admin@edify.org"} {
		borrowAccount(t, who)
		token := sessionOf(t, who, seededPassword).GetAccessToken()
		if _, err := pageOf(token, "/fund-requests/weekly", nil); connect.CodeOf(err) == connect.CodeInternal {
			t.Fatalf("%s opening Fund Requests: %v", who, err)
		}
	}
}

//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// The existing feed's Verification Queue over work waiting for verification
// the seed lacks (a core visit, an overdue and a fresh visit, a core school,
// a cluster-wide session, another year; partner-delivered work and work with
// no Salesforce ID left out; delivered work with none for the drill-down),
// for the readers the page opens for and those it refuses, each filter, each
// drill-down, a search and the pages of a long drill-down. The ages move
// with the clock, so the answers hold for half an hour. Skipped unless
// EDIFY_IA_VERIFICATION_GOLDEN names a file internal/iapages/testdata/
// verification_golden.py wrote within the half hour.
func TestTheVerificationQueueMatchesTheExistingFeedOverWorkTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_IA_VERIFICATION_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_IA_VERIFICATION_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		hrRegisterGolden
		Written time.Time `json:"written"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden answers were written at %s; their ages have moved", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM activity WHERE id LIKE 'giv%'`); err != nil {
			t.Errorf("clearing the activities: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Rows["activity"] {
		if _, err := admin.Exec(ctx, `INSERT INTO activity SELECT * FROM json_populate_record(NULL::activity, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing an activity: %v", err)
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	if len(answers) == 0 {
		t.Fatal("the golden asks nothing of the Verification Queue")
	}
	compareGolden(t, "/ia/verification/", answers)
}

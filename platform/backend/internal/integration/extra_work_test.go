//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The existing feed's answers over extra assignments (every status, overdue
// and not, long words, enough for one officer to page, another year and its
// approved scoring policy), which the seed does not hold, compared whole.
// Skipped unless EDIFY_EXTRA_WORK_GOLDEN names a file
// internal/extrawork/testdata/golden.py wrote today (overdue moves with the
// clock).
func TestExtraWorkMatchesTheExistingFeedOverAssignmentsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_EXTRA_WORK_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_EXTRA_WORK_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden calendarGolden
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if golden.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the golden answers were written on %s", golden.Today)
	}
	ctx := context.Background()
	tables := []string{"hr_extra_assignment", "hr_extra_work_scoring_policy"}
	clear := func() {
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gew%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range tables {
		for _, row := range golden.Rows[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	tokens := map[string]string{}
	compared, differing := 0, 0
	for _, answer := range golden.Answers {
		token, ok := tokens[answer.Email]
		if !ok {
			borrowAccount(t, answer.Email)
			token = sessionOf(t, answer.Email, seededPassword).GetAccessToken()
			tokens[answer.Email] = token
		}
		got, err := pageOf(token, "/extra-work", answer.Query)
		if answer.Status != 200 {
			if err == nil {
				t.Errorf("%s %v: answered, the feed said %d", answer.Email, answer.Query, answer.Status)
			}
			continue
		}
		if err != nil {
			t.Fatalf("%s %v: %v", answer.Email, answer.Query, err)
		}
		want := &screensv1.GetPageResponse{}
		if err := protojson.Unmarshal(answer.Body, want); err != nil {
			t.Fatalf("the golden answer: %v", err)
		}
		compared++
		if !proto.Equal(got, want) {
			differing++
			t.Errorf("%s %v differs:\n go: %s\n existing: %s", answer.Email, answer.Query,
				shorten(protojson.Format(got)), shorten(protojson.Format(want)))
		}
	}
	t.Logf("%d answers of %d accounts compared, %d differing", compared, len(tokens), differing)
	if compared == 0 {
		t.Fatal("no answer was compared")
	}
}

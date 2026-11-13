//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestTheCalendarOpensOnTheMonthThatHoldsToday(t *testing.T) {
	borrowAccount(t, "cceo1@edify.org")
	token := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/calendar", nil)
	if err != nil {
		t.Fatal(err)
	}
	today := time.Now().In(mustNairobi(t))
	want := today.Month().String() + " " + today.Format("2006")
	blocks := page.GetBlocks()
	if page.GetHeader().GetTitle() != "Calendar" || len(blocks) == 0 {
		t.Fatalf("the page: %v", page)
	}
	rail := blocks[len(blocks)-1].GetSegments()
	if len(rail.GetSegments()) != 5 || rail.GetSegments()[0].GetBlocks()[0].GetPanel().GetTitle() != want {
		t.Fatalf("the month: %v, want %s", rail, want)
	}
	if _, err := pageOf(token, "/calendar", map[string]string{"format": "csv"}); err == nil {
		t.Fatal("a format the feed has no renderer for is answered")
	}
}

func mustNairobi(t *testing.T) *time.Location {
	t.Helper()
	loc, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		t.Fatal(err)
	}
	return loc
}

// calendarGolden is what internal/calendarpage/testdata/golden.py writes:
// the rows it filed and the existing feed's answers over them.
type calendarGolden struct {
	Today   string                       `json:"today"`
	Rows    map[string][]json.RawMessage `json:"rows"`
	Answers []struct {
		Email  string            `json:"email"`
		Query  map[string]string `json:"query"`
		Status int               `json:"status"`
		Body   json.RawMessage   `json:"body"`
	} `json:"answers"`
}

// The existing feed's answers over leave, organization events, recorded
// holidays and work on days off, which the seed does not hold, compared
// whole. Skipped unless EDIFY_CALENDAR_GOLDEN names a file written today
// (the month and its Today move with the clock).
func TestTheCalendarMatchesTheExistingFeedOverRowsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_CALENDAR_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_CALENDAR_GOLDEN is not set")
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
	tables := []string{"public_holiday", "calendar_block", "leave", "activity"}
	clear := func() {
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gcal%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range []string{"activity", "leave", "calendar_block", "public_holiday"} {
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
		got, err := pageOf(token, "/calendar", answer.Query)
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
}

func shorten(s string) string {
	s = strings.Join(strings.Fields(s), " ")
	if len(s) > 4000 {
		return s[:4000] + "…"
	}
	return s
}

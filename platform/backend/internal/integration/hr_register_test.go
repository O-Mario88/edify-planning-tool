//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// hrRegisterGolden is what internal/hrregister/testdata/golden.py writes: the
// rows it filed and the existing feed's answers over them, register by
// register.
type hrRegisterGolden struct {
	Today   string                       `json:"today"`
	Rows    map[string][]json.RawMessage `json:"rows"`
	Answers []struct {
		Email  string            `json:"email"`
		Path   string            `json:"path"`
		Query  map[string]string `json:"query"`
		Status int               `json:"status"`
		Body   json.RawMessage   `json:"body"`
	} `json:"answers"`
}

// The existing feed's answers over People records the seed does not hold
// (enough to page, every lifecycle state, lines and none, another country, a
// deleted record and a deleted account), compared whole. Skipped unless
// EDIFY_HR_REGISTER_GOLDEN names a file internal/hrregister/testdata/
// golden.py wrote today.
func TestTheHRRegistersMatchTheExistingFeedOverPeopleTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_HR_REGISTER_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_HR_REGISTER_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden hrRegisterGolden
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if golden.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the golden answers were written on %s", golden.Today)
	}
	ctx := context.Background()
	// Children first; only the golden's own rows (ids starting "ghr").
	children := []string{"staff_supervisor_assignment", "staff_profile", "user"}
	clear := func() {
		for _, table := range children {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'ghr%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range []string{"user", "staff_profile", "staff_supervisor_assignment"} {
		for _, row := range golden.Rows[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO "`+table+`" SELECT * FROM json_populate_record(NULL::"`+table+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	byPath := map[string][]goldenAnswer{}
	for _, a := range golden.Answers {
		byPath[a.Path] = append(byPath[a.Path], goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	if len(byPath) == 0 {
		t.Fatal("no answer to compare")
	}
	for path, answers := range byPath {
		compareGolden(t, path, answers)
	}
}

//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/acting"
)

// The existing feed's Acting Leadership over appointments the seed lacks (an
// officer acting this month, another next month, one ended, one cancelled,
// and a Lead acting as Country Director next month), for the Programme
// Lead, the officer appointed for next month, the Country Director, HR, IA,
// the Admin and the Accountant it refuses. Someone acting this month works
// in the acting seat, which the existing application answers. Skipped unless EDIFY_ACTING_PAGE_GOLDEN names a
// file internal/acting/testdata/page_golden.py wrote within the hour.
func TestActingLeadershipMatchesTheExistingFeed(t *testing.T) {
	path := os.Getenv("EDIFY_ACTING_PAGE_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ACTING_PAGE_GOLDEN is not set")
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
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM acting_assignment WHERE id LIKE 'gac%'`); err != nil {
			t.Errorf("clearing the appointments: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Rows["acting_assignment"] {
		if _, err := admin.Exec(ctx, `INSERT INTO acting_assignment SELECT * FROM json_populate_record(NULL::acting_assignment, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing an appointment: %v", err)
		}
	}
	compareGolden(t, acting.PagePath, golden.Answers)
}

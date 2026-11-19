//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestTheVerificationNotificationsMatchTheExistingPage files the notices
// internal/iapages/testdata/notifications_golden.py filed (fifty-two to
// Impact Assessment under the verification categories, one under another
// category, one to someone else), asks /ia/notifications/ as each reader the
// golden asked, and compares the whole page. Skipped unless
// EDIFY_IA_NOTIFICATIONS_GOLDEN names that file, written within the hour.
func TestTheVerificationNotificationsMatchTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_IA_NOTIFICATIONS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_IA_NOTIFICATIONS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM notification WHERE id LIKE 'gian%'`); err != nil {
			t.Errorf("clearing the notices: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Tables["notification"] {
		if _, err := admin.Exec(ctx, `INSERT INTO notification SELECT * FROM json_populate_record(NULL::notification, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a notice: %v", err)
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/ia/notifications/", golden.Answers)
}

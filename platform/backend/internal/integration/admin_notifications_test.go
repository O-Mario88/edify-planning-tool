//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestTheNotificationLogsMatchTheExistingPage files the notifications
// internal/adminpanel/testdata/notifications_golden.py filed (fifty-one
// dated tomorrow), asks /admin-panel/notifications-mgmt as each reader the
// golden asked, and compares the whole page. Skipped unless
// EDIFY_ADMIN_NOTIFICATIONS_GOLDEN names that file, written within the hour.
func TestTheNotificationLogsMatchTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_ADMIN_NOTIFICATIONS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_ADMIN_NOTIFICATIONS_GOLDEN is not set")
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
		if _, err := admin.Exec(ctx, `DELETE FROM notification WHERE id LIKE 'gnmg%'`); err != nil {
			t.Errorf("clearing the notifications: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Tables["notification"] {
		if _, err := admin.Exec(ctx, `INSERT INTO notification SELECT * FROM json_populate_record(NULL::notification, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a notification: %v", err)
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/admin-panel/notifications-mgmt", golden.Answers)
}

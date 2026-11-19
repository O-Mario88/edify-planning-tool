//go:build integration

package integration

import "testing"

// TestTodayMatchesTheExistingPage compares /today as the database stands,
// then under the snoozes and cleared decisions
// internal/todaypage/testdata/golden.py filed.
func TestTodayMatchesTheExistingPage(t *testing.T) {
	t.Run("as it stands", func(t *testing.T) {
		compareFiledPage(t, "EDIFY_TODAY_GOLDEN", "gtdy", "/today")
	})
	t.Run("snoozed and cleared", func(t *testing.T) {
		compareFiledPage(t, "EDIFY_TODAY_FILED_GOLDEN", "gtdy", "/today", "command_center_todo_snooze", "command_center_today_action")
	})
}

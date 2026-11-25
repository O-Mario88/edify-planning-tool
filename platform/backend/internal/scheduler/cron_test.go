package scheduler

import (
	"testing"
	"time"
)

func TestTheJobsFireWhenTheExistingSchedulerFiresThem(t *testing.T) {
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		t.Fatal(err)
	}
	schedules, err := djangoSchedules(kampala)
	if err != nil {
		t.Fatal(err)
	}
	if len(schedules) != 41 {
		t.Fatalf("%d schedules, want the registry's 41", len(schedules))
	}
	// Wednesday 25 November 2026, 05:12 in Kampala.
	from := time.Date(2026, 11, 25, 5, 12, 30, 0, kampala)
	cases := map[string]string{
		"weekly_fund_request":        "2026-11-27 06:00", // Friday 06:00
		"monthly_work_plan":          "2026-11-25 06:00", // the 25th, today
		"notification_escalation":    "2026-11-25 06:00", // hourly :00
		"daily_plan_notifications":   "2026-11-25 06:45",
		"daily_debrief_reminders":    "2026-11-25 08:00", // 08:00 and 18:00
		"weekly_debrief_reports":     "2026-11-30 06:00", // Monday
		"target_ledger_sync":         "2026-11-25 05:30", // every 30 minutes
		"hand_in_entered_work":       "2026-11-25 05:25",
		"outbox_drain":               "2026-11-25 05:13",
		"autopilot_weekly_proposals": "2026-11-27 05:00",
		"closure_checklist_refresh":  "2026-11-25 05:40",
		"planning_oversight_warm":    "2026-11-25 05:16", // every 4 minutes
	}
	for name, want := range cases {
		c, ok := schedules[name]
		if !ok {
			t.Fatalf("no schedule for %s", name)
		}
		if got := c.Next(from).Format("2006-01-02 15:04"); got != want {
			t.Errorf("%s next = %s, want %s", name, got, want)
		}
	}
	// Twice in a row: 18:00 follows 08:00.
	c := schedules["daily_debrief_reminders"]
	if got := c.Next(c.Next(from)).Format("15:04"); got != "18:00" {
		t.Errorf("the second debrief reminder fires at %s", got)
	}
}

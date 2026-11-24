package activities

import (
	"errors"
	"testing"
)

func TestAttendanceCountsReadAsPythonsInt(t *testing.T) {
	tests := []struct {
		raw     string
		want    int
		refusal string
		handOn  bool
	}{
		{"", 0, "", false},
		{"12", 12, "", false},
		{" 7 ", 7, "", false},
		{"+3", 3, "", false},
		{"0", 0, "", false},
		{"-1", 0, "teachersAttended cannot be negative.", false},
		{"abc", 0, "teachersAttended must be a whole number.", false},
		{"1.5", 0, "teachersAttended must be a whole number.", false},
		{"1_000", 0, "", true},
		{"99999999999999999999", 0, "", true},
	}
	for _, tt := range tests {
		got, err := attendanceCountOf("teachersAttended", tt.raw)
		var refusal *Refusal
		switch {
		case tt.handOn:
			if !errors.Is(err, ErrHandOn) {
				t.Fatalf("%q: want hand-on, got %d, %v", tt.raw, got, err)
			}
		case tt.refusal != "":
			if !errors.As(err, &refusal) || refusal.Message != tt.refusal {
				t.Fatalf("%q: got %d, %v", tt.raw, got, err)
			}
		case err != nil || got != tt.want:
			t.Fatalf("%q: got %d, %v", tt.raw, got, err)
		}
	}
}

func TestAttendanceIsRefusedOnceTheWorkIsClosed(t *testing.T) {
	for _, status := range []string{"closed", "cancelled", "rejected", "deferred"} {
		if !attendanceClosed(status) {
			t.Fatalf("%s takes no attendance", status)
		}
	}
	for _, status := range []string{"scheduled", "completion_started", "completed", "returned_by_pl"} {
		if attendanceClosed(status) {
			t.Fatalf("%s takes attendance", status)
		}
	}
}

func TestTheAttendanceAuditKeepsThePostedValues(t *testing.T) {
	got := attendanceAuditPayload(map[string][]string{"teachers_attended": {"12"}, "notes": {"  sheet signed  "}})
	if got["teachers"] != "12" || got["leaders"] != 0 || got["notes"] != "sheet signed" {
		t.Fatalf("got %#v", got)
	}
}

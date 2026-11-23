package plreview

import (
	"slices"
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

func TestReturnNoteIsWhatTheExistingComposeWrites(t *testing.T) {
	ticks := []string{"Participants not entered in Salesforce", " Wrong school, cluster or activity date "}
	cases := []struct {
		name    string
		reasons []string
		written string
		want    string
	}{
		{"both", ticks, " Enter the 12 teachers. ", "Participants not entered in Salesforce; Wrong school, cluster or activity date — Enter the 12 teachers."},
		{"ticks only", ticks, "  ", "Participants not entered in Salesforce; Wrong school, cluster or activity date"},
		{"words only", nil, "Enter the 12 teachers.", "Enter the 12 teachers."},
		{"nothing", []string{" "}, "", ""},
	}
	for _, tc := range cases {
		if got := composeReturnNote(tc.reasons, tc.written); got != tc.want {
			t.Errorf("%s: got %q, want %q", tc.name, got, tc.want)
		}
	}
}

func TestALongReturnNoteIsCutWithAVisibleMarker(t *testing.T) {
	got := composeReturnNote(nil, strings.Repeat("é", 600))
	if utf8.RuneCountInString(got) != maxReturnNote || !strings.HasSuffix(got, "…") {
		t.Fatalf("%d characters: %q", utf8.RuneCountInString(got), got[len(got)-8:])
	}
	spaced := composeReturnNote(nil, strings.Repeat("a", 510)+"  "+strings.Repeat("b", 20))
	if !strings.HasSuffix(spaced, "a…") {
		t.Fatalf("the cut keeps no trailing space: %q", spaced[len(spaced)-6:])
	}
}

func TestTheViewsAuditReasonJoinsTheTicksAndTheWords(t *testing.T) {
	if got := returnAuditReason([]string{"A", "B"}, "C"); got != "A; B; C" {
		t.Errorf("both: %q", got)
	}
	if got := returnAuditReason([]string{"A", "B"}, ""); got != "A; B" {
		t.Errorf("ticks: %q", got)
	}
}

func TestTickedReasonsSurviveTheCommaJoinedValue(t *testing.T) {
	wrong := "Wrong school, cluster or activity date"
	value := "Participants not entered in Salesforce," + ReturnReasonValue(wrong)
	got := TickedReasons(value)
	if !slices.Equal(got, []string{"Participants not entered in Salesforce", wrong}) {
		t.Fatalf("%q", got)
	}
	if strings.Contains(ReturnReasonValue(wrong), ",") {
		t.Fatalf("a checklist value cannot hold a comma: %q", ReturnReasonValue(wrong))
	}
	if got := TickedReasons(""); len(got) != 0 {
		t.Fatalf("nothing ticked: %q", got)
	}
}

func TestTimesAreWrittenAsPythonsIsoformat(t *testing.T) {
	at := time.Date(2026, 11, 23, 15, 36, 59, 113927000, time.FixedZone("EAT", 3*3600))
	if got := pythonISO(at); got != "2026-11-23T12:36:59.113927+00:00" {
		t.Errorf("with microseconds: %q", got)
	}
	whole := time.Date(2026, 11, 23, 12, 36, 59, 0, time.UTC)
	if got := pythonISO(whole); got != "2026-11-23T12:36:59+00:00" {
		t.Errorf("a whole second: %q", got)
	}
}

func TestADecisionRaisesTheExistingEvents(t *testing.T) {
	at := time.Date(2026, 11, 23, 12, 0, 0, 500000000, time.UTC)
	const version = "2026-11-23T12:00:00.500000+00:00"
	keys := func(events []outboxEvent) []string {
		out := make([]string, 0, len(events))
		for _, e := range events {
			out = append(out, e.Type+"|"+e.Key)
		}
		return out
	}
	verified := keys(reviewEvents(Review{ID: "a1", SchoolID: "s1", ProjectID: "p1"}, statusVerified, at, true))
	if !slices.Equal(verified, []string{
		"bt.activity.state_changed|bt.activity.state:a1:ia_verified:" + version,
		"projects.impact.refresh|projects.impact:s1:activity:a1:" + version,
		"integrations.salesforce.activity|sf:activity:a1",
	}) {
		t.Errorf("verified: %v", verified)
	}
	plain := keys(reviewEvents(Review{ID: "a1", SchoolID: "s1"}, statusVerified, at, false))
	if !slices.Equal(plain, []string{"bt.activity.state_changed|bt.activity.state:a1:ia_verified:" + version}) {
		t.Errorf("no project, sync off: %v", plain)
	}
	noSchool := keys(reviewEvents(Review{ID: "a1", ProjectID: "p1"}, statusVerified, at, false))
	if len(noSchool) != 1 {
		t.Errorf("no school to refresh: %v", noSchool)
	}
	returned := keys(reviewEvents(Review{ID: "a1", SchoolID: "s1", ProjectID: "p1"}, statusReturnedByPL, at, true))
	if !slices.Equal(returned, []string{"bt.activity.state_changed|bt.activity.state:a1:returned_by_pl:" + version}) {
		t.Errorf("returned: %v", returned)
	}
	earlier := time.Date(2026, 1, 2, 3, 4, 5, 0, time.UTC)
	again := keys(reviewEvents(Review{ID: "a1", IAConfirmedAt: &earlier}, statusReturnedByPL, at, false))
	if !slices.Equal(again, []string{"bt.activity.state_changed|bt.activity.state:a1:returned_by_pl:2026-01-02T03:04:05+00:00"}) {
		t.Errorf("a return after an earlier confirmation keeps that version: %v", again)
	}
}

func TestMayDecideIsTheViewsDoorBeforeTheRecordsState(t *testing.T) {
	lead := reviewerReach{clearsOwn: true, own: []string{"u-lead"}, supervised: []string{"sp-officer"}}
	cases := []struct {
		name string
		work reviewCase
		by   reviewerReach
		want bool
	}{
		{"the Admin", reviewCase{owner: ""}, reviewerReach{admin: true}, true},
		{"no owner", reviewCase{owner: ""}, lead, false},
		{"own staff work", reviewCase{owner: "u-lead"}, lead, true},
		{"own partner work", reviewCase{owner: "u-lead", deliveryType: partnerDelivery}, lead, false},
		{"a supervisee, whatever the status", reviewCase{owner: "sp-officer", status: "closed"}, lead, true},
		{"someone else's officer", reviewCase{owner: "sp-other"}, lead, false},
	}
	for _, tc := range cases {
		if got := mayDecide(tc.work, tc.by); got != tc.want {
			t.Errorf("%s: got %v", tc.name, got)
		}
	}
}

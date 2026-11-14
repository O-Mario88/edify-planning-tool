package staffactivity

import (
	"encoding/json"
	"os"
	"slices"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func at(day, hour, minute int) time.Time {
	return time.Date(2026, time.November, day, hour, minute, 0, 0, zone)
}

func ptr(s string) *string { return &s }

// Two made-up people (testdata/person_golden.py) drawn by the template and
// read by the feed: follow-ups, suggestions, a current session, a linked and
// a plain action, the empty boxes and the Admin's missing Follow up.
func TestAPersonsDetailReadsAsThePageDrawsIt(t *testing.T) {
	raw, err := os.ReadFile("testdata/person_golden.json")
	if err != nil {
		t.Fatal(err)
	}
	golden := map[string]json.RawMessage{}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	week := period{key: "week", on: civil(2026, time.November, 11), label: "Week of 9 Nov 2026"}
	today := civil(2026, time.November, 11)
	cases := map[string]*detail{
		"busy": {
			x: &person{
				id: "gpsa-p1", name: "Grace  A. Okello", status: "online", title: "CCEO", region: "Central", supervisor: "Ruth Lead",
				logins: 12, seconds: 7500, failed: 4, reasons: []string{"low_engagement", "repeated_errors"},
			},
			p: week, today: today, canFollowUp: true, sessionTotal: 12,
			sessions: []session{
				{at: at(11, 8, 5), device: "Phone", span: 3630, active: 3600, ended: "Current session"},
				{at: at(10, 17, 30), device: "Unknown", span: 300, ended: "Signed out 10/11 17:35"},
			},
			tasks:   1,
			modules: [][3]string{{"Planning", "1h 05m", "1 action"}, {"Clusters", "0m", "2 actions"}},
			timeline: []act{
				{at: at(11, 8, 10), ok: true, label: "Scheduled a visit", module: "Planning", subjectKind: ptr("Activity"), subjectI: ptr("gpsa-a1")},
				{at: at(10, 17, 31), ok: true, label: "Set a cluster's partner facilitator", module: "Clusters", subjectKind: ptr("Cluster"), subjectI: ptr("c1")},
			},
			actsTotal: 3, trend: []string{"Mon", "Tue", "Wed"}, loginDays: 1,
			followUps: [][3]string{
				{"gpsa-f1", choice(rules.Person.FollowUpTriggers, "repeated_errors"), ""},
				{"gpsa-f2", choice(rules.Person.FollowUpTriggers, "excessive_time"), ""},
			},
		},
		"quiet": {
			x:            &person{id: "gpsa-p2", name: "Ann", status: "on_leave", title: "Programme Lead"},
			p:            week,
			today:        today,
			sessionTotal: 1,
		},
	}
	for name, d := range cases {
		want := &screensv1.GetPageResponse{}
		if err := (protojson.UnmarshalOptions{DiscardUnknown: false}).Unmarshal(golden[name], want); err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		got := personBlocks(d, d.x.id)
		if !proto.Equal(got, want) {
			t.Errorf("%s:\n got %v\nwant %v", name, got, want)
		}
	}
}

func TestAnEchoIsNamedByThePlainRowAndARefusalStandsAlone(t *testing.T) {
	var echo, plain string
	for action, d := range rules.MeaningfulActions {
		if d.Secondary && echo == "" {
			echo = action
		}
		if !d.Secondary && plain == "" {
			plain = action
		}
	}
	if echo == "" || plain == "" {
		t.Skip("the registry has no echo action")
	}
	acts := foldActs([]auditRow{
		{id: "3", action: echo, success: true, at: at(11, 9, 2), correlation: ptr("req"), kind: ptr("school"), subject: ptr("s1")},
		{id: "2", action: plain, success: true, at: at(11, 9, 1), correlation: ptr("req"), kind: ptr("school"), subject: ptr("s1")},
		{id: "1", action: plain, success: false, at: at(11, 9, 0), correlation: ptr("req"), kind: ptr("school"), subject: ptr("s1")},
		{id: "0", action: rules.FailedRequestActions[0], success: false, at: at(11, 8, 0)},
		{id: "9", action: plain, success: true, at: at(11, 7, 0), correlation: ptr(""), kind: ptr("school"), subject: ptr("s1")},
		{id: "8", action: plain, success: true, at: at(11, 6, 0), correlation: nil, kind: ptr("school"), subject: ptr("s1")},
	})
	if len(acts) != 5 {
		t.Fatalf("got %d actions, want 5: %+v", len(acts), acts)
	}
	first := acts[0]
	if !first.ok || first.label != rules.MeaningfulActions[plain].Label || !first.at.Equal(at(11, 9, 2)) {
		t.Errorf("the echo was not renamed by its plain row: %+v", first)
	}
	if acts[1].ok || acts[1].label != "A request failed" || acts[2].ok {
		t.Errorf("refusals must stand alone and fail: %+v %+v", acts[1], acts[2])
	}
	if !acts[3].ok || !acts[4].ok {
		t.Errorf("rows with no request are each an action: %+v", acts[3:])
	}
}

func TestThePeriodTrendIsADayAWeekOrAMonth(t *testing.T) {
	today := civil(2026, time.November, 13)
	for _, c := range []struct {
		key, on string
		want    []string
	}{
		{"day", "", []string{"Fri"}},
		{"week", "", []string{"Mon", "Tue", "Wed", "Thu", "Fri"}},
		{"week", "2026-11-20", nil},
		{"month", "2026-10-15", nil},
		{"fy", "", []string{"28 Sep", "05 Oct", "12 Oct", "19 Oct", "26 Oct", "02 Nov", "09 Nov"}},
		{"fy", "2026-06-01", []string{"Oct", "Nov", "Dec", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep"}},
	} {
		got := trendLabels(choosePeriod(c.key, c.on, today))
		if c.key == "month" {
			if len(got) != 31 || got[0] != "Thu 01" || got[30] != "Sat 31" {
				t.Errorf("month: %v", got)
			}
			continue
		}
		if !slices.Equal(got, c.want) {
			t.Errorf("%s %s: got %v, want %v", c.key, c.on, got, c.want)
		}
	}
}

func TestAPersonsAddressAndTheirFollowUpsWords(t *testing.T) {
	for path, want := range map[string]string{
		"/staff-activity/people/abc": "abc", "/staff-activity/people/": "", "/staff-activity/people/abc/follow-up": "",
		"/staff-activity": "", "/staff-activity/people/a b": "a b",
	} {
		if got, ok := personID(path); got != want || ok != (want != "") {
			t.Errorf("%s: got %q %v", path, got, ok)
		}
	}
	if got := choice(rules.Person.FollowUpStatuses, "returned"); got != "Returned for clarification" {
		t.Errorf("status: %q", got)
	}
	if got := choice(rules.Person.FollowUpStatuses, "made-up"); got != "made-up" {
		t.Errorf("an unknown status shows as stored: %q", got)
	}
	if got := jM(civil(2026, time.March, 5)); got != "5 Mar" {
		t.Errorf("due: %q", got)
	}
}

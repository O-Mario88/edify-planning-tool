package plreview

import (
	"encoding/base64"
	"os"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/pydecimal"
)

func TestACreditRuleMatchesAsTheExistingRuleDoes(t *testing.T) {
	work := creditFacts{Project: "p1", Delivery: "staff", Method: "in_person", HasSchool: true, SchoolType: "champion", Intervention: "leadership"}
	cases := []struct {
		name string
		rule creditRule
		want bool
	}{
		{"no conditions", creditRule{}, true},
		{"its project", creditRule{Project: "p1"}, true},
		{"another project", creditRule{Project: "p2"}, false},
		{"its executor", creditRule{Executor: "staff"}, true},
		{"another executor", creditRule{Executor: "partner"}, false},
		{"its delivery method", creditRule{Method: "in_person"}, true},
		{"another delivery method", creditRule{Method: "online"}, false},
		{"a family holding the school's type", creditRule{SchoolType: "core"}, true},
		{"a family without it", creditRule{SchoolType: "client"}, false},
		{"the type itself", creditRule{SchoolType: "champion"}, true},
		{"its intervention", creditRule{Intervention: "leadership"}, true},
		{"another intervention", creditRule{Intervention: "enrolment"}, false},
		{"a school level, which no school record carries", creditRule{SchoolLevel: "primary"}, false},
	}
	for _, tc := range cases {
		if got := tc.rule.matches(work); got != tc.want {
			t.Errorf("%s: got %v", tc.name, got)
		}
	}
	if (creditRule{SchoolType: "core"}).matches(creditFacts{}) {
		t.Error("work at no school cannot meet a school-type rule")
	}
}

func TestOneMilestoneEarnsOneCredit(t *testing.T) {
	work := creditFacts{Delivery: "staff"}
	rules := []creditRule{
		{ID: "r1", Milestone: "m1"},
		{ID: "r2", Milestone: "m2", Executor: "partner"},
		{ID: "r3", Milestone: "m3"},
	}
	planned := plannedCredits(rules, work, map[string]bool{"m3": true})
	if len(planned) != 1 || planned[0].ID != "r1" {
		t.Fatalf("planned=%v", planned)
	}
}

func TestTheFirstMatchingRuleEarnsAMilestonesCredit(t *testing.T) {
	rules := []creditRule{{ID: "r1", Milestone: "m1"}, {ID: "r2", Milestone: "m1"}}
	planned := plannedCredits(rules, creditFacts{}, map[string]bool{})
	if len(planned) != 1 || planned[0].ID != "r1" {
		t.Fatalf("planned=%v", planned)
	}
	if got := plannedCredits(rules, creditFacts{}, map[string]bool{"m1": true}); len(got) != 0 {
		t.Fatalf("a milestone already credited earns no other: %v", got)
	}
}

func TestAReversedCreditComesBackOnlyWhenItsRuleStillMatches(t *testing.T) {
	work := creditFacts{Catalogue: "c1", Delivery: "staff"}
	reversed := []reversedCredit{
		{ID: "x1", Rule: creditRule{Milestone: "m1", Catalogue: "c1"}},
		{ID: "x2", Rule: creditRule{Milestone: "m2", Catalogue: "c1", Executor: "partner"}},
		{ID: "x3", Rule: creditRule{Milestone: "m3", Catalogue: "another"}},
	}
	ids, milestones := revivedCredits(reversed, work)
	if !slices.Equal(ids, []string{"x1"}) || !slices.Equal(milestones, []string{"m1"}) {
		t.Fatalf("ids=%v milestones=%v", ids, milestones)
	}
}

func TestAPeriodTargetsFiguresAreTheExistingEngines(t *testing.T) {
	dec := pydecimal.MustParse
	denominator := dec("50")
	zero := dec("0")
	cases := []struct {
		name                         string
		actual, planned              string
		denominator                  *pydecimal.Decimal
		rate, capped                 bool
		wantActual, wantAchieved, st string
	}{
		{name: "a count on its way", actual: "3", planned: "10", wantActual: "3", wantAchieved: "30", st: "in_progress"},
		{name: "a count met", actual: "10", planned: "10", wantActual: "10", wantAchieved: "100", st: "achieved"},
		{name: "nothing yet", actual: "0", planned: "10", wantActual: "0", wantAchieved: "0", st: "not_started"},
		{name: "no plan", actual: "4", planned: "0", wantActual: "4", wantAchieved: "0", st: "in_progress"},
		{name: "the database does the rounding", actual: "1", planned: "160", wantActual: "1", wantAchieved: "0.625", st: "in_progress"},
		{name: "a rate over its schools", actual: "45", planned: "90", denominator: &denominator, rate: true, wantActual: "45", wantAchieved: "100", st: "achieved"},
		{name: "a rate past its schools, capped", actual: "60", planned: "90", denominator: &denominator, rate: true, capped: true, wantActual: "60", wantAchieved: "111.11", st: "achieved"},
		{name: "a rate past its schools, not capped", actual: "60", planned: "90", denominator: &denominator, rate: true, wantActual: "60", wantAchieved: "133.33", st: "achieved"},
		{name: "a rate with no denominator", actual: "45", planned: "90", rate: true, wantActual: "45", wantAchieved: "0", st: "in_progress"},
		{name: "a rate with a zero denominator", actual: "45", planned: "90", denominator: &zero, rate: true, wantActual: "45", wantAchieved: "0", st: "in_progress"},
	}
	for _, tc := range cases {
		got := figuresFor(dec(tc.actual), dec(tc.planned), tc.denominator, tc.rate, tc.capped)
		if dec(got.Actual).Cmp(dec(tc.wantActual)) != 0 || !strings.HasPrefix(got.Achievement, tc.wantAchieved) || got.Status != tc.st {
			t.Errorf("%s: got %+v", tc.name, got)
		}
	}
}

func TestOnlyADeviceThisDeploymentCanReachIsQueued(t *testing.T) {
	apple := strings.Repeat("a", 64)
	cases := []struct {
		name         string
		ready        PushReadiness
		kind, target string
		want         bool
	}{
		{"web with its keys", PushReadiness{Web: true}, "web", "https://x", true},
		{"web without", PushReadiness{FCM: true}, "web", "https://x", false},
		{"android through Firebase", PushReadiness{FCM: true}, "android", "token", true},
		{"android without", PushReadiness{APNS: true}, "android", "token", false},
		{"an Apple token through Apple", PushReadiness{APNS: true}, "ios", apple, true},
		{"an Apple token without Apple's key", PushReadiness{FCM: true}, "ios", apple, false},
		{"a Firebase token on an iPhone", PushReadiness{FCM: true}, "ios", "firebase:token", true},
		{"a Firebase token without Firebase", PushReadiness{APNS: true}, "ios", "firebase:token", false},
		{"nothing configured", PushReadiness{}, "web", "https://x", false},
	}
	for _, tc := range cases {
		if got := tc.ready.reaches(tc.kind, tc.target); got != tc.want {
			t.Errorf("%s: got %v", tc.name, got)
		}
	}
}

func TestPushReadinessIsReadFromTheExistingSettings(t *testing.T) {
	account := `{"project_id":"p","client_email":"c@example.org","private_key":"k"}`
	env := func(values map[string]string) func(string) string {
		return func(name string) string { return values[name] }
	}
	noFile := func(string) ([]byte, error) { return nil, os.ErrNotExist }
	full := PushReadinessFrom(env(map[string]string{
		"WEBPUSH_VAPID_PUBLIC_KEY": "pub", "WEBPUSH_VAPID_PRIVATE_KEY": "priv",
		"FCM_SERVICE_ACCOUNT_JSON": account,
		"APNS_KEY_ID":              "k", "APNS_TEAM_ID": "t", "APNS_PRIVATE_KEY": "p",
	}), noFile)
	if full != (PushReadiness{Web: true, FCM: true, APNS: true}) {
		t.Fatalf("full: %+v", full)
	}
	encoded := PushReadinessFrom(env(map[string]string{
		"FCM_SERVICE_ACCOUNT_JSON": base64.StdEncoding.EncodeToString([]byte(account)),
	}), noFile)
	if !encoded.FCM {
		t.Fatal("a base64 account should count")
	}
	fromFile := PushReadinessFrom(env(map[string]string{"FCM_SERVICE_ACCOUNT_FILE": "/k.json"}),
		func(string) ([]byte, error) { return []byte(account), nil })
	if !fromFile.FCM {
		t.Fatal("an account in a file should count")
	}
	broken := PushReadinessFrom(env(map[string]string{
		"WEBPUSH_VAPID_PUBLIC_KEY": "pub",
		"FCM_SERVICE_ACCOUNT_JSON": `{"project_id":"p"}`,
		"APNS_KEY_ID":              "k",
	}), noFile)
	if broken != (PushReadiness{}) {
		t.Fatalf("half-set keys reach nothing: %+v", broken)
	}
}

func TestAConfirmedSSARaisesTheExistingEvents(t *testing.T) {
	at := time.Date(2026, 11, 23, 12, 0, 0, 250000000, time.UTC)
	const version = "2026-11-23T12:00:00.250000+00:00"
	got := []string{}
	for _, e := range confirmedSSAEvents("r1", "s1", at) {
		got = append(got, e.Type+"|"+e.Key)
	}
	want := []string{
		"bt.ssa.confirmed|bt.ssa.confirmed:r1:" + version,
		"ssa.recommendations.generate|ssa.recommendations:r1:" + version,
		"projects.impact.refresh|projects.impact:s1:ssa:" + version,
		"projects.baselines.capture|projects.baselines.capture:s1:ssa:r1:confirmed",
	}
	if !slices.Equal(got, want) {
		t.Fatalf("got %v", got)
	}
}

func TestACreditNeedsItsSalesforceReference(t *testing.T) {
	cases := []struct {
		recordType, id string
		want           bool
	}{
		{"NONE", "", true},
		{"VISIT", "SV-1", true},
		{"VISIT", "   ", false},
		{"", "", false},
		{"none", "", false},
	}
	for _, tc := range cases {
		if got := salesforceSatisfied(tc.recordType, tc.id); got != tc.want {
			t.Errorf("%q %q: got %v", tc.recordType, tc.id, got)
		}
	}
}

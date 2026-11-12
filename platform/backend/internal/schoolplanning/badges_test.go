package schoolplanning

import (
	"slices"
	"testing"
	"time"
)

func labels(chips []Chip) []string {
	out := []string{}
	for _, c := range chips {
		out = append(out, c.Label)
	}
	return out
}

func TestAStatusFallsInTheExistingBucket(t *testing.T) {
	for status, want := range map[string]string{
		"scheduled": bucketPlanned, "partner_scheduled": bucketPlanned, "completion_started": bucketPlanned,
		"evidence_uploaded": bucketAwaiting, "completed": bucketAwaiting, "submitted_to_pl": bucketAwaiting,
		"ia_verified": bucketVerified, "closed": bucketVerified,
		"returned_by_pl": bucketReplan,
		"cancelled":      "", "not_planned": "", "awaiting_owner_approval": "",
	} {
		if got := bucketOf(status); got != want {
			t.Errorf("%s: %q, want %q", status, got, want)
		}
	}
}

func TestTheActivitysOwnTypeDecidesItsBadgeFirst(t *testing.T) {
	cases := []struct {
		activityType string
		flag         bool
		want         string
	}{
		{"school_visit", true, KindVisits},
		{"cluster_training", false, KindTrainings},
		{"cluster_meeting", false, KindClusterMeetings},
		{"cluster_meeting", true, KindTrainings},
		{"project_activity", true, KindTrainings},
		{"project_activity", false, ""},
	}
	for _, c := range cases {
		if got := kindOf(c.activityType, c.flag); got != c.want {
			t.Errorf("%s (counts as training %v): %q, want %q", c.activityType, c.flag, got, c.want)
		}
	}
}

func TestChipsReadInOrderAndNameTheirKind(t *testing.T) {
	c := Counts{Planned: 1, Verified: 2, Replan: 1}
	if got := labels(c.Chips("")); !slices.Equal(got, []string{"1 Planned", "2 Complete", "1 Needs Replanning"}) {
		t.Errorf("chips %v", got)
	}
	b := Badges{ClusterMeetings: Counts{Awaiting: 1}}
	if got := labels(b.ClusterMeetingChips()); !slices.Equal(got, []string{"1 Cluster Meeting Awaiting Verification"}) {
		t.Errorf("meeting chips %v", got)
	}
}

func TestAPlannedMeetingIsTrainingPlannedForTheSchool(t *testing.T) {
	if got := labels((Badges{}).TrainingChips()); !slices.Equal(got, []string{"Not Planned"}) {
		t.Errorf("nothing planned: %v", got)
	}
	// A meeting alone: the training cell names no training count, and the
	// meeting chip beside it says what is planned.
	if got := labels((Badges{ClusterMeetings: Counts{Planned: 1}}).TrainingChips()); len(got) != 0 {
		t.Errorf("a meeting only: %v", got)
	}
	if got := labels((Badges{}).VisitChips()); !slices.Equal(got, []string{"Not Planned"}) {
		t.Errorf("visits: %v", got)
	}
}

func TestADayIsThePlannedDateElseTheLocalDayOfTheSchedule(t *testing.T) {
	planned := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)
	// Midnight in Nairobi is 21:00 UTC the day before.
	scheduled := time.Date(2026, 11, 20, 21, 0, 0, 0, time.UTC)
	if got := dayOf(&planned, &scheduled); got.Day() != 20 {
		t.Errorf("planned wins: %v", got)
	}
	if got := dayOf(nil, &scheduled); got.Day() != 21 {
		t.Errorf("scheduled is read on Nairobi's clock: %v", got)
	}
	if dayOf(nil, nil) != nil {
		t.Error("no date, no day")
	}
}

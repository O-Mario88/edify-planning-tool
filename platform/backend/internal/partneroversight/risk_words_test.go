package partneroversight

import (
	"slices"
	"testing"
	"time"
)

// The drawer's worded risks are the page's risks: the same keys for every
// stage, status, evidence and payment state, worst first.
func TestRisksWithWordsAreThePagesRisks(t *testing.T) {
	today := time.Date(2026, 11, 25, 0, 0, 0, 0, time.UTC)
	day := func(n int) *time.Time { d := today.AddDate(0, 0, n); return &d }
	zero, cost := int64(0), int64(40000)
	for _, stage := range []string{stageAwaiting, stageScheduled, stageReturned} {
		for _, assigned := range []*time.Time{nil, day(-30), day(-8), day(-5)} {
			for _, status := range []string{"scheduled", "in_progress", "salesforce_id_required", "ia_verified", "completed"} {
				for _, evidence := range []string{"", "uploaded", "accepted"} {
					for _, planned := range []*int64{nil, &zero, &cost} {
						it := &item{stage: stage, assignmentDate: assigned, scheduledDate: day(-20), activityStatus: status,
							evidenceStatus: evidence, plannedCost: planned, submittedToIA: day(-12), iaStatus: "pending", partnerName: "World Reader"}
						keys := []string{}
						for _, r := range risksWithWords(it, today) {
							keys = append(keys, r.key)
						}
						want := risksOf(it, today)
						slices.Sort(keys)
						slices.Sort(want)
						if !slices.Equal(keys, want) {
							t.Fatalf("%s %v %s %q: %v, want %v", stage, assigned, status, evidence, keys, want)
						}
					}
				}
			}
		}
	}
}

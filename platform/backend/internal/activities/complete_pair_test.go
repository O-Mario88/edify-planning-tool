package activities

import (
	"errors"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// Go completes the officer's own staff pair at one school, both halves still
// to be completed, its visit not collecting the SSA, planned on one day.
func TestWhichPairsGoCompletes(t *testing.T) {
	day := time.Date(2026, 11, 25, 0, 0, 0, 0, time.UTC)
	p := auth.Principal{Account: auth.Account{StaffProfileID: "s-me", ActiveRole: "CCEO"}}
	base := func() completedPair {
		return completedPair{
			training: completedVisit{id: "t", activityType: inSchoolTrainingType, status: "scheduled", schoolID: "sc", responsible: "s-me", recordType: "TRAINING", plannedDate: day},
			visit:    completedVisit{id: "v", activityType: plainSchoolVisit, status: "scheduled", schoolID: "sc", responsible: "s-me", recordType: "VISIT", plannedDate: day},
		}
	}
	for name, c := range map[string]struct {
		change func(*completedPair)
		in     bool
	}{
		"scheduled":             {func(*completedPair) {}, true},
		"training started":      {func(pr *completedPair) { pr.training.status = startedStatus }, true},
		"handed in":             {func(pr *completedPair) { pr.visit.status = handedInStatus }, false},
		"two schools":           {func(pr *completedPair) { pr.visit.schoolID = "other" }, false},
		"someone else's":        {func(pr *completedPair) { pr.training.responsible = "s-other" }, false},
		"visit collects SSA":    {func(pr *completedPair) { pr.visit.collectsSSA = true }, false},
		"visit as SSA Support":  {func(pr *completedPair) { pr.visit.purpose = ssaSupportPurpose }, false},
		"an ID already":         {func(pr *completedPair) { pr.visit.salesforceID = "SV-1" }, false},
		"another record type":   {func(pr *completedPair) { pr.training.recordType = "VISIT" }, false},
		"planned on two days":   {func(pr *completedPair) { pr.visit.plannedDate = day.AddDate(0, 0, 1) }, false},
		"a OneTest visit":       {func(pr *completedPair) { pr.visit.costing = onetestCostingProfile }, false},
		"in a cluster or a pro": {func(pr *completedPair) { pr.training.other = true }, false},
	} {
		pr := base()
		c.change(&pr)
		if got := pr.outOfCase(p) == ""; got != c.in {
			t.Errorf("%s: in case %v, want %v (%s)", name, got, c.in, pr.outOfCase(p))
		}
	}
}

// The pair's visit ID is judged by the visit's forms only: a training's TS-
// ID there is the wrong form, with no notice of its own.
func TestAPairsVisitIDIsAVisitsForm(t *testing.T) {
	for raw, ok := range map[string]bool{"SV-12345": true, " sve-abc ": true, "TS-12345": false, "": false} {
		pp := &pairCompletion{visitRaw: raw}
		err := pp.judgeVisitID()
		var refusal *Refusal
		if ok && err != nil {
			t.Errorf("%q: %v", raw, err)
		}
		if !ok && (!errors.As(err, &refusal) || refusal.Notice || refusal.Message != salesforceFormsRefusal) {
			t.Errorf("%q: %v, want %q", raw, err, salesforceFormsRefusal)
		}
	}
}

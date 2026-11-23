package coreforms

import (
	"reflect"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolplanning"
)

func eligibleItem(id, code, name, kind string) catalogueItem {
	return catalogueItem{id: id, code: code, name: name, workflowKind: kind, activityType: "school_visit", staff: true, individual: true}
}

var rankedNeeds = []rankedSSA{
	{Need: Need{Code: "financial_health", Label: "Financial Health", Score: 6.1}, Band: "Improving"},
	{Need: Need{Code: "enrolment", Label: "Enrolment", Score: 7}, Band: "Improving"},
}

func TestTheFirstRecommendationAnswersTheWeakestNeed(t *testing.T) {
	items := []catalogueItem{eligibleItem("late", "B", "Enrolment Drive", "school_visit"), eligibleItem("first", "A", "Budgeting", "school_visit")}
	mappings := map[string][]itemMapping{
		"late":  {{intervention: "enrolment", mode: "fixed"}},
		"first": {{intervention: "financial_health", mode: "fixed"}, {intervention: "enrolment", mode: "fixed"}},
	}
	got := recommendFrom(recommendInput{items: items, mappings: mappings, ranked: rankedNeeds, hasRecord: true})
	if got.First == nil || got.First.ID != "first" || got.First.Reason != "Financial Health is Improving at 6.1/10." || got.First.Target != "financial_health" {
		t.Fatalf("first: %+v", got.First)
	}
	if got.Unmet != nil {
		t.Fatalf("the top need is answered: %+v", got.Unmet)
	}
}

func TestAWholeScoreKeepsItsDecimalInTheReason(t *testing.T) {
	items := []catalogueItem{eligibleItem("late", "B", "Enrolment Drive", "school_visit")}
	got := recommendFrom(recommendInput{items: items, mappings: map[string][]itemMapping{"late": {{intervention: "enrolment", mode: "fixed"}}}, ranked: rankedNeeds, hasRecord: true})
	if got.First.Reason != "Enrolment is Improving at 7.0/10." {
		t.Fatalf("reason: %q", got.First.Reason)
	}
}

func TestWorkAlreadyPlannedRanksAfterFreshWork(t *testing.T) {
	busy := eligibleItem("busy", "A", "Alpha", "school_visit")
	busy.conflict = true
	items := []catalogueItem{busy, eligibleItem("fresh", "B", "Beta", "school_visit")}
	mappings := map[string][]itemMapping{"busy": {{intervention: "financial_health", mode: "fixed"}}, "fresh": {{intervention: "financial_health", mode: "fixed"}}}
	if got := recommendFrom(recommendInput{items: items, mappings: mappings, ranked: rankedNeeds, hasRecord: true}); got.First.ID != "fresh" {
		t.Fatalf("first: %+v", got.First)
	}
}

func TestAFollowUpInheritsItsSourceAndNeverOutranksANamedResponse(t *testing.T) {
	follow := eligibleItem("follow", "F", "Follow Up", "training_follow_up_visit")
	items := []catalogueItem{follow}
	mappings := map[string][]itemMapping{"follow": {{mode: "inherit_from_source_activity"}}}
	source := &sourceActivity{name: "Budgeting", focus: "financial_health"}
	got := recommendFrom(recommendInput{items: items, mappings: mappings, ranked: rankedNeeds, hasRecord: true, source: source})
	if got.First.Reason != "Follow up Budgeting and inherit its Financial Health intervention." || got.First.rank != 20 {
		t.Fatalf("follow: %+v", got.First)
	}
	none := recommendFrom(recommendInput{items: items, mappings: mappings, ranked: rankedNeeds, hasRecord: true})
	if none.First.Reason != "No completed source support is available. Address the current unresolved Financial Health need at 6.1/10." {
		t.Fatalf("no source: %q", none.First.Reason)
	}
	if none.Unmet == nil {
		t.Fatal("a follow-up does not answer the need it borrows")
	}
}

func TestATopNeedNoSingleSchoolWorkAnswersSaysWhereToGo(t *testing.T) {
	cluster := catalogueItem{id: "c", code: "C", name: "Cluster Course", staff: true, clusterDelivery: true}
	central := catalogueItem{id: "w", code: "W", name: "Camp", individual: true, nonSchool: true}
	standard := eligibleItem("s", "S", "Standard", "school_visit")
	standard.standard = true
	got := recommendFrom(recommendInput{items: []catalogueItem{cluster, central, standard}, mappings: map[string][]itemMapping{
		"c": {{intervention: "financial_health", mode: "fixed"}}, "w": {{intervention: "financial_health", mode: "fixed"}},
	}, ranked: rankedNeeds, hasRecord: true})
	if got.Unmet == nil || !got.Unmet.StandardAvailable || got.Unmet.Label != "Financial Health" {
		t.Fatalf("unmet: %+v", got.Unmet)
	}
	want := []BlockedGroup{
		{Reason: "not approved for staff delivery", Route: "schedule from the Work Plan page", Names: []string{"Camp"}},
		{Reason: "not delivered to a single school", Route: "schedule through a cluster", Names: []string{"Cluster Course"}},
	}
	if !reflect.DeepEqual(got.Unmet.Groups, want) {
		t.Fatalf("groups: %+v", got.Unmet.Groups)
	}
}

func TestWithoutAnSSAOnlyTheCollectionIsSuggested(t *testing.T) {
	collect := eligibleItem("ssa", "S", "SSA Collection", "school_visit_ssa_collection")
	other := eligibleItem("x", "X", "Budgeting", "school_visit")
	got := recommendFrom(recommendInput{items: []catalogueItem{collect, other}, mappings: map[string][]itemMapping{
		"ssa": {{mode: "ssa_completion_prerequisite"}}, "x": {{intervention: "financial_health", mode: "fixed"}},
	}})
	if got.HasSSA || got.First == nil || got.First.ID != "ssa" {
		t.Fatalf("got %+v", got)
	}
	if got.First.Reason != "No applicable verified SSA exists. Complete the SSA before intervention support is recommended." {
		t.Fatalf("reason: %q", got.First.Reason)
	}
}

func TestTheOpeningActivityFollowsTheRecommendationAndTheYearsSSA(t *testing.T) {
	cases := []struct {
		name, kind, ssa string
		outreach        bool
		wantType, want  string
	}{
		{"recommended visit", "school_visit", "done", false, "school_visit", "ssa_support"},
		{"recommended training", "in_school_training", "done", false, "in_school_training", "in_school_training"},
		{"training before the SSA", "in_school_training", "pending", false, "baseline_ssa_visit", "ssa_support"},
		{"an unknown kind", "core_visit", "done", false, "school_visit", "ssa_support"},
		{"nothing recommended", "", "done", false, "school_visit", "ssa_support"},
		{"a Champion", "", "pending", true, "donor_visit", "donor_visit"},
	}
	for _, tc := range cases {
		kind := openingActivityType(tc.kind, tc.ssa, tc.outreach)
		if kind != tc.wantType || fallbackPurpose(kind) != tc.want {
			t.Errorf("%s: %q, %q", tc.name, kind, fallbackPurpose(kind))
		}
	}
}

func TestAUsedVisitLocksItsPurposeForThatYearOnly(t *testing.T) {
	locks := yearLocks([]yearUse{{year: "2027", used: true, reason: "Used in 2027."}, {year: "2028"}}, false)
	if !reflect.DeepEqual(locks.Visit["training_follow_up"], map[string]string{"2027": "Used in 2027."}) {
		t.Fatalf("locks: %+v", locks.Visit)
	}
	if len(locks.EveryYear) != 0 {
		t.Fatalf("open in 2028: %v", locks.EveryYear)
	}
	all := yearLocks([]yearUse{{year: "2027", used: true, reason: "Used."}}, false)
	if len(all.EveryYear) != 3 || !all.AllEveryYear {
		t.Fatalf("every year: %+v", all)
	}
}

func TestAUniversalTrainingKeepsInSchoolTrainingOpen(t *testing.T) {
	locks := yearLocks([]yearUse{{year: "2027", used: true, reason: "Used."}}, true)
	if _, held := locks.Visit["in_school_training"]; held {
		t.Fatalf("training purpose locked: %+v", locks.Visit)
	}
	if locks.Training["2027"] != "Used." || !locks.TrainingEveryYear {
		t.Fatalf("training locks: %+v", locks)
	}
	if !reflect.DeepEqual(locks.EveryYear, []string{"training_follow_up"}) {
		t.Fatalf("every year: %v", locks.EveryYear)
	}
}

func TestTheStandardItemPricesAPurpose(t *testing.T) {
	items := []profileItem{{kind: "donor_visit", code: "B", mode: "none"}, {kind: "donor_visit", code: "A", mode: "direct_total", standard: true},
		{kind: "social_visit", code: "C", mode: "none"}, {kind: "social_visit", code: "D", mode: "none"}}
	got := purposeProfiles(items, []Choice{{"donor_visit", "Donor Visit"}, {"social_visit", "Social Visit"}}, func(kind string) string { return kind })
	if !got["donor_visit"].RequiresParticipants || !got["donor_visit"].Schedulable {
		t.Fatalf("donor: %+v", got["donor_visit"])
	}
	if got["social_visit"].Schedulable || got["social_visit"].UnavailableReason != "No single approved Cost Catalogue entry prices this purpose. Ask the Country Director to define one." {
		t.Fatalf("social: %+v", got["social_visit"])
	}
}

func TestExistingPlansAreSaidOnceInOrder(t *testing.T) {
	day := time.Date(2026, 11, 9, 0, 0, 0, 0, time.UTC)
	got := existingSummary(append(countParts(schoolplanning.Counts{Planned: 2, Awaiting: 1}, "visit"), countParts(schoolplanning.Counts{Verified: 1}, "training")...))
	if got != "2 planned visits, 1 visit awaiting verification and 1 completed training" {
		t.Fatalf("summary: %q", got)
	}
	if line := planLabel("School Visit", &day); line != "School Visit · 9 Nov 2026" {
		t.Fatalf("label: %q", line)
	}
	if line := planLabel("School Visit", nil); line != "School Visit" {
		t.Fatalf("no date: %q", line)
	}
}

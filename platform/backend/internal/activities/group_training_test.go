package activities

import (
	"errors"
	"net/url"
	"testing"
	"time"
)

// docs/migration/38: the cluster Group Training's rules that the seed
// cannot reach, and the ones it can, before any read.

func groupForm() url.Values {
	return url.Values{
		"csrfmiddlewaretoken": {"t"}, "cluster_id": {"c1"}, "activity_type": {"cluster_training"},
		"invited_schools_shown": {"1"}, "invited_school_ids": {"s1", "s2"}, "printing_pages": {""},
		"photocopy_pages": {""}, "photocopy_copies": {""}, "delivery_type": {"staff"},
		"facilitating_partner_id": {""}, "ssa_deviation_reason": {""}, "executor_type": {"staff"},
		"teachers_per_school": {"2"}, "leaders_per_school": {"1"}, "other_per_school": {"0"},
		"activity_goal": {"a goal"}, "expected_outcome": {"an outcome"}, "catalogue_item_id": {"course"},
		"scheduled_date": {"2026-11-26"},
	}
}

func TestTheGroupTrainingFormIsTakenOnlyForTheOwnersStaffSession(t *testing.T) {
	req, ok := GroupTrainingRequestFromForm(groupForm())
	if !ok || req.ClusterID != "c1" || len(req.Invited) != 2 || !req.InvitedShown || req.Teachers != "2" {
		t.Fatalf("the drawer's own form: %v %+v", ok, req)
	}
	handedOn := map[string]func(url.Values){
		"a partner facilitates":      func(f url.Values) { f.Set("facilitating_partner_id", "p1") },
		"no Facilitated by field":    func(f url.Values) { f.Del("facilitating_partner_id") },
		"online delivery":            func(f url.Values) { f.Set("delivery_mode", "online") },
		"a responsible person named": func(f url.Values) { f.Set("responsible_staff_id", "x") },
		"a focus the planner names":  func(f url.Values) { f.Set("focus_intervention", "leadership") },
		"a project":                  func(f url.Values) { f.Set("project_id", "p") },
		"partner delivery":           func(f url.Values) { f.Set("delivery_type", "partner") },
		"a cluster meeting":          func(f url.Values) { f.Set("activity_type", "cluster_meeting") },
		"a school":                   func(f url.Values) { f.Set("school_id", "S-1") },
	}
	for name, change := range handedOn {
		f := groupForm()
		change(f)
		if _, ok := GroupTrainingRequestFromForm(f); ok {
			t.Errorf("%s: must be handed on", name)
		}
	}
	if IsGroupTrainingForm(url.Values{"school_id": {"S-1"}, "activity_type": {"cluster_training"}}) {
		t.Error("a school's form is not a cluster's")
	}
}

func TestParticipantsAndMaterialsAreReadAsTheServiceReadsThem(t *testing.T) {
	tests := []struct {
		name                     string
		teachers, leaders, other string
		want                     int
		refusal                  string
		handOn                   bool
	}{
		{name: "two teachers and a leader", teachers: "2", leaders: "1", other: "0", want: 3},
		{name: "a blank category is none", teachers: "4", want: 4},
		{name: "nobody", teachers: "0", leaders: "0", other: "0", refusal: nobodyPerSchool},
		{name: "past the per-school ceiling", teachers: "400", leaders: "101", refusal: tooManyPerSchool},
		{name: "none stated (the catalogue's guidance decides)", handOn: true},
		{name: "a leading zero", teachers: "02", handOn: true},
		{name: "a decimal", teachers: "2.5", handOn: true},
		{name: "a sign", teachers: "+2", handOn: true},
		{name: "implausibly many of one category", teachers: "100001", handOn: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, _, err := perSchoolOf(GroupTrainingRequest{Teachers: test.teachers, Leaders: test.leaders, Other: test.other})
			assertOutcome(t, err, test.refusal, test.handOn)
			if err == nil && got != test.want {
				t.Fatalf("per school %d, want %d", got, test.want)
			}
		})
	}
	m, err := materialsOf(GroupTrainingRequest{Printing: "12", PhotocopyPages: "", PhotocopyCopies: "3"})
	if err != nil || m != [3]int{12, 0, 3} {
		t.Fatalf("materials %v %v", m, err)
	}
	_, err = materialsOf(GroupTrainingRequest{PhotocopyCopies: "1000001"})
	assertOutcome(t, err, "The number of photocopies is implausibly large.", false)
	_, err = materialsOf(GroupTrainingRequest{Printing: "-1"})
	assertOutcome(t, err, "", true)
}

func assertOutcome(t *testing.T, err error, refusal string, handedOn bool) {
	t.Helper()
	var r *Refusal
	switch {
	case handedOn:
		if !errors.Is(err, ErrHandOn) {
			t.Fatalf("want a hand-on, got %v", err)
		}
	case refusal != "":
		if !errors.As(err, &r) || r.Message != refusal {
			t.Fatalf("want %q, got %v", refusal, err)
		}
	case err != nil:
		t.Fatalf("want no refusal, got %v", err)
	}
}

func score(code string, v float64) ssaScore { return ssaScore{Intervention: code, Score: &v} }

func TestTheClusterNeedAveragesTheCurrentRecordsOfTheSchoolsInvited(t *testing.T) {
	now := time.Date(2026, 11, 13, 9, 0, 0, 0, time.UTC)
	current := func(id string, scores ...ssaScore) memberRecord {
		return memberRecord{SchoolID: "s-" + id, Record: &ssaRecord{ID: id, FY: "2027", Scores: scores}}
	}
	records := []memberRecord{
		current("r2", score("leadership", 5.0), score("learning_environment", 4.5)),
		current("r1", score("leadership", 5.6), score("learning_environment", 5.1)),
		{SchoolID: "s-old", Record: &ssaRecord{ID: "r0", FY: "2020", Scores: []ssaScore{score("leadership", 1)}}},
	}
	need := clusterNeedFrom(4, records, now)
	if need.Members != 4 || need.Assessed != 2 || need.StaleSchools != 1 {
		t.Fatalf("counts %+v", need)
	}
	if len(need.Rows) != 2 || need.Rows[0].Intervention != "learning_environment" || need.Rows[0].Average != 4.8 ||
		need.Rows[0].SchoolsLow != 2 || need.Rows[1].Average != 5.3 || need.Rows[1].SchoolsLow != 1 {
		t.Fatalf("rows %+v", need.Rows)
	}
	if got := need.SourceSSAIDs; len(got) != 2 || got[0] != "r1" {
		t.Fatalf("source SSAs sorted, the out-of-date one left out: %v", got)
	}
	ev := assessCluster("cluster_training", "leadership", "course", []string{"fixed"}, need, now)
	if ev.Alignment != "priority" && ev.Alignment != "off_priority" {
		t.Fatalf("alignment %s", ev.Alignment)
	}
	cluster := ev.Data["cluster"].(map[string]any)
	if cluster["focusRank"] != 2 || cluster["focusSchoolsBelow"] != 1 {
		t.Fatalf("focus %v", cluster)
	}
	stale := clusterNeedFrom(1, records[2:], now)
	if !stale.stale() || assessCluster("cluster_training", "leadership", "course", nil, stale, now).Alignment != "stale_ssa" {
		t.Fatalf("only out-of-date members: %+v", stale)
	}
	none := assessCluster("cluster_training", "", "planner", []string{"administrative"}, clusterNeed{}, now)
	if none.Alignment != "not_applicable" || reasonFor(none) != "Not school-improvement work, so no SSA intervention applies." {
		t.Fatalf("an orientation: %s %q", none.Alignment, reasonFor(none))
	}
}

func TestTheClusterReasonSaysTheFocusAndTheWeakestNeed(t *testing.T) {
	cluster := map[string]any{"focusRank": 4, "focusAverage": pyFloat(5.3), "focusSchoolsBelow": 2,
		"assessedSchools": 3, "top": map[string]any{"label": "Learning Environment"}}
	got := reasonFor(evidence{Alignment: "off_priority", Focus: "leadership", Data: map[string]any{"cluster": cluster}})
	want := "Targets Leadership (cluster average 5.3/10, 2 of 3 assessed schools below 5.5); the weakest cluster need is Learning Environment."
	if got != want {
		t.Fatalf("%q\nwant %q", got, want)
	}
	unscored := map[string]any{"focusRank": nil, "top": nil}
	if got := reasonFor(evidence{Alignment: "priority", Focus: "leadership", Data: map[string]any{"cluster": unscored}}); got != "Targets Leadership (not scored in any member school)." {
		t.Fatalf("%q", got)
	}
	noFocus := map[string]any{"top": map[string]any{"label": "Leadership"}}
	if got := reasonFor(evidence{Alignment: "no_focus", Data: map[string]any{"cluster": noFocus}}); got != "Names no intervention although the SSA ranks Leadership first." {
		t.Fatalf("%q", got)
	}
}

func TestTheClusterRecommendationMergesEachMembersNeed(t *testing.T) {
	ranked := func(codes ...string) []rankedNeed {
		out := []rankedNeed{}
		for _, c := range codes {
			out = append(out, rankedNeed{Intervention: c})
		}
		return out
	}
	members := []memberNeed{
		{SchoolID: "a", Record: &ssaRecord{ID: "ra"}, Ranked: ranked("finance", "leadership")},
		{SchoolID: "b", Record: &ssaRecord{ID: "rb"}, Ranked: ranked("leadership", "finance")},
		{SchoolID: "c"},
	}
	items := []clusterItem{
		{ID: "lead", Code: "L", Name: "Leadership", Mappings: []itemMapping{{Mode: "fixed", Intervention: "leadership"}}},
		{ID: "fin", Code: "F", Name: "Finance", Mappings: []itemMapping{{Mode: "fixed", Intervention: "finance"}}, Conflict: true},
		{ID: "multi", Code: "M", Name: "Many", Mappings: []itemMapping{
			{Mode: "multiple_allowed", Intervention: "leadership", Priority: 2},
			{Mode: "multiple_allowed", Intervention: "finance", Priority: 1}}},
		{ID: "next", Code: "N", Name: "Follow", Mappings: []itemMapping{{Mode: "inherit_from_source_activity"}}},
		{ID: "orient", Code: "O", Name: "Orientation", Mappings: []itemMapping{{Mode: "administrative"}}},
	}
	got := rankForCluster(members, items, "", "lead")
	if got.reason != "2 Cluster member School(s) have verified Leadership need." || len(got.ssaIDs) != 2 ||
		got.verification != "verified" {
		t.Fatalf("%+v", got)
	}
	// Leadership and Many and Finance all rank 0 once; Finance is planned
	// already, so Leadership and Many come first, by name; the follow-up
	// ranks 20 and is fourth.
	if !got.recommended {
		t.Error("Leadership is among the first three")
	}
	if follow := rankForCluster(members, items, "", "next"); follow.recommended || follow.reason != "2 Cluster member School(s) have verified Finance need." {
		t.Fatalf("the follow-up: %+v", follow)
	}
	if inherited := rankForCluster(members, items, "leadership", "next"); inherited.reason != "2 Cluster member School(s) have verified Leadership need." {
		t.Fatalf("the follow-up inherits the last session's target: %+v", inherited)
	}
	if orient := rankForCluster(members, items, "", "orient"); orient.reason != "Authorized alternative Catalogue Activity." || len(orient.ssaIDs) != 0 {
		t.Fatalf("no row for the course: %+v", orient)
	}
	if none := rankForCluster(members[2:], items, "", "lead"); none.verification != "none" {
		t.Fatalf("no member with an SSA: %+v", none)
	}
	src := got.source()
	if src["context"] != "cluster" || src["engine"] != "apps.ssa.recommendation_engine" || src["projectId"] != nil {
		t.Fatalf("source %v", src)
	}
}

func TestAClusterRowInsertsItsOwnColumnsAndAVisitNone(t *testing.T) {
	visit := activityRow{}
	if visit.groupFields() != nil {
		t.Fatal("a school's work writes no cluster column")
	}
	if source, context := visit.planning(); source != "school_planning" || context != "school" {
		t.Fatal("a school's work keeps its planning source")
	}
	session := activityRow{planningSource: "cluster_planning", contextType: "cluster",
		group: &groupColumns{clusterID: "c1", expected: 9, perSchool: 3, invited: 3, printing: 0, photocopyCopies: 4}}
	fields := map[string]any{}
	for _, f := range session.groupFields() {
		fields[f.name] = f.value
	}
	if fields["cluster_id"] != "c1" || fields["expected_participants"] != 9 || fields["printing_pages"] != nil ||
		fields["photocopy_copies"] != 4 {
		t.Fatalf("%v", fields)
	}
	probe := session.probe()
	if probe["school_id"] != nil || probe["cluster_id"] != "c1" || probe["planning_source"] != "cluster_planning" {
		t.Fatalf("the day check's probe: %v", probe)
	}
}

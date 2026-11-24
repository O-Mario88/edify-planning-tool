package activities

import (
	"errors"
	"net/url"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
)

// A meeting is a training to Salesforce: its ID is TS-… or the record's own
// ID, and a visit's SV- ID is refused in the existing words.
func TestAMeetingsIDIsJudgedAsATrainingsID(t *testing.T) {
	s := &Service{}
	for raw, want := range map[string]string{
		"TS-998877":       "",
		" ts - abc ":      "",
		"A0B1C2D3E4F5G6H": "",
		"":                trainingFormsRefusal,
		"TS-12":           trainingFormsRefusal,
		"SV-990001":       trainingFormsRefusal,
		"SVE-990001":      trainingFormsRefusal,
	} {
		err := s.judgeTrainingID(&completionPlan{raw: raw})
		var refusal *Refusal
		switch {
		case want == "" && err != nil:
			t.Errorf("%q: %v, want it accepted", raw, err)
		case want != "" && (!errors.As(err, &refusal) || refusal.Message != want):
			t.Errorf("%q: %v, want %q", raw, err, want)
		}
	}
}

// The register is read as _cluster_member_school_ids first reads it: each
// id stripped, blanks dropped, each school once in its first place.
func TestTheRegisterIsReadOnceEachInPostedOrder(t *testing.T) {
	got := postedIDs([]string{" s2", "s1", "", "s2", "s1 ", "on"})
	if want := []string{"s2", "s1", "on"}; !slices.Equal(got, want) {
		t.Fatalf("%v, want %v", got, want)
	}
}

func meetingService() *Service {
	return &Service{kampala: time.UTC, now: func() time.Time { return time.Date(2026, 11, 20, 9, 0, 0, 0, time.UTC) }}
}

func meetingPlan() *completionPlan {
	return &completionPlan{a: completedVisit{activityType: clusterMeetingType, plannedDate: time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)}}
}

// A training is completed with someone in the room: no teacher and no
// leader is refused before the ID is judged, in complete()'s words.
func TestAMeetingNeedsAttendanceBeforeItsIDIsJudged(t *testing.T) {
	for name, form := range map[string]url.Values{
		"no one, a good ID": {"actual_delivery_date": {"2026-11-20"}, "salesforce_id": {"TS-998877"}},
		"no one, a bad ID":  {"actual_delivery_date": {"2026-11-20"}, "salesforce_id": {"SV-1"}, "teachers_attended": {"0"}},
	} {
		var refusal *Refusal
		if err := meetingService().readMeetingForm(meetingPlan(), form); !errors.As(err, &refusal) || refusal.Message != trainingAttendanceAsked {
			t.Errorf("%s: %v, want %q", name, err, trainingAttendanceAsked)
		}
	}
	form := url.Values{"actual_delivery_date": {"2026-11-20"}, "salesforce_id": {"SV-1"}, "leaders_attended": {"2"}}
	var refusal *Refusal
	if err := meetingService().readMeetingForm(meetingPlan(), form); !errors.As(err, &refusal) || refusal.Message != trainingFormsRefusal {
		t.Errorf("leaders came, a visit's ID: %v, want %q", err, trainingFormsRefusal)
	}
}

// The audit row records the register as posted (unfiltered, as getlist
// gives it), no visiting schools, and the counts as read.
func TestAMeetingsPayloadIsTheExistingOne(t *testing.T) {
	pl := meetingPlan()
	form := url.Values{
		"actual_delivery_date": {"2026-11-20"}, "salesforce_id": {" ts-998877 "}, "teachers_attended": {"4"},
		"leaders_attended": {"1"}, "attended_school_ids": {"s1", "s1", "on"},
	}
	if err := meetingService().readMeetingForm(pl, form); err != nil {
		t.Fatal(err)
	}
	if pl.normalized != "TS-998877" || pl.teachers != 4 || pl.leaders != 1 || !slices.Equal(pl.attended, []string{"s1", "on"}) {
		t.Fatalf("read %q %d %d %v", pl.normalized, pl.teachers, pl.leaders, pl.attended)
	}
	ids, ok := pl.payload["attendedSchoolIds"].([]any)
	if !ok || len(ids) != 3 || ids[2] != "on" {
		t.Errorf("attendedSchoolIds %v", pl.payload["attendedSchoolIds"])
	}
	if v, ok := pl.payload["visitingSchoolIds"].([]any); !ok || len(v) != 0 {
		t.Errorf("visitingSchoolIds %v", pl.payload["visitingSchoolIds"])
	}
	if pl.payload["otherParticipants"] != 0 || pl.payload["salesforceId"] != "ts-998877" {
		t.Errorf("payload %v", pl.payload)
	}
}

// What Go does not make is handed on: visiting schools, a purpose, an
// accountability, other participants, and a day other than the planned one.
func TestAMeetingsCompletionHandsOnWhatItDoesNotMake(t *testing.T) {
	for name, change := range map[string]func(url.Values){
		"visiting schools":   func(f url.Values) { f.Set("visiting_school_ids", "g1") },
		"a purpose":          func(f url.Values) { f.Set("purpose_type", "ssa_support") },
		"an accountability":  func(f url.Values) { f.Set("netsuite_id", "NS-1") },
		"other participants": func(f url.Values) { f.Set("other_participants", "3") },
		"another day":        func(f url.Values) { f.Set("actual_delivery_date", "2026-11-19") },
		"a training's ID":    func(f url.Values) { f.Set("training_salesforce_id", "TS-1") },
	} {
		form := url.Values{"actual_delivery_date": {"2026-11-20"}, "salesforce_id": {"TS-998877"}, "teachers_attended": {"2"}}
		change(form)
		if err := meetingService().readMeetingForm(meetingPlan(), form); !errors.Is(err, ErrHandOn) {
			t.Errorf("%s: %v, want a hand-on", name, err)
		}
	}
}

// Go completes the officer's own meeting, started or still to be started,
// kept as a training or under no record type, with no ID yet.
func TestWhichMeetingsGoCompletes(t *testing.T) {
	day := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)
	p := auth.Principal{Account: auth.Account{StaffProfileID: "s-me", ActiveRole: "CCEO"}}
	base := func() completedMeeting {
		return completedMeeting{id: "m", status: "scheduled", responsible: "s-me", planned: &day}
	}
	for name, c := range map[string]struct {
		change func(*completedMeeting)
		in     bool
	}{
		"scheduled":           {func(*completedMeeting) {}, true},
		"started":             {func(m *completedMeeting) { m.status = startedStatus }, true},
		"rescheduled":         {func(m *completedMeeting) { m.status = "rescheduled" }, true},
		"kept as a training":  {func(m *completedMeeting) { m.recordType = "training" }, true},
		"handed in":           {func(m *completedMeeting) { m.status = handedInStatus }, false},
		"someone else's":      {func(m *completedMeeting) { m.responsible = "s-other" }, false},
		"with a guest":        {func(m *completedMeeting) { m.other = true }, false},
		"confirmed":           {func(m *completedMeeting) { m.verification = confirmedVerification }, false},
		"no record":           {func(m *completedMeeting) { m.recordType = "NONE" }, false},
		"holding an ID":       {func(m *completedMeeting) { m.reference = "TS-1" }, false},
		"with no planned day": {func(m *completedMeeting) { m.planned = nil }, false},
	} {
		m := base()
		c.change(&m)
		if got := m.outOfCase(p) == ""; got != c.in {
			t.Errorf("%s: in case %v, want %v (%s)", name, got, c.in, m.outOfCase(p))
		}
	}
}

// The function that hands a meeting in takes the statuses the Go save
// starts or completes: the SQL names them as a literal.
func TestTheMeetingHandInTakesTheStartableStatuses(t *testing.T) {
	raw, err := os.ReadFile(filepath.FromSlash("../../../deploy/db/completion_roles.sql"))
	if err != nil {
		t.Fatal(err)
	}
	fn := regexp.MustCompile(`(?s)FUNCTION gateway_completion\.hand_in_cluster_meeting\(.*?\$fn\$;`).Find(raw)
	array := regexp.MustCompile(`(?s)work\.status = ANY \(ARRAY\[(.*?)\]::varchar\[\]\)`).FindSubmatch(fn)
	if array == nil {
		t.Fatal("the function's statuses were not found")
	}
	named := []string{}
	for _, m := range regexp.MustCompile(`'([a-z_]+)'`).FindAllSubmatch(array[1], -1) {
		named = append(named, string(m[1]))
	}
	want := append(slices.Clone(startableStatuses), startedStatus)
	slices.Sort(named)
	slices.Sort(want)
	if !slices.Equal(named, want) {
		t.Fatalf("the function takes %v; the Go save takes %v", named, want)
	}
}

// A head count is drawn as the template's default:0 draws it.
func TestHeadCountsAreDrawnWithTheTemplatesDefault(t *testing.T) {
	two, zero := 2, 0
	for _, c := range []struct {
		n    *int
		want string
	}{{nil, "0"}, {&zero, "0"}, {&two, "2"}} {
		if got := countValue(c.n); got != c.want {
			t.Errorf("%v: %q, want %q", c.n, got, c.want)
		}
	}
}

// Work done on another day keeps the local time it was scheduled for, and
// is priced with the move's reason in completed_day's words.
func TestWorkDoneOnAnotherDayKeepsItsTimeOfDay(t *testing.T) {
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		t.Fatal(err)
	}
	scheduled := time.Date(2026, 11, 27, 6, 30, 0, 0, time.UTC) // 09:30 in Kampala
	day := time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC)
	got := onDoneDay(scheduled, day, kampala)
	if want := time.Date(2026, 11, 5, 9, 30, 0, 0, kampala); !got.Equal(want) {
		t.Errorf("%v, want %v", got, want)
	}
	if got := completedOnReason(day); got != "Completed on 05 Nov 2026" {
		t.Errorf("%q", got)
	}
}

// With Django absent a meeting done on another day is read, not handed on:
// the move is decided once the form is read.
func TestAMeetingDoneOnAnotherDayIsReadWithDjangoAbsent(t *testing.T) {
	pl := meetingPlan()
	pl.sessions = true
	form := url.Values{"actual_delivery_date": {"2026-11-19"}, "salesforce_id": {"TS-998877"}, "teachers_attended": {"2"}}
	if err := meetingService().readMeetingForm(pl, form); err != nil {
		t.Fatalf("%v, want the form read", err)
	}
	if !sameDay(pl.delivered, time.Date(2026, 11, 19, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("delivered %v", pl.delivered)
	}
}

// A training's TS- ID typed as a visit's is the view's own notice, naming
// where it goes on a visit the drawer offers as a training.
func TestATrainingIDOnAVisitIsTheViewsNotice(t *testing.T) {
	for kind, want := range map[string]string{
		"school_visit": "TS-12 is a training ID. This visit is completed with its visit ID from Salesforce: SV-… or SVE-….",
		ssaCollectionKind: "TS-12 is a training ID. If a training was delivered on this visit, choose “In-school Training” or " +
			"“In-school Training + SSA Collection” as the purpose: the training's TS- ID goes in Training ID, and the visit's SV- or SVE- ID in Visit ID.",
	} {
		pl := &completionPlan{a: completedVisit{activityType: kind}}
		var refusal *Refusal
		if err := pl.trainingIDOnAVisit(url.Values{"salesforce_id": {" ts-12"}}); !errors.As(err, &refusal) || !refusal.Notice || refusal.Message != want {
			t.Errorf("%s: %v", kind, err)
		}
		if err := pl.trainingIDOnAVisit(url.Values{"salesforce_id": {"SV-12345"}}); err != nil {
			t.Errorf("%s: a visit's ID refused: %v", kind, err)
		}
	}
}

// A School Visit + SSA Collection keeps why no SSA was taken; a blank
// sheet is none; scores marked collected are all eight or the view's notice.
func TestTheSSANotCollectedIsReadAsTheViewReadsIt(t *testing.T) {
	pl := &completionPlan{}
	if err := readSSANotCollected(pl, url.Values{"ssa_collected": {"no"}, "ssa_not_collected_reason": {" Other "}}); err != nil || pl.ssaReason == nil || *pl.ssaReason != "Other" || !pl.ssaVisit {
		t.Fatalf("%v %v", err, pl.ssaReason)
	}
	pl = &completionPlan{}
	if err := readSSANotCollected(pl, url.Values{"ssa_collected": {"yes"}, "score_leadership": {""}}); err != nil || pl.ssaReason != nil {
		t.Fatalf("a blank sheet: %v %v", err, pl.ssaReason)
	}
	var refusal *Refusal
	if err := readSSANotCollected(&completionPlan{}, url.Values{"ssa_collected": {"yes"}, "score_leadership": {"7"}}); !errors.As(err, &refusal) ||
		!refusal.Notice || refusal.Message != "Missing score for Christlike Behaviour" {
		t.Fatalf("a part-filled sheet: %v", err)
	}
	full := url.Values{"ssa_collected": {"yes"}}
	for _, field := range ssaScoreFields {
		full.Set(field, "7.5")
	}
	pl = &completionPlan{}
	if err := readSSANotCollected(pl, full); err != nil || len(pl.ssaScores) != 8 || pl.ssaReason != nil {
		t.Fatalf("all eight: %v %d", err, len(pl.ssaScores))
	}
	full.Set("score_exposure_to_word_of_god", "11")
	if err := readSSANotCollected(&completionPlan{}, full); !errors.As(err, &refusal) || refusal.Message != "Score for Exposure To Word Of God must be between 0 and 10" {
		t.Fatalf("out of range: %v", err)
	}
	full.Set("score_exposure_to_word_of_god", "seven")
	if err := readSSANotCollected(&completionPlan{}, full); !errors.As(err, &refusal) || refusal.Message != "Score for Exposure To Word Of God must be numeric" {
		t.Fatalf("not numeric: %v", err)
	}
	full.Set("score_exposure_to_word_of_god", "nan")
	if err := readSSANotCollected(&completionPlan{}, full); !errors.Is(err, ErrHandOn) {
		t.Fatalf("nan: %v, want a hand-on", err)
	}
}

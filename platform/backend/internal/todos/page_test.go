package todos

import (
	"context"
	"encoding/json"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

func day(s string) *time.Time {
	d, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return &d
}

// TestNextActionIsTheExistingOne holds computeNextAction, actPriority and
// actStatus to compute_next_action, _act_priority and _act_status over the
// exported grid of activities (testdata/next_action_cases.json).
func TestNextActionIsTheExistingOne(t *testing.T) {
	raw, err := os.ReadFile("testdata/next_action_cases.json")
	if err != nil {
		t.Fatal(err)
	}
	var file struct {
		Fields []string `json:"fields"`
		Cases  []string `json:"cases"`
	}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatal(err)
	}
	today := *day("2026-11-13")
	planned := map[string]*time.Time{"none": nil, "past": day("2026-11-10"), "today": day("2026-11-13"), "future": day("2026-11-17")}
	if len(file.Cases) < 1000 {
		t.Fatalf("only %d cases", len(file.Cases))
	}
	for _, c := range file.Cases {
		given, answer, _ := strings.Cut(c, " => ")
		in := strings.Split(given, "|")
		want := strings.Split(answer, "|")
		v := map[string]string{}
		for i, f := range file.Fields {
			v[f] = in[i]
		}
		teachers, _ := strconv.Atoi(v["teachers"])
		leaders, _ := strconv.Atoi(v["leaders"])
		a := activity{ID: "ACT", Status: v["status"], DeliveryType: v["delivery"], EvidenceStatus: v["evidence"],
			PlannedDate: planned[v["planned"]], SalesforceID: v["sf"], ActivityType: v["type"], Teachers: teachers,
			Leaders: leaders, HasSchool: v["school"] != "none", SchoolSSAStatus: v["school"],
			IAVerification: v["ia"], Payment: v["payment"]}
		if v["advances"] != "" {
			for _, k := range strings.Split(v["advances"], "+") {
				switch k {
				case "receipt":
					a.Advances[len(a.Advances)-1].ReceiptConfirmed = true
				case "netsuite":
					a.Advances[len(a.Advances)-1].NetSuite = true
				default:
					a.Advances = append(a.Advances, advance{Status: k})
				}
			}
		}
		na := computeNextAction(a, today)
		got := []string{na.Text, na.Action, na.URL, actPriority(a, na.Action, today), actStatus(a, na.Action, today)}
		if strings.Join(got, "|") != answer {
			t.Errorf("%s\n got %v\nwant %v", given, got, want)
		}
	}
}

// TestThePageIsTheExistingOneOverSyntheticQueues compares the page Go draws
// with the existing feed's answer for the same queue
// (testdata/page_golden.json: every builder replaced by one handing back
// the rows; the link gate, sort, counts, template and reader the existing
// application's own).
func TestThePageIsTheExistingOneOverSyntheticQueues(t *testing.T) {
	raw, err := os.ReadFile("testdata/page_golden.json")
	if err != nil {
		t.Fatal(err)
	}
	var file struct {
		Answers []struct {
			Role string `json:"role"`
			Rows []struct {
				Title, Category, Priority string
				StatusKey                 string `json:"status_key"`
				Actionable                bool
				Linked                    string
				ActionLabel               string `json:"action_label"`
				ActionURL                 string `json:"action_url"`
				Shape, Due                string
			} `json:"rows"`
			Body json.RawMessage `json:"body"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &file); err != nil {
		t.Fatal(err)
	}
	if len(file.Answers) < 5 {
		t.Fatalf("only %d answers", len(file.Answers))
	}
	for i, a := range file.Answers {
		var rows []todo
		for _, r := range a.Rows {
			row := todo{Title: r.Title, Category: r.Category, Priority: r.Priority, StatusKey: r.StatusKey,
				Actionable: r.Actionable, Linked: r.Linked, ActionLabel: r.ActionLabel, ActionURL: r.ActionURL, Shape: r.Shape}
			if r.Due != "" {
				row.Due = day(r.Due)
			}
			rows = append(rows, row)
		}
		q, err := buildQueue(a.Role, rows)
		if err != nil {
			t.Fatal(err)
		}
		want := &screensv1.GetPageResponse{}
		if err := protojson.Unmarshal(a.Body, want); err != nil {
			t.Fatal(err)
		}
		if got := page(q); !proto.Equal(got, want) {
			t.Errorf("queue %d (%d rows):\n got %v\nwant %v", i, len(rows), got, want)
		}
	}
}

func TestContextLineDropsThePlaceTheTitleNames(t *testing.T) {
	for _, c := range [][3]string{
		{"Schedule V1 Core Visit — Nakifuma School", "Nakifuma School · Core Visit", "Core Visit"},
		{"Schedule V1 Core Visit — Nakifuma School", "Nakifuma School", ""},
		{"Chase Partner Delivery", "Koome · partner", "Koome · partner"},
		{"Fix", "", ""},
		{"Anything", " · rest", " · rest"},
	} {
		if got := contextLine(c[0], c[1]); got != c[2] {
			t.Errorf("contextLine(%q, %q) = %q, want %q", c[0], c[1], got, c[2])
		}
	}
}

func TestIdenticalToDosGroupFromThree(t *testing.T) {
	r := func(title string) todo { return todo{Title: title, Category: "C", Priority: "high"} }
	got := groupIdentical([]todo{r("a"), r("b"), r("a"), r("b"), r("a"), r("c")})
	if len(got) != 4 || !got[0].group || len(got[0].rows) != 3 || got[1].group || got[3].rows[0].Title != "c" {
		t.Errorf("%+v", got)
	}
}

func TestEveryBuilderGoHasIsOneOfTheQueues(t *testing.T) {
	for name := range Handled {
		if !contains(rules.Builders, name) {
			t.Errorf("Go builds %s, which the queue no longer has", name)
		}
	}
	if !Served("CCEO") {
		t.Errorf("the field officer's queue needs a builder Go does not have: %v", rules.Roles["CCEO"].Builders)
	}
	for role := range rules.Roles {
		if role != "CCEO" && Served(role) {
			t.Errorf("%s is served", role)
		}
	}
}

// A core plan's gaps are _core_plan_gaps': its returned slots, and each
// kind's first slot by sequence that is neither done, in flight nor
// returned (the seed's plans have no returned slot).
func TestACorePlansGapsAreItsReturnedAndNextOpenSlots(t *testing.T) {
	slots := []coreSlot{
		{ID: "v3", Kind: "visit", Sequence: 3, Status: "Planned"},
		{ID: "v1", Kind: "visit", Sequence: 1, Status: "Completed"},
		{ID: "v2", Kind: "visit", Sequence: 2, Status: "Returned"},
		{ID: "t1", Kind: "training", Sequence: 1, Status: "Scheduled"},
		{ID: "t2", Kind: "training", Sequence: 2, Status: "IA Pending"},
		{ID: "a1", Kind: "assessment", Sequence: 1, Status: "returned"},
	}
	returned, missing := corePlanGaps(slots)
	if len(returned) != 2 || returned[0].ID != "v2" || returned[1].ID != "a1" {
		t.Errorf("returned %+v", returned)
	}
	if len(missing) != 1 || missing[0].slot.ID != "v3" || missing[0].label != "Visit" {
		t.Errorf("missing %+v", missing)
	}
}

func TestAReaderIsPassedOnByAGuardOrAnApprovalTheyGive(t *testing.T) {
	if _, err := partnerAssignmentGuard(context.Background(), nil, &reader{role: "PartnerAdmin"}); err != errPassOn {
		t.Errorf("a partner: %v", err)
	}
	if got, err := partnerAssignmentGuard(context.Background(), nil, &reader{role: "CCEO"}); err != nil || got != nil {
		t.Errorf("an officer: %v %v", got, err)
	}
	if _, err := fundRequestTodos(context.Background(), nil, &reader{role: "Program Lead"}); err != errPassOn {
		t.Errorf("a fund approver: %v", err)
	}
}

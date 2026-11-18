//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
)

const partnerOversightPath = "/partner-oversight/"

// The gateway under test has no existing application behind it, so every
// answer here is Go's, and a reader Go passes on reads as unavailable.
func TestPartnerOversightAnOfficerWithNoPartnerWorkIsGos(t *testing.T) {
	borrowAccount(t, "cceo1@edify.org")
	page, err := pageOf(sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken(), partnerOversightPath, nil)
	if err != nil {
		t.Fatalf("Partner Monitoring for cceo1: %v", err)
	}
	blocks := page.GetBlocks()
	if page.GetHeader().GetTitle() != "Partner Monitoring" || len(blocks) != 4 {
		t.Fatalf("got %q with %d blocks", page.GetHeader().GetTitle(), len(blocks))
	}
	tabs := blocks[1].GetLinkTabs().GetTabs()
	if len(tabs) != 1 || tabs[0].GetLabel() != "All team members 0" || !tabs[0].GetActive() {
		t.Errorf("team member tabs %v", tabs)
	}
	if note := blocks[2].GetStrip().GetMetrics()[0].GetNote(); note != "" {
		t.Errorf("an officer with no monitor has no Partner target, got %q", note)
	}
	if blocks[3].GetEmpty() == "" {
		t.Error("no empty state")
	}
}

func TestPartnerOversightALeadWithNoPartnerWorkSeesTheirTeamAndRegister(t *testing.T) {
	borrowAccount(t, "pl2@edify.org")
	page, err := pageOf(sessionOf(t, "pl2@edify.org", seededPassword).GetAccessToken(), partnerOversightPath, map[string]string{"fy": "2028"})
	if err != nil {
		t.Fatalf("Partner Monitoring for pl2: %v", err)
	}
	blocks := page.GetBlocks()
	if len(blocks) != 7 {
		t.Fatalf("got %d blocks", len(blocks))
	}
	tabs := blocks[1].GetLinkTabs().GetTabs()
	if len(tabs) < 2 || tabs[1].GetLabel() != "Program Lead 2 0" || !strings.Contains(tabs[1].GetHref(), "&fy=2028&") {
		t.Errorf("team member tabs %v", tabs)
	}
	if note := blocks[2].GetStrip().GetMetrics()[0].GetNote(); !strings.Contains(note, "Partner target 0 visits") {
		t.Errorf("first tile note %q", note)
	}
	if got := blocks[5].GetStrip().GetMetrics(); len(got) != 4 || got[0].GetNote() != "FY2028 · meetings, orientations and follow-ups" {
		t.Errorf("register tiles %v", got)
	}
}

func TestPartnerOversightPassesOnWhatGoDoesNotDrawAndRefusesOthers(t *testing.T) {
	borrowAccount(t, "cceo1@edify.org")
	borrowAccount(t, "cd@edify.org")
	borrowAccount(t, "business-transformation@edify.org")
	officer := sessionOf(t, "cceo1@edify.org", seededPassword).GetAccessToken()
	// cceo1's completed FY 2026 Partner work is Go's (the golden compares
	// it), and so is an activity filter over it.
	if _, err := pageOf(officer, partnerOversightPath, map[string]string{"fy": "2026"}); err != nil {
		t.Errorf("cceo1 in FY 2026: %v", err)
	}
	var held int
	if err := admin.QueryRow(context.Background(), `SELECT count(*) FROM partner_assignment pa
JOIN "user" u ON u.id = pa.monitoring_staff_id WHERE u.email = 'cceo1@edify.org'`).Scan(&held); err != nil {
		t.Fatal(err)
	}
	if held > 0 {
		if _, err := pageOf(officer, partnerOversightPath, map[string]string{"fy": "2026", "activity_type": "school_visit"}); err != nil {
			t.Errorf("an activity filter: %v", err)
		}
	}
	// A custom period from the export drawer is too.
	if _, err := pageOf(officer, partnerOversightPath, map[string]string{"period_type": "fy"}); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Errorf("custom period: got %v, want the page passed on", err)
	}
	// The country's lens and a region's are Go's.
	if _, err := pageOf(sessionOf(t, "cd@edify.org", seededPassword).GetAccessToken(), partnerOversightPath, nil); err != nil {
		t.Errorf("the Country Director: %v", err)
	}
	borrowAccount(t, "regional-lead@edify.org")
	if _, err := pageOf(sessionOf(t, "regional-lead@edify.org", seededPassword).GetAccessToken(), partnerOversightPath, nil); err != nil {
		t.Errorf("the Regional Programme Lead: %v", err)
	}
	if _, err := pageOf(sessionOf(t, "business-transformation@edify.org", seededPassword).GetAccessToken(), partnerOversightPath, nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Errorf("Business Transformation: got %v, want not found", err)
	}
}

// partnerOversightGoldenEnv names a file of the existing feed's answers for
// Partner Monitoring with partner work in it (internal/partneroversight/
// testdata/golden.py writes it). Without it the comparison is skipped.
const partnerOversightGoldenEnv = "EDIFY_PARTNER_OVERSIGHT_GOLDEN"

// partnerOversightTables is the order the golden's rows are filed in (a
// row before the rows that point at it) and, reversed, the order they
// leave.
var partnerOversightTables = []string{"partner", "activity", "partner_assignment", "activity_schedule_cost_line", "evidence_record", "partner_assignment_withdrawal"}

// filePartnerOversightGolden reads the golden, files its rows and returns
// its answers; the rows leave when the test ends.
func filePartnerOversightGolden(t *testing.T) []goldenAnswer {
	t.Helper()
	path := os.Getenv(partnerOversightGoldenEnv)
	if path == "" {
		t.Skip(partnerOversightGoldenEnv + " is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden hrRegisterGolden
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	kampala, err := time.LoadLocation("Africa/Kampala")
	if err != nil {
		t.Fatal(err)
	}
	if golden.Today != time.Now().In(kampala).Format(time.DateOnly) {
		t.Skipf("the golden answers were written on %s; their dates have moved", golden.Today)
	}
	ctx := context.Background()
	clear := func() {
		for i := len(partnerOversightTables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gpo%%'`, partnerOversightTables[i])); err != nil {
				t.Errorf("clearing %s: %v", partnerOversightTables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range partnerOversightTables {
		for _, row := range golden.Rows[table] {
			if _, err := admin.Exec(ctx, fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table), string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status,
			Body: periodInUse(t, a.Body, a.Query)})
	}
	if len(answers) == 0 {
		t.Fatal("the golden asks nothing of Partner Monitoring")
	}
	return answers
}

// periodInUse is the existing answer with its period select showing the
// period in use, as Go draws it (internal/parity/intended.json
// go-fix-period-select-partner: the existing feed always reads "week").
func periodInUse(t *testing.T, body json.RawMessage, query map[string]string) json.RawMessage {
	t.Helper()
	var page map[string]any
	if err := json.Unmarshal(body, &page); err != nil {
		t.Fatal(err)
	}
	blocks, _ := page["blocks"].([]any)
	if len(blocks) == 0 {
		return body
	}
	first, _ := blocks[0].(map[string]any)
	bar, _ := first["filters"].(map[string]any)
	selects, _ := bar["filters"].([]any)
	if len(selects) == 0 {
		return body
	}
	kind := strings.ToLower(strings.TrimSpace(query["period"]))
	switch kind {
	case "week", "month", "quarter", "fy":
	default:
		month, err := strconv.Atoi(strings.TrimSpace(query["month"]))
		quarter := strings.ToUpper(strings.TrimSpace(query["quarter"]))
		switch {
		case err == nil && month >= 1 && month <= 12:
			kind = "month"
		case quarter == "Q1" || quarter == "Q2" || quarter == "Q3" || quarter == "Q4":
			kind = "quarter"
		default:
			kind = "fy"
		}
	}
	selects[0].(map[string]any)["value"] = kind
	out, err := json.Marshal(page)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// The existing feed's Partner Monitoring over work in each state the page
// reads apart (internal/partneroversight/testdata/golden.py files it) and
// over the seed's completed FY 2026 work, for the officers and Programme
// Leads whose teams hold it.
func TestPartnerOversightWithPartnerWorkMatchesTheExistingFeed(t *testing.T) {
	compareGolden(t, partnerOversightPath, filePartnerOversightGolden(t))
}

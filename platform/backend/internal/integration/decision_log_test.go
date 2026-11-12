//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// decisionLogGoldenEnv names a file of the existing feed's answers for the
// Decision Log over many decisions (docs/migration/18-decision-log.md says
// how it is made). Without it the comparison is skipped.
const decisionLogGoldenEnv = "EDIFY_DECISION_LOG_GOLDEN"

// goldenAnswer is one answer of the existing feed, asked as one account.
type goldenAnswer struct {
	Email  string            `json:"email"`
	Query  map[string]string `json:"query"`
	Status int               `json:"status"`
	Body   json.RawMessage   `json:"body"`
}

// compareGolden asks Go each question as its account and compares the
// answer with the existing feed's as a whole message.
func compareGolden(t *testing.T, path string, answers []goldenAnswer) {
	t.Helper()
	tokens := map[string]string{}
	compared, differing := 0, 0
	for _, answer := range answers {
		token, ok := tokens[answer.Email]
		if !ok {
			borrowAccount(t, answer.Email)
			result, err := signIn(t, signInClientAt(fmt.Sprintf("10.9.7.%d", len(tokens)+1)), answer.Email, seededPassword)
			if err != nil || result.GetSession() == nil {
				t.Fatalf("signing in %s: %v", answer.Email, err)
			}
			token = result.GetSession().GetAccessToken()
			tokens[answer.Email] = token
		}
		compared++
		got, err := pageOf(token, path, answer.Query)
		if answer.Status == 404 {
			if connect.CodeOf(err) != connect.CodeNotFound {
				differing++
				t.Errorf("%s %v: %v, want not found", answer.Email, answer.Query, err)
			}
			continue
		}
		if err != nil {
			differing++
			t.Errorf("%s %v: %v", answer.Email, answer.Query, err)
			continue
		}
		want := &screensv1.GetPageResponse{}
		if err := protojson.Unmarshal(answer.Body, want); err != nil {
			t.Fatalf("%s %v: reading the existing answer: %v", answer.Email, answer.Query, err)
		}
		if !proto.Equal(got, want) {
			differing++
			g, w := protojson.Format(got), protojson.Format(want)
			at := 0
			for at < len(g) && at < len(w) && g[at] == w[at] {
				at++
			}
			t.Errorf("%s %v differs at byte %d:\n go:       …%s\n existing: …%s", answer.Email, answer.Query, at,
				g[max(at-200, 0):min(at+200, len(g))], w[max(at-200, 0):min(at+200, len(w))])
		}
	}
	t.Logf("%d answers of %d accounts compared, %d differing", compared, len(tokens), differing)
}

// goldenFreshFor is how long a file of answers holds: the windows they were
// asked over and the ages they show move with the clock, and every row is
// filed at least this far from an edge.
const goldenFreshFor = time.Hour

// skipWhenStale skips a comparison whose answers were made too long ago.
func skipWhenStale(t *testing.T, made time.Time) {
	t.Helper()
	if age := time.Since(made); age > goldenFreshFor {
		t.Skipf("the answers were made %s ago; their windows and ages have moved since", age.Round(time.Minute))
	}
}

// auditRow is one audit_log row a test files, removed when the test ends.
type auditRow struct {
	ID         string          `json:"id"`
	Action     string          `json:"action"`
	SubjectID  *string         `json:"subject_id"`
	ActorID    *string         `json:"actor_id"`
	ActorRole  *string         `json:"actor_role"`
	Payload    json.RawMessage `json:"payload"`
	Success    bool            `json:"success"`
	Reason     *string         `json:"reason"`
	CreatedAt  string          `json:"created_at"`
	SubjectKey string          `json:"subject_kind"`
}

func fileDecisions(t *testing.T, rows []auditRow) {
	t.Helper()
	ctx := context.Background()
	var already int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM audit_log WHERE id LIKE 'gpd%'`).Scan(&already); err != nil {
		t.Fatal(err)
	}
	if already != 0 {
		t.Skipf("the test database already holds %d of this test's decisions", already)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM audit_log WHERE id LIKE 'gpd%'`); err != nil {
			t.Errorf("removing the test's decisions: %v", err)
		}
	})
	for _, r := range rows {
		var payload *string
		if len(r.Payload) > 0 && string(r.Payload) != "null" {
			p := string(r.Payload)
			payload = &p
		}
		if _, err := admin.Exec(ctx, `
INSERT INTO audit_log (id, seq, action, subject_kind, subject_id, actor_id, actor_role, payload, success, reason, created_at)
VALUES ($1, NULL, $2, 'Thing', $3, $4, $5, $6::jsonb, $7, $8, $9::timestamptz)`,
			r.ID, r.Action, r.SubjectID, r.ActorID, r.ActorRole, payload, r.Success, r.Reason, r.CreatedAt); err != nil {
			t.Fatalf("filing decision %s: %v", r.ID, err)
		}
	}
}

func userIDOf(t *testing.T, email string) string {
	t.Helper()
	var id string
	if err := admin.QueryRow(context.Background(), `SELECT id FROM "user" WHERE email = $1`, email).Scan(&id); err != nil {
		t.Fatal(err)
	}
	return id
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestTheDecisionLogListsAnOfficersOwnDecisionsInTheWindow(t *testing.T) {
	me, peer := userIDOf(t, "cceo@edify.org"), userIDOf(t, "cceo1@edify.org")
	at := func(hoursAgo int) string {
		return time.Now().Add(-time.Duration(hoursAgo) * time.Hour).Format(time.RFC3339)
	}
	role, reason := "CCEO", "[Go parity check] the plan was late"
	fileDecisions(t, []auditRow{
		{ID: "gpd900001", Action: "plan_return", ActorID: &me, ActorRole: &role, Reason: &reason, Payload: json.RawMessage(`{"monthKey": "2026-11"}`), Success: true, CreatedAt: at(2)},
		{ID: "gpd900002", Action: "escalation_raise", ActorID: &me, Payload: json.RawMessage(`{"decision": "delegated_back"}`), Success: false, CreatedAt: at(30)},
		{ID: "gpd900003", Action: "plan_approve", ActorID: &peer, Success: true, CreatedAt: at(3)},
		{ID: "gpd900004", Action: "plan_approve", ActorID: &me, Success: true, CreatedAt: at(24 * 40)},
		{ID: "gpd900005", Action: "auth.login_failed", ActorID: &me, Success: true, CreatedAt: at(1)},
	})
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/decision-log", nil)
	if err != nil {
		t.Fatal(err)
	}
	table := tableOf(page)
	if table == nil || len(table.GetRows()) != 2 {
		t.Fatalf("the table: %v", table)
	}
	first, second := table.GetRows()[0].GetCells(), table.GetRows()[1].GetCells()
	if first[1].GetText() != "Returned a monthly plan Programme" || first[2].GetText() != "2026-11" || first[4].GetText() != reason {
		t.Fatalf("the latest decision: %v", first)
	}
	if second[2].GetText() != "Delegated back" || second[3].GetText() != "—" {
		t.Fatalf("the earlier decision: %v", second)
	}
	foot := page.GetBlocks()[len(page.GetBlocks())-2].GetPanel().GetItems()[0].GetText()
	if !strings.Contains(foot, "Showing the 2 most recent decisions in scope. Scope: Your own decisions · last 30 days.") {
		t.Fatalf("the footnote: %q", foot)
	}

	wider, err := pageOf(token, "/decision-log", map[string]string{"days": "90", "group": "Programme"})
	if err != nil {
		t.Fatal(err)
	}
	if rows := tableOf(wider).GetRows(); len(rows) != 2 || rows[1].GetCells()[1].GetText() != "Approved a monthly plan Programme" {
		t.Fatalf("ninety days of Programme decisions: %v", rows)
	}
}

// With the existing feed's answers on file, Go's are compared with them
// field by field, over the same decisions.
func TestTheDecisionLogMatchesTheExistingFeedOverManyDecisions(t *testing.T) {
	path := os.Getenv(decisionLogGoldenEnv)
	if path == "" {
		t.Skipf("%s is not set", decisionLogGoldenEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Now     time.Time      `json:"now"`
		Rows    []auditRow     `json:"rows"`
		Answers []goldenAnswer `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Now)
	fileDecisions(t, golden.Rows)
	compareGolden(t, "/decision-log", golden.Answers)
}

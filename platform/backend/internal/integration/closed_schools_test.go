//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"

	"connectrpc.com/connect"
	"google.golang.org/protobuf/encoding/protojson"
	"google.golang.org/protobuf/proto"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// closedSchoolsGoldenEnv names a file of the existing feed's answers for the
// archive over many closures (docs/migration/16-closed-schools.md says how
// it is made). Without it the comparison is skipped.
const closedSchoolsGoldenEnv = "EDIFY_CLOSED_SCHOOLS_GOLDEN"

// closureRow is one closure a test files, removed when the test ends. Only
// school_closure is written: the school itself is left as it is.
type closureRow struct {
	ID                  string  `json:"id"`
	SchoolID            string  `json:"school_id"`
	ClosureType         string  `json:"closure_type"`
	ReasonCategory      string  `json:"reason_category"`
	Reason              string  `json:"reason"`
	EffectiveDate       string  `json:"effective_date"`
	Enrollment          *int64  `json:"enrollment_at_closure"`
	OwnerAtClosure      *string `json:"owner_at_closure"`
	OwnerName           string  `json:"owner_name_at_closure"`
	ActivitiesCancelled int     `json:"activities_cancelled"`
	PartnersWithdrawn   int     `json:"partner_assignments_withdrawn"`
	BudgetReleased      int64   `json:"budget_released"`
	ReopenedAt          *string `json:"reopened_at"`
}

func fileClosures(t *testing.T, rows []closureRow) {
	t.Helper()
	ctx := context.Background()
	var already int
	if err := admin.QueryRow(ctx, `SELECT count(*) FROM school_closure`).Scan(&already); err != nil {
		t.Fatal(err)
	}
	if already != 0 {
		t.Skipf("the test database already holds %d closures", already)
	}
	ids := []string{}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `DELETE FROM school_closure WHERE id = ANY($1)`, ids); err != nil {
			t.Errorf("removing the test's closures: %v", err)
		}
	})
	for _, r := range rows {
		ids = append(ids, r.ID)
		if _, err := admin.Exec(ctx, `
INSERT INTO school_closure (created_at, updated_at, id, school_id, closure_type, reason_category, reason,
  effective_date, closed_by, closed_by_role, enrollment_at_closure, enrollment_source, cluster_name_at_closure,
  owner_at_closure, owner_name_at_closure, activities_cancelled, partner_assignments_withdrawn, budget_released,
  locked_activities_for_review, reopened_at, reopening_reason)
VALUES (now(), now(), $1, $2, $3, $4, $5, $6::date, 'goparity', '', $7, '', '', $8, $9, $10, $11, $12, 0, $13::timestamptz, '')`,
			r.ID, r.SchoolID, r.ClosureType, r.ReasonCategory, r.Reason, r.EffectiveDate, r.Enrollment,
			r.OwnerAtClosure, r.OwnerName, r.ActivitiesCancelled, r.PartnersWithdrawn, r.BudgetReleased, r.ReopenedAt); err != nil {
			t.Fatalf("filing closure %s: %v", r.ID, err)
		}
	}
}

func tableOf(page *screensv1.GetPageResponse) *screensv1.PageTable {
	for _, block := range page.GetBlocks() {
		if t := block.GetTable(); t != nil {
			return t
		}
	}
	return nil
}

// The gateway under test has no existing application behind it, so every
// answer here is Go's.
func TestTheArchiveListsAnOfficersClosuresNewestFirst(t *testing.T) {
	ctx := context.Background()
	rows, err := admin.Query(ctx, `
SELECT s.id, s.name FROM school s
JOIN staff_school_assignment a ON a.school_id = s.id
JOIN staff_profile sp ON sp.id = a.staff_id JOIN "user" u ON u.id = sp.user_id
WHERE u.email = 'cceo@edify.org' AND s.deleted_at IS NULL ORDER BY s.id LIMIT 3`)
	if err != nil {
		t.Fatal(err)
	}
	type school struct{ id, name string }
	schools := []school{}
	for rows.Next() {
		var s school
		if err := rows.Scan(&s.id, &s.name); err != nil {
			t.Fatal(err)
		}
		schools = append(schools, s)
	}
	rows.Close()
	if len(schools) < 3 {
		t.Skip("the seeded officer holds fewer than three schools")
	}
	day := func(ago int) string { return time.Now().UTC().AddDate(0, 0, -ago).Format("2006-01-02") }
	ten, thirty, many := int64(10), int64(1230), int64(500)
	reopened := time.Now().UTC().Format(time.RFC3339)
	fileClosures(t, []closureRow{
		{ID: "gpt000001", SchoolID: schools[0].id, ClosureType: "temporary", ReasonCategory: "financial", Reason: "[Go parity check] a", EffectiveDate: day(3), Enrollment: &ten, OwnerName: "Officer One"},
		{ID: "gpt000002", SchoolID: schools[1].id, ClosureType: "permanent", ReasonCategory: "merged", Reason: "[Go parity check] b", EffectiveDate: day(1)},
		{ID: "gpt000003", SchoolID: schools[2].id, ClosureType: "permanent", ReasonCategory: "other", Reason: "[Go parity check] c", EffectiveDate: day(2), Enrollment: &thirty},
		{ID: "gpt000004", SchoolID: schools[0].id, ClosureType: "temporary", ReasonCategory: "other", Reason: "[Go parity check] reopened", EffectiveDate: day(0), Enrollment: &many, ReopenedAt: &reopened},
	})

	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	page, err := pageOf(token, "/schools/closed", nil)
	if err != nil {
		t.Fatal(err)
	}
	if page.GetHeader().GetTitle() != "Closed Schools" || len(page.GetHeader().GetActions()) != 0 {
		t.Fatalf("the header: %v", page.GetHeader())
	}
	figures := page.GetBlocks()[0].GetStrip().GetMetrics()
	if figures[0].GetValue() != "3" || figures[2].GetValue() != "1,240" {
		t.Fatalf("closed %s and enrolment removed %s, want 3 and 1,240 (a reopened closure counts for neither)", figures[0].GetValue(), figures[2].GetValue())
	}
	table := tableOf(page)
	if table == nil || len(table.GetRows()) != 3 {
		t.Fatalf("the table: %v", table)
	}
	for i, want := range []struct {
		school          school
		kind, enrolment string
	}{
		{schools[1], "Permanently closed", "Not recorded"},
		{schools[2], "Permanently closed", "1,230"},
		{schools[0], "Temporarily closed", "10"},
	} {
		cells := table.GetRows()[i].GetCells()
		if cells[1].GetHref() != "/schools/"+want.school.id || cells[5].GetText() != want.kind || cells[7].GetText() != want.enrolment {
			t.Fatalf("row %d: %v, want %s %s %s", i, cells, want.school.name, want.kind, want.enrolment)
		}
	}
	if owner := table.GetRows()[2].GetCells()[3].GetText(); owner != "Officer One" {
		t.Fatalf("the former owner: %q", owner)
	}

	found, err := pageOf(token, "/schools/closed", map[string]string{"q": "zzz no such school"})
	if err != nil {
		t.Fatal(err)
	}
	if tableOf(found) != nil || len(found.GetHeader().GetActions()) != 1 || found.GetBlocks()[0].GetStrip().GetMetrics()[0].GetValue() != "0" {
		t.Fatalf("a search that matches nothing: %v", found)
	}
}

func TestARoleOutsideTheArchiveIsTurnedAway(t *testing.T) {
	borrowAccount(t, "coordinator@edify.org")
	token := sessionOf(t, "coordinator@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/schools/closed", nil); connect.CodeOf(err) != connect.CodeNotFound {
		t.Fatalf("a Project Coordinator opening Closed Schools: %v, want not found", err)
	}
}

// With the existing feed's answers on file, Go's are compared with them
// field by field, over the same closures.
func TestTheArchiveMatchesTheExistingFeedOverManyClosures(t *testing.T) {
	path := os.Getenv(closedSchoolsGoldenEnv)
	if path == "" {
		t.Skipf("%s is not set", closedSchoolsGoldenEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Rows    []closureRow `json:"rows"`
		Answers []struct {
			Email  string            `json:"email"`
			Query  map[string]string `json:"query"`
			Status int               `json:"status"`
			Body   json.RawMessage   `json:"body"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	fileClosures(t, golden.Rows)

	tokens := map[string]string{}
	compared, differing := 0, 0
	for _, answer := range golden.Answers {
		token, ok := tokens[answer.Email]
		if !ok {
			borrowAccount(t, answer.Email)
			result, err := signIn(t, signInClientAt(fmt.Sprintf("10.9.8.%d", len(tokens)+1)), answer.Email, seededPassword)
			if err != nil || result.GetSession() == nil {
				t.Fatalf("signing in %s: %v", answer.Email, err)
			}
			token = result.GetSession().GetAccessToken()
			tokens[answer.Email] = token
		}
		compared++
		got, err := pageOf(token, "/schools/closed", answer.Query)
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

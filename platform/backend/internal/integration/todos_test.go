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
	"github.com/jackc/pgx/v5"
)

// todosGoldenEnv names a file of the existing feed's To-Do answers over
// synthetic records (docs/migration/36-todos.md says how it is made).
// Without it the comparison is skipped.
const todosGoldenEnv = "EDIFY_TODOS_GOLDEN"

// filedRow is one record as the database held it when the existing feed
// was asked.
type filedRow struct {
	Table string          `json:"table"`
	Row   json.RawMessage `json:"row"`
}

// fileRows puts the records back exactly (ids, times and all) and removes
// them when the test ends.
func fileRows(t *testing.T, rows []filedRow) {
	t.Helper()
	ctx := context.Background()
	t.Cleanup(func() {
		for i := len(rows) - 1; i >= 0; i-- {
			r := rows[i]
			var key struct {
				ID any `json:"id"`
			}
			_ = json.Unmarshal(r.Row, &key)
			if _, err := admin.Exec(context.Background(), `DELETE FROM `+pgx.Identifier{r.Table}.Sanitize()+` WHERE id::text = $1`,
				fmt.Sprint(key.ID)); err != nil {
				t.Errorf("removing a %s row: %v", r.Table, err)
			}
		}
	})
	for _, r := range rows {
		table := pgx.Identifier{r.Table}.Sanitize()
		if _, err := admin.Exec(ctx, `INSERT INTO `+table+` SELECT * FROM json_populate_record(NULL::`+table+`, $1::json)`,
			string(r.Row)); err != nil {
			t.Fatalf("filing a %s row: %v", r.Table, err)
		}
	}
}

// With the existing feed's answers on file, Go's are compared with them as
// whole messages, over the same records: every kind of row a field
// officer's queue holds that the seed lacks.
func TestTodosMatchTheExistingFeedOverSyntheticRecords(t *testing.T) {
	path := os.Getenv(todosGoldenEnv)
	if path == "" {
		t.Skipf("%s is not set", todosGoldenEnv)
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Today   string         `json:"today"`
		Rows    []filedRow     `json:"rows"`
		Answers []goldenAnswer `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if today := time.Now().In(time.FixedZone("EAT", 3*3600)).Format("2006-01-02"); today != golden.Today {
		t.Skipf("the answers were made on %s; today is %s, so every due day has moved", golden.Today, today)
	}
	fileRows(t, golden.Rows)
	compareGolden(t, "/todos", golden.Answers)
}

// A record Go does not build rows from yet (here a school action handed to
// the officer) passes the officer on to the existing application, which
// this gateway does not have; without one the officer's queue is Go's.
func TestTodosPassAReaderOnWhenAGuardedRecordIsTheirs(t *testing.T) {
	ctx := context.Background()
	me, lead := userIDOf(t, "cceo@edify.org"), userIDOf(t, "pl1@edify.org")
	borrowAccount(t, "cceo@edify.org")
	token := sessionOf(t, "cceo@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/todos", nil); err != nil {
		t.Fatalf("the officer's queue without a school action: %v", err)
	}
	var school string
	if err := admin.QueryRow(ctx, `SELECT id FROM school WHERE deleted_at IS NULL ORDER BY id LIMIT 1`).Scan(&school); err != nil {
		t.Fatal(err)
	}
	fileTeamActions(t, []teamActionRow{{ID: "gpa910001", CreatedAt: time.Now().Format(time.RFC3339), ConditionKey: "gpa-todo-1",
		IssueType: "no_visit", SchoolID: school, SenderID: lead, RecipientID: me, RequestedAction: "[Go parity check] Visit",
		WorkflowRoute: "/schools/" + school, State: "open"}})
	if _, err := pageOf(token, "/todos", nil); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("with a school action: %v, want it passed to the existing application", err)
	}
	// pl1 is passed on here too: one of the Programme Lead's guards finds a
	// record in this database (docs/migration/55-todos-pl.md).
	borrowAccount(t, "pl1@edify.org")
	leadToken := sessionOf(t, "pl1@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(leadToken, "/todos", nil); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("the Programme Lead: %v, want it passed to the existing application", err)
	}
}

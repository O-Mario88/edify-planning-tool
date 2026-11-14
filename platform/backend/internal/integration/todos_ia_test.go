//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"

	"connectrpc.com/connect"
)

// todosIAGoldenEnv names a file of the existing feed's To-Do answers for
// Impact Assessment over synthetic records (docs/migration/56 says how it
// is made). Without it the comparison is skipped.
const todosIAGoldenEnv = "EDIFY_TODOS_IA_GOLDEN"

// Impact Assessment's queue over the same records as the existing feed's:
// activities awaiting verification (staff with a Salesforce ID, partner,
// a cluster's), collection work, blocked import rows, a returned SSA and
// the schools with no training planned, as whole messages.
func TestTodosIAMatchTheExistingFeedOverSyntheticRecords(t *testing.T) {
	path := os.Getenv(todosIAGoldenEnv)
	if path == "" {
		t.Skipf("%s is not set", todosIAGoldenEnv)
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

// A record only a guarded builder reads (here an SSA record awaiting a
// verifier, which ia_queue_todos counts; an existing record is set pending
// and put back) passes Impact Assessment on to the
// existing application; without one the queue is Go's.
func TestTodosIAPassedOnWhenAGuardedRecordExists(t *testing.T) {
	ctx := context.Background()
	borrowAccount(t, "ia@edify.org")
	token := sessionOf(t, "ia@edify.org", seededPassword).GetAccessToken()
	if _, err := pageOf(token, "/todos", nil); err != nil {
		t.Fatalf("Impact Assessment's queue with nothing guarded: %v", err)
	}
	var record, status string
	if err := admin.QueryRow(ctx, `SELECT id, verification_status FROM ssa_record
WHERE deleted_at IS NULL AND verification_status <> 'pending' ORDER BY id LIMIT 1`).Scan(&record, &status); err != nil {
		t.Fatal(err)
	}
	if _, err := admin.Exec(ctx, `UPDATE ssa_record SET verification_status = 'pending' WHERE id = $1`, record); err != nil {
		t.Fatalf("setting an SSA record pending: %v", err)
	}
	t.Cleanup(func() {
		if _, err := admin.Exec(context.Background(), `UPDATE ssa_record SET verification_status = $2 WHERE id = $1`, record, status); err != nil {
			t.Errorf("restoring the SSA record: %v", err)
		}
	})
	if _, err := pageOf(token, "/todos", nil); connect.CodeOf(err) != connect.CodeUnavailable {
		t.Fatalf("with a pending SSA record: %v, want it passed to the existing application", err)
	}
}

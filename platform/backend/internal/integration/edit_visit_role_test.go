//go:build integration

package integration

import (
	"context"
	"testing"

	"github.com/jackc/pgx/v5"
)

// The fourth save, editing a visit's words (docs/migration/31): the gateway
// locks the visit's row and writes its goal and expected outcome, and
// nothing else of it (TestGatewayRoleCanNeitherWriteNorReadSecrets refuses
// its focus, purpose and SSA verdict). Everything here is rolled back.
func TestTheActivitiesWriterRoleMakesTheEditsWrite(t *testing.T) {
	ctx := context.Background()
	var id string
	if err := admin.QueryRow(ctx, `SELECT id FROM activity WHERE deleted_at IS NULL ORDER BY id LIMIT 1`).Scan(&id); err != nil {
		t.Skipf("the test database has no activity (%v)", err)
	}
	tx, err := gateway.BeginTx(ctx, pgx.TxOptions{AccessMode: pgx.ReadWrite})
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = tx.Rollback(ctx) }()
	var status string
	if err := tx.QueryRow(ctx, `SELECT status FROM activity WHERE id = $1 AND deleted_at IS NULL FOR UPDATE`, id).Scan(&status); err != nil {
		t.Fatalf("locking the visit: %v", err)
	}
	tag, err := tx.Exec(ctx, `UPDATE activity SET activity_purpose_text = $2, expected_outcome = $3, updated_at = now()
WHERE id = $1`, id, "[Go edit check] goal", "[Go edit check] outcome")
	if err != nil || tag.RowsAffected() != 1 {
		t.Fatalf("the edit's write: %v (%d rows)", err, tag.RowsAffected())
	}
}

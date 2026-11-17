//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
)

// fileGoldenRows files a golden's rows, table by table in the order given,
// in one transaction: a deferred foreign key is checked once every row is
// in, so a child the golden dumped before its parent (rows are dumped in
// their stored order, and an updated parent moves after its child) files.
func fileGoldenRows(t *testing.T, ctx context.Context, tables []string, rows map[string][]json.RawMessage) {
	t.Helper()
	tx, err := admin.Begin(ctx)
	if err != nil {
		t.Fatal(err)
	}
	for _, table := range tables {
		for _, row := range rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if _, err := tx.Exec(ctx, sql, string(row)); err != nil {
				_ = tx.Rollback(ctx)
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	if err := tx.Commit(ctx); err != nil {
		t.Fatalf("filing the rows: %v", err)
	}
}

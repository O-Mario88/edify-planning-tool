//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// ThePolicyResponsePageMatchesTheExistingPage files the policies and
// disagreements internal/uploadcenter/testdata/restricted_golden.py filed,
// asks /policy-agreement/restricted as each reader the golden asked, and
// compares the whole page. Skipped unless EDIFY_POLICY_RESTRICTED_GOLDEN
// names that file, written within the hour.
func TestThePolicyResponsePageMatchesTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_POLICY_RESTRICTED_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_POLICY_RESTRICTED_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		Written time.Time                    `json:"written"`
		Tables  map[string][]json.RawMessage `json:"tables"`
		Answers []goldenAnswer               `json:"answers"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	skipWhenStale(t, golden.Written)
	ctx := context.Background()
	// Children first; filed parents first, a document's current version
	// set once its versions are filed.
	tables := []string{"document_acknowledgement", "document_version", "document_asset"}
	clear := func() {
		if _, err := admin.Exec(ctx, `UPDATE document_asset SET current_version_id = NULL WHERE id LIKE 'gprd%'`); err != nil {
			t.Errorf("unlinking the versions: %v", err)
		}
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE 'gprd%'`); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	versions := map[string]string{}
	for i := len(tables) - 1; i >= 0; i-- {
		for _, row := range golden.Tables[tables[i]] {
			if tables[i] == "document_asset" {
				var d struct {
					ID      string  `json:"id"`
					Current *string `json:"current_version_id"`
				}
				if err := json.Unmarshal(row, &d); err != nil {
					t.Fatal(err)
				}
				if d.Current != nil {
					versions[d.ID] = *d.Current
				}
				if _, err := admin.Exec(ctx, `INSERT INTO document_asset SELECT * FROM json_populate_record(NULL::document_asset,
					(($1::jsonb) || '{"current_version_id": null}')::json)`, string(row)); err != nil {
					t.Fatalf("filing a document: %v", err)
				}
				continue
			}
			if _, err := admin.Exec(ctx, `INSERT INTO "`+tables[i]+`" SELECT * FROM json_populate_record(NULL::"`+tables[i]+`", $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", tables[i], err)
			}
		}
	}
	for document, version := range versions {
		if _, err := admin.Exec(ctx, `UPDATE document_asset SET current_version_id = $2 WHERE id = $1`, document, version); err != nil {
			t.Fatalf("linking a document's version: %v", err)
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/policy-agreement/restricted", golden.Answers)
}

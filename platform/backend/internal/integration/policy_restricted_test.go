//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// comparePolicyPage files the policies, versions and answers a policy
// golden filed (every id starting prefix), asks page as each reader the
// golden asked, and compares the whole page. Skipped unless env names that
// golden, written within the hour.
func comparePolicyPage(t *testing.T, env, prefix, page string) {
	path := os.Getenv(env)
	if path == "" {
		t.Skip(env + " is not set")
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
		if _, err := admin.Exec(ctx, `UPDATE document_asset SET current_version_id = NULL WHERE id LIKE $1`, prefix+"%"); err != nil {
			t.Errorf("unlinking the versions: %v", err)
		}
		for _, table := range tables {
			if _, err := admin.Exec(ctx, `DELETE FROM "`+table+`" WHERE id LIKE $1`, prefix+"%"); err != nil {
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
	compareGolden(t, page, golden.Answers)
}

// TestThePolicyResponsePageMatchesTheExistingPage compares the policy
// response page under the policies and disagreements
// internal/uploadcenter/testdata/restricted_golden.py filed.
func TestThePolicyResponsePageMatchesTheExistingPage(t *testing.T) {
	comparePolicyPage(t, "EDIFY_POLICY_RESTRICTED_GOLDEN", "gprd", "/policy-agreement/restricted")
}

// TestThePolicyAgreementCenterMatchesTheExistingPage compares the Policy
// Agreement Center under the policies and answers
// internal/uploadcenter/testdata/agreement_golden.py filed.
func TestThePolicyAgreementCenterMatchesTheExistingPage(t *testing.T) {
	comparePolicyPage(t, "EDIFY_POLICY_AGREEMENT_GOLDEN", "gpag", "/policy-agreement")
}

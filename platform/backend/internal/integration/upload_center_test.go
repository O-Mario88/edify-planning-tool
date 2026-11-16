//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"testing"
	"time"
)

// uploadTables is the order the golden's rows are filed in (a row before
// the rows that point at it; a document's current version is linked once
// its versions are filed) and, reversed, the order they leave.
var uploadTables = []string{
	"document_asset", "document_version", "document_audience_rule", "document_acknowledgement",
	"school_import_batch", "ssa_import_batch", "ssa_import_row",
}

// The existing feed's Upload Center over uploads the seed lacks (documents
// in each state and audience, a mandatory policy with an overdue signature,
// training resources aimed at a role, a slug, a person, a future day and
// nobody, school and SSA import batches), for every reader it opens for
// with each tab, a type, a status, a search and pages, and for readers it
// refuses. Skipped unless EDIFY_UPLOAD_CENTER_GOLDEN names a file
// internal/uploadcenter/testdata/golden.py wrote within the half hour.
func TestTheUploadCenterMatchesTheExistingFeedOverUploadsTheSeedLacks(t *testing.T) {
	path := os.Getenv("EDIFY_UPLOAD_CENTER_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_UPLOAD_CENTER_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		hrRegisterGolden
		Written time.Time `json:"written"`
	}
	if err := json.Unmarshal(raw, &golden); err != nil {
		t.Fatal(err)
	}
	if time.Since(golden.Written) > 30*time.Minute {
		t.Skipf("the golden answers were written at %s; their times have moved", golden.Written)
	}
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `UPDATE document_asset SET current_version_id = NULL WHERE id LIKE 'gup%'`); err != nil {
			t.Errorf("unlinking the documents' versions: %v", err)
		}
		for i := len(uploadTables) - 1; i >= 0; i-- {
			table := uploadTables[i]
			if table == "document_asset" {
				// The versions point at their documents: they leave first.
				if _, err := admin.Exec(ctx, `DELETE FROM document_version WHERE id LIKE 'gup%'`); err != nil {
					t.Errorf("clearing document_version: %v", err)
				}
			}
			if _, err := admin.Exec(ctx, fmt.Sprintf(`DELETE FROM %s WHERE id LIKE 'gup%%'`, table)); err != nil {
				t.Errorf("clearing %s: %v", table, err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range uploadTables {
		for _, row := range golden.Rows[table] {
			sql := fmt.Sprintf(`INSERT INTO %s SELECT * FROM json_populate_record(NULL::%s, $1::json)`, table, table)
			if table == "document_asset" {
				sql = `INSERT INTO document_asset SELECT * FROM json_populate_record(NULL::document_asset,
					($1::jsonb || '{"current_version_id": null}')::json)`
			}
			if _, err := admin.Exec(ctx, sql, string(row)); err != nil {
				t.Fatalf("filing a %s row: %v", table, err)
			}
		}
	}
	for _, row := range golden.Rows["document_asset"] {
		var d struct {
			ID      string  `json:"id"`
			Version *string `json:"current_version_id"`
		}
		if err := json.Unmarshal(row, &d); err != nil {
			t.Fatal(err)
		}
		if _, err := admin.Exec(ctx, `UPDATE document_asset SET current_version_id = $2 WHERE id = $1`, d.ID, d.Version); err != nil {
			t.Fatalf("linking a document's version: %v", err)
		}
	}
	answers := []goldenAnswer{}
	for _, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
	}
	if len(answers) == 0 {
		t.Fatal("the golden asks nothing of the Upload Center")
	}
	compareGolden(t, "/uploads", answers)
}

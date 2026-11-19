//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// TestSchoolEvidenceLearningResultsMatchTheExistingPage files the class
// results internal/schoolevidence/testdata/learning_golden.py filed, asks
// /ia/school-evidence/ as each reader the golden asked, and compares the
// whole page. Skipped unless EDIFY_SCHOOL_EVIDENCE_GOLDEN names that file,
// written within the hour.
func TestSchoolEvidenceLearningResultsMatchTheExistingPage(t *testing.T) {
	path := os.Getenv("EDIFY_SCHOOL_EVIDENCE_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_SCHOOL_EVIDENCE_GOLDEN is not set")
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
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM impact_learning_result WHERE id LIKE 'gsev%'`); err != nil {
			t.Errorf("clearing the results: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Tables["impact_learning_result"] {
		if _, err := admin.Exec(ctx, `INSERT INTO impact_learning_result SELECT * FROM json_populate_record(NULL::impact_learning_result, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a result: %v", err)
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/ia/school-evidence/", golden.Answers)
}

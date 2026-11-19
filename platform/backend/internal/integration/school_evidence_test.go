//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"testing"
	"time"
)

// compareSchoolEvidence files the rows a School Evidence golden filed (every
// id starting prefix, in each table, in order), asks /ia/school-evidence/ as
// each reader the golden asked, and compares the whole page. Skipped unless
// env names that golden, written within the hour.
func compareSchoolEvidence(t *testing.T, env, prefix string, tables ...string) {
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
	clear := func() {
		for i := len(tables) - 1; i >= 0; i-- {
			if _, err := admin.Exec(ctx, `DELETE FROM `+tables[i]+` WHERE id LIKE $1`, prefix+"%"); err != nil {
				t.Errorf("clearing %s: %v", tables[i], err)
			}
		}
	}
	clear()
	t.Cleanup(clear)
	for _, table := range tables {
		for _, row := range golden.Tables[table] {
			if _, err := admin.Exec(ctx, `INSERT INTO `+table+` SELECT * FROM json_populate_record(NULL::`+table+`, $1::json)`, string(row)); err != nil {
				t.Fatalf("filing a row of %s: %v", table, err)
			}
		}
	}
	if len(golden.Answers) == 0 {
		t.Fatal("the golden asks nothing")
	}
	compareGolden(t, "/ia/school-evidence/", golden.Answers)
}

// TestSchoolEvidenceLearningResultsMatchTheExistingPage compares the
// Learning tab under the class results
// internal/schoolevidence/testdata/learning_golden.py filed.
func TestSchoolEvidenceLearningResultsMatchTheExistingPage(t *testing.T) {
	compareSchoolEvidence(t, "EDIFY_SCHOOL_EVIDENCE_GOLDEN", "gsev", "impact_learning_result")
}

// TestSchoolEvidenceDiscipleshipMatchesTheExistingPage compares the
// Discipleship tab under the records and change stories
// internal/schoolevidence/testdata/discipleship_golden.py filed.
func TestSchoolEvidenceDiscipleshipMatchesTheExistingPage(t *testing.T) {
	compareSchoolEvidence(t, "EDIFY_SCHOOL_EVIDENCE_DISCIPLESHIP_GOLDEN", "gsed", "impact_discipleship_record", "mscs_story")
}

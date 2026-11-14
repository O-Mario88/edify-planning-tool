//go:build integration

package integration

import (
	"context"
	"encoding/json"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/audit"
)

type auditedRead struct {
	Action      string         `json:"action"`
	SubjectKind *string        `json:"subject_kind"`
	SubjectID   *string        `json:"subject_id"`
	ActorID     *string        `json:"actor_id"`
	ActorRole   *string        `json:"actor_role"`
	Success     bool           `json:"success"`
	Payload     map[string]any `json:"payload"`
}

// The existing feed's Employee Relations over cases the seed does not hold
// (every type, status and severity, two countries, confidential cases worked
// by HR and not), with HR's searches, Admin, Impact Assessment and a CCEO who
// may not open it; and the audit row each reading appends: the same action,
// subject, actor, role and payload as the existing application's, sealed onto
// the one chain so the existing verifier accepts it. Skipped unless
// EDIFY_EMPLOYEE_RELATIONS_GOLDEN names a file internal/hrregister/testdata/
// employee_relations_golden.py wrote today.
func TestEmployeeRelationsMatchesTheExistingFeedAndAuditsEachRead(t *testing.T) {
	path := os.Getenv("EDIFY_EMPLOYEE_RELATIONS_GOLDEN")
	if path == "" {
		t.Skip("EDIFY_EMPLOYEE_RELATIONS_GOLDEN is not set")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var golden struct {
		hrRegisterGolden
		Audited [][]auditedRead
	}
	if err := json.Unmarshal(raw, &golden.hrRegisterGolden); err != nil {
		t.Fatal(err)
	}
	var withAudit struct {
		Answers []struct {
			Audited []auditedRead `json:"audited"`
		} `json:"answers"`
	}
	if err := json.Unmarshal(raw, &withAudit); err != nil {
		t.Fatal(err)
	}
	if golden.Today != time.Now().In(mustNairobi(t)).Format(time.DateOnly) {
		t.Skipf("the golden answers were written on %s", golden.Today)
	}
	ctx := context.Background()
	clear := func() {
		if _, err := admin.Exec(ctx, `DELETE FROM hr_relations_case WHERE id LIKE 'gpe%'`); err != nil {
			t.Errorf("clearing the cases: %v", err)
		}
	}
	clear()
	t.Cleanup(clear)
	for _, row := range golden.Rows["hr_relations_case"] {
		if _, err := admin.Exec(ctx, `INSERT INTO hr_relations_case SELECT * FROM json_populate_record(NULL::hr_relations_case, $1::json)`, string(row)); err != nil {
			t.Fatalf("filing a case: %v", err)
		}
	}
	var before int64
	if err := admin.QueryRow(ctx, `SELECT COALESCE(max(seq), 0) FROM audit_log`).Scan(&before); err != nil {
		t.Fatal(err)
	}
	answers := []goldenAnswer{}
	want := []auditedRead{}
	for i, a := range golden.Answers {
		answers = append(answers, goldenAnswer{Email: a.Email, Query: a.Query, Status: a.Status, Body: a.Body})
		want = append(want, withAudit.Answers[i].Audited...)
	}
	compareGolden(t, "/employee-relations", answers)

	rows, err := admin.Query(ctx, `
SELECT seq, action, subject_kind, subject_id, actor_id, actor_role, success, reason, ip_address, user_agent,
       correlation_id, payload, prev_hash, hash,
       (SELECT hash FROM audit_log p WHERE p.seq = a.seq - 1)
FROM audit_log a WHERE seq > $1 AND action = 'hr.er_accessed' ORDER BY seq`, before)
	if err != nil {
		t.Fatal(err)
	}
	defer rows.Close()
	got := []auditedRead{}
	for rows.Next() {
		var (
			seq                                 int64
			r                                   auditedRead
			reason, ip, agent, correlation      *string
			payload                             []byte
			prevHash, hash, previousRowsOwnHash *string
		)
		if err := rows.Scan(&seq, &r.Action, &r.SubjectKind, &r.SubjectID, &r.ActorID, &r.ActorRole, &r.Success,
			&reason, &ip, &agent, &correlation, &payload, &prevHash, &hash, &previousRowsOwnHash); err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(payload, &r.Payload); err != nil {
			t.Fatalf("row %d's payload: %v", seq, err)
		}
		got = append(got, r)
		if ip == nil || agent == nil || correlation == nil {
			t.Errorf("row %d does not record where the reading came from: %v %v %v", seq, ip, agent, correlation)
		}
		// Sealed onto the chain: linked to the row before and hashed as the
		// existing application hashes.
		if prevHash == nil || previousRowsOwnHash == nil || *prevHash != *previousRowsOwnHash {
			t.Errorf("row %d is not linked to the row before it", seq)
			continue
		}
		canonical, err := audit.Canonical(audit.Entry{
			Action: r.Action, SubjectKind: r.SubjectKind, SubjectID: r.SubjectID, ActorID: r.ActorID,
			ActorRole: r.ActorRole, Success: r.Success, Reason: reason, IPAddress: ip, UserAgent: agent,
			CorrelationID: correlation, Payload: r.Payload,
		})
		if err != nil {
			t.Fatal(err)
		}
		if hash == nil || *hash != audit.ChainHash(*prevHash, canonical) {
			t.Errorf("row %d's hash is not the chain's", seq)
		}
	}
	if err := rows.Err(); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("audit rows:\n got %+v\nwant %+v", got, want)
	}
	t.Logf("%d readings audited as the existing application audits them", len(got))
}

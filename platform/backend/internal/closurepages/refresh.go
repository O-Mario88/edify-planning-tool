package closurepages

// The closure_checklist_refresh job (ClosureEligibilityService.refresh_open):
// every open activity's closure checklist and blockers persisted from its
// facts (the same facts the readiness queue reads), written only where they
// changed. A blocker that still applies keeps its row, so its age is the age
// of the block; blockers that no longer apply, and duplicates, are removed
// through gateway_closure.remove_blockers. Inside the caller's transaction.

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// openExcluded are OPEN_EXCLUDED_STATUSES.
var openExcluded = []string{"not_planned", "planned", "scheduled", "rescheduled", "assigned_to_partner",
	"partner_scheduled", "closed"}

// blockerRule is one of _BLOCKER_RULES.
type blockerRule struct {
	met         func(storedFacts) bool
	financeOnly bool
	reason      string
	role        string
}

// storedFacts are the nine checks a checklist stores.
type storedFacts struct {
	closureFacts
	auditTrail bool
}

var blockerRules = []blockerRule{
	{func(f storedFacts) bool { return f.executed }, false, "Activity not executed", "CCEO"},
	{func(f storedFacts) bool { return f.evidence }, false, "Evidence Missing", "CCEO"},
	{func(f storedFacts) bool { return f.salesforce }, false, "Activity SF ID Missing", "CCEO"},
	{func(f storedFacts) bool { return f.verified }, false, "IA not verified", "ImpactAssessment"},
	{func(f storedFacts) bool { return f.accountsCleared }, true, "Accounts not cleared", "Accountant"},
	{func(f storedFacts) bool { return f.netsuiteEntered }, true, "NetSuite ID missing", "Accountant"},
	{func(f storedFacts) bool { return f.published }, false, "Analytics not published", "ImpactAssessment"},
}

// specs is blocker_specs: (reason, role) for every unmet check, in rule order.
func (f storedFacts) specs() [][2]string {
	var out [][2]string
	for _, r := range blockerRules {
		if !r.met(f) && (f.financeRequired || !r.financeOnly) {
			out = append(out, [2]string{r.reason, r.role})
		}
	}
	return out
}

func (f storedFacts) columns() []bool {
	return []bool{f.executed, f.evidence, f.salesforce, f.verified, f.financeRequired, f.accountsCleared,
		f.netsuiteEntered, f.published, f.auditTrail}
}

const refreshBatch = 500

// RefreshOpen is refresh_open; it says how many checklists it wrote.
func RefreshOpen(ctx context.Context, tx pgx.Tx, now time.Time) (int, error) {
	written, last := 0, ""
	for {
		batch, err := openBatch(ctx, tx, last)
		if err != nil {
			return written, err
		}
		if len(batch) == 0 {
			return written, nil
		}
		last = batch[len(batch)-1].id
		n, err := persistBatch(ctx, tx, batch, now)
		if err != nil {
			return written, err
		}
		written += n
	}
}

type openActivity struct {
	id    string
	facts storedFacts
}

// openBatch is the next 500 open activities by id, with their facts.
func openBatch(ctx context.Context, tx pgx.Tx, after string) ([]openActivity, error) {
	q := rules.Queue
	moved := `SELECT 1 FROM advance_request r WHERE r.activity_id = a.id AND r.status = ANY($3)`
	rows, err := tx.Query(ctx, `
SELECT a.id, a.activity_type, a.status, COALESCE(a.delivery_type, ''), COALESCE(a.payment_status, ''),
  COALESCE(a.salesforce_activity_id, ''), UPPER(COALESCE(a.salesforce_record_type_snapshot, '')),
  EXISTS (SELECT 1 FROM evidence_record e WHERE e.activity_id = a.id AND NOT e.quarantined),
  EXISTS (SELECT 1 FROM activity_schedule_cost_line l WHERE l.activity_id = a.id),
  EXISTS (SELECT 1 FROM netsuite_expense_record n WHERE n.activity_id = a.id),
  EXISTS (SELECT 1 FROM advance_request r WHERE r.activity_id = a.id AND r.status = ANY($4)),
  EXISTS (`+moved+`),
  EXISTS (`+moved+` AND (r.accountability_netsuite_id IS NULL OR r.accountability_netsuite_id = '')),
  COALESCE((SELECT pr.status FROM analytics_publish_record pr WHERE pr.activity_id = a.id LIMIT 1), ''),
  EXISTS (SELECT 1 FROM activity_timeline_event t WHERE t.activity_id = a.id)
FROM activity a
WHERE a.deleted_at IS NULL AND NOT (a.status = ANY($2)) AND a.id > $1
ORDER BY a.id LIMIT `+strconv.Itoa(refreshBatch), after, openExcluded, q.MovedAdvance, q.ClearedAdvance)
	if err != nil {
		return nil, fmt.Errorf("closurepages: reading the open activities: %w", err)
	}
	defer rows.Close()
	var out []openActivity
	for rows.Next() {
		var a closureItem
		var timeline bool
		if err := rows.Scan(&a.id, &a.kind, &a.status, &a.delivery, &a.payment, &a.salesforce, &a.recordType, &a.evidence,
			&a.costLines, &a.netsuite, &a.cleared, &a.moved, &a.unaccounted, &a.publish, &timeline); err != nil {
			return nil, err
		}
		out = append(out, openActivity{id: a.id, facts: storedFacts{closureFacts: a.facts(), auditTrail: timeline}})
	}
	return out, rows.Err()
}

// persistBatch is _persist_batch.
func persistBatch(ctx context.Context, tx pgx.Tx, batch []openActivity, now time.Time) (int, error) {
	ids := make([]string, 0, len(batch))
	for _, a := range batch {
		ids = append(ids, a.id)
	}
	current := map[string][]bool{}
	rows, err := tx.Query(ctx, `SELECT activity_id, activity_executed, evidence_uploaded, salesforce_id_entered, ia_verified,
  finance_required, accounts_cleared, netsuite_id_entered, analytics_published, audit_trail_saved
FROM closure_checklist WHERE activity_id = ANY($1)`, ids)
	if err != nil {
		return 0, fmt.Errorf("closurepages: reading the checklists: %w", err)
	}
	for rows.Next() {
		var id string
		v := make([]bool, 9)
		if err := rows.Scan(&id, &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7], &v[8]); err != nil {
			rows.Close()
			return 0, err
		}
		current[id] = v
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, err
	}
	written := 0
	for _, a := range batch {
		want := a.facts.columns()
		have, ok := current[a.id]
		if ok && equalBools(have, want) {
			continue
		}
		args := []any{a.id, now, want[0], want[1], want[2], want[3], want[4], want[5], want[6], want[7], want[8]}
		if ok {
			_, err = tx.Exec(ctx, `UPDATE closure_checklist SET activity_executed = $3, evidence_uploaded = $4,
  salesforce_id_entered = $5, ia_verified = $6, finance_required = $7, accounts_cleared = $8, netsuite_id_entered = $9,
  analytics_published = $10, audit_trail_saved = $11, last_evaluated_at = $2, updated_at = $2 WHERE activity_id = $1`, args...)
		} else {
			_, err = tx.Exec(ctx, `INSERT INTO closure_checklist (id, created_at, updated_at, activity_id, activity_executed,
  evidence_uploaded, salesforce_id_entered, ia_verified, finance_required, accounts_cleared, netsuite_id_entered,
  analytics_published, audit_trail_saved, last_evaluated_at)
VALUES ($12, $2, $2, $1, $3, $4, $5, $6, $7, $8, $9, $10, $11, $2) ON CONFLICT DO NOTHING`, append(args, cuid.New())...)
		}
		if err != nil {
			return written, fmt.Errorf("closurepages: writing a checklist: %w", err)
		}
		written++
	}
	return written, reconcileBlockers(ctx, tx, batch, ids, now)
}

// reconcileBlockers is _reconcile_blockers for the batch.
func reconcileBlockers(ctx context.Context, tx pgx.Tx, batch []openActivity, ids []string, now time.Time) error {
	type blocker struct{ id, reason, role string }
	existing := map[string][]blocker{}
	rows, err := tx.Query(ctx, `SELECT id, activity_id, blocking_reason, responsible_role FROM closure_blocker
WHERE activity_id = ANY($1) ORDER BY created_at, id`, ids)
	if err != nil {
		return fmt.Errorf("closurepages: reading the blockers: %w", err)
	}
	for rows.Next() {
		var b blocker
		var activity string
		if err := rows.Scan(&b.id, &activity, &b.reason, &b.role); err != nil {
			rows.Close()
			return err
		}
		existing[activity] = append(existing[activity], b)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}
	var stale []string
	for _, a := range batch {
		wanted := a.facts.specs()
		isWanted := map[[2]string]bool{}
		for _, w := range wanted {
			isWanted[w] = true
		}
		kept := map[[2]string]bool{}
		for _, b := range existing[a.id] {
			key := [2]string{b.reason, b.role}
			if isWanted[key] && !kept[key] {
				kept[key] = true
			} else {
				stale = append(stale, b.id)
			}
		}
		for _, w := range wanted {
			if kept[w] {
				continue
			}
			if _, err := tx.Exec(ctx, `INSERT INTO closure_blocker (id, created_at, updated_at, activity_id, blocking_reason,
  responsible_role) VALUES ($1, $2, $2, $3, $4, $5)`, cuid.New(), now, a.id, w[0], w[1]); err != nil {
				return fmt.Errorf("closurepages: recording a blocker: %w", err)
			}
		}
	}
	if len(stale) > 0 {
		if _, err := tx.Exec(ctx, `SELECT gateway_closure.remove_blockers($1)`, stale); err != nil {
			return fmt.Errorf("closurepages: removing the blockers that no longer apply: %w", err)
		}
	}
	return nil
}

func equalBools(a, b []bool) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

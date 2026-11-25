package targets

// target_ledger_sync: every active CCEO's and Program Lead's achievement
// ledger for the operational year, rebuilt and stored, as
// TargetAchievementService.rebuild stores it: a new source's row inserted
// (validated sources stamped validated now), a changed source's row moved
// and rewritten (its updated_at left as it was read, as the existing bulk
// update leaves it), and a row whose source left the year's workflow
// reversed. Marks are not cleared: the rebuild never clears them, and a page
// still refreshes a marked person as before. Inside the caller's transaction.

import (
	"context"
	"fmt"
	"slices"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// SyncLedgers is the target_ledger_sync job for the year; it says how many
// people it rebuilt.
func SyncLedgers(ctx context.Context, tx pgx.Tx, fy string, now time.Time) (int, error) {
	people, err := ledgerPeople(ctx, tx)
	if err != nil || len(people) == 0 {
		return 0, err
	}
	active, err := activeAreas(ctx, tx)
	if err != nil {
		return 0, err
	}
	areaIDs, err := areaIDsByKey(ctx, tx)
	if err != nil {
		return 0, err
	}
	src, err := readSources(ctx, tx, people, fy)
	if err != nil {
		return 0, err
	}
	for _, p := range people {
		if err := storeLedger(ctx, tx, p, fy, active, areaIDs, src, now); err != nil {
			return 0, err
		}
	}
	return len(people), nil
}

// ledgerPeople are the job's accounts: active, not removed, holding the
// CCEO or Program Lead role, with their People record when they have one.
func ledgerPeople(ctx context.Context, tx pgx.Tx) ([]Person, error) {
	rows, err := tx.Query(ctx, `SELECT u.id, COALESCE(sp.id, '') FROM "user" u LEFT JOIN staff_profile sp ON sp.user_id = u.id
WHERE u.status = 'active' AND u.deleted_at IS NULL AND u.roles && ARRAY['CCEO', 'Program Lead']::varchar[]
ORDER BY u.created_at DESC, u.id`)
	if err != nil {
		return nil, fmt.Errorf("targets: reading the people to rebuild: %w", err)
	}
	defer rows.Close()
	var out []Person
	for rows.Next() {
		var p Person
		if err := rows.Scan(&p.UserID, &p.StaffID); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}

func areaIDsByKey(ctx context.Context, tx pgx.Tx) (map[string]string, error) {
	rows, err := tx.Query(ctx, `SELECT key, id FROM target_area WHERE active`)
	if err != nil {
		return nil, fmt.Errorf("targets: reading the target areas' ids: %w", err)
	}
	defer rows.Close()
	out := map[string]string{}
	for rows.Next() {
		var key, id string
		if err := rows.Scan(&key, &id); err != nil {
			return nil, err
		}
		out[key] = id
	}
	return out, rows.Err()
}

// storeLedger is _rebuild's flush for one person.
func storeLedger(ctx context.Context, tx pgx.Tx, p Person, fy string, active map[string]bool, areaIDs map[string]string,
	src sources, now time.Time) error {
	pending, seen, err := planLedger(p, fy, active, src)
	if err != nil {
		return err
	}
	existing := src.ledger[p.UserID]
	for key, want := range pending {
		row, ok := existing[key]
		if !ok {
			if err := insertLedgerRow(ctx, tx, p.UserID, areaIDs[want.area], key, fy, want, now); err != nil {
				return err
			}
			continue
		}
		if row.status == want.status && row.day.Equal(want.day) && row.fy == fy {
			continue
		}
		validatedAt := row.validatedAt
		if want.status == validated && validatedAt == nil {
			validatedAt = &now
		}
		if _, err := tx.Exec(ctx, `UPDATE target_achievement_ledger SET fy = $2, activity_date = $3, credited_month = $4,
  credited_quarter = $5, validation_status = $6, validated_at = $7 WHERE id = $1`,
			row.id, fy, want.day.Format(time.DateOnly), want.month, QuarterOfMonth(want.month), want.status, validatedAt); err != nil {
			return fmt.Errorf("targets: rewriting a ledger row: %w", err)
		}
	}
	var stale []string
	for key, row := range existing {
		if row.fy == fy && !seen[key] && row.status != reversed {
			stale = append(stale, row.id)
		}
	}
	if len(stale) > 0 {
		if _, err := tx.Exec(ctx, `UPDATE target_achievement_ledger SET validation_status = 'reversed', updated_at = $2
WHERE id = ANY($1)`, stale, now); err != nil {
			return fmt.Errorf("targets: reversing the ledger rows whose source left: %w", err)
		}
	}
	return nil
}

func insertLedgerRow(ctx context.Context, tx pgx.Tx, userID, areaID string, key sourceKey, fy string, want credit,
	now time.Time) error {
	var validatedAt *time.Time
	if want.status == validated {
		validatedAt = &now
	}
	if _, err := tx.Exec(ctx, `INSERT INTO target_achievement_ledger (id, created_at, updated_at, user_id, area_id,
  source_type, source_id, fy, activity_date, credited_month, credited_quarter, quantity, validation_status, validated_at)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, 1, $11, $12)
ON CONFLICT DO NOTHING`, cuid.New(), now, userID, areaID, key.kind, key.id, fy, want.day.Format(time.DateOnly),
		want.month, QuarterOfMonth(want.month), want.status, validatedAt); err != nil {
		return fmt.Errorf("targets: recording a ledger row: %w", err)
	}
	return nil
}

// CreditedActivityType is ledger_sync._credited_activity_type: whether an
// activity of this type is a source some target area counts, so its save
// can move the owner's ledger.
func CreditedActivityType(activityType string) bool {
	for _, s := range rules.Rebuild.Sources {
		if s.Kind == "activity" && slices.Contains(s.Types, activityType) {
			return true
		}
	}
	return false
}

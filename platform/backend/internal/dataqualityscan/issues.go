package dataqualityscan

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

// school is the directory record the builder reads.
type school struct {
	id                                                     string
	hasCoordinates                                         bool
	phone, contact, schoolType, subCounty, duplicateStatus *string
	enrollment                                             *int
	ownerID, ownerStatus, ownerRaw, clusterID, ssaStatus   *string
}

// issue is one DataQualityIssue the builder wants open.
type issue struct {
	schoolID, conditionKey, issueType, severity, fieldName string
	currentValue, suggestedFix                             *string
}

func operatingSchools(ctx context.Context, tx pgx.Tx) ([]school, error) {
	rows, err := tx.Query(ctx, `SELECT id, latitude IS NOT NULL AND longitude IS NOT NULL, school_phone, primary_contact_name,
  school_type, sub_county_id, duplicate_status, enrollment, account_owner_id, account_owner_status, account_owner_name_raw,
  cluster_id, current_fy_ssa_status
FROM school WHERE deleted_at IS NULL AND operational_status IN ('active', 'reopened')
ORDER BY created_at DESC`)
	if err != nil {
		return nil, fmt.Errorf("dataqualityscan: reading the operating schools: %w", err)
	}
	defer rows.Close()
	var out []school
	for rows.Next() {
		var s school
		if err := rows.Scan(&s.id, &s.hasCoordinates, &s.phone, &s.contact, &s.schoolType, &s.subCounty, &s.duplicateStatus,
			&s.enrollment, &s.ownerID, &s.ownerStatus, &s.ownerRaw, &s.clusterID, &s.ssaStatus); err != nil {
			return nil, err
		}
		out = append(out, s)
	}
	return out, rows.Err()
}

func blank(s *string) bool { return s == nil || *s == "" }

func text(s string) *string { return &s }

// conditionKey is dq_condition_key.
func conditionKey(schoolID, issueType string) string {
	return "school:" + schoolID + "|dq:" + issueType
}

// build is build_data_quality_issues for one school.
func build(s school, overrides map[string]bool) []issue {
	var out []issue
	add := func(issueType, severity, field string, current *string, fix string) {
		out = append(out, issue{schoolID: s.id, conditionKey: conditionKey(s.id, issueType), issueType: issueType, severity: severity,
			fieldName: field, currentValue: current, suggestedFix: text(fix)})
	}
	if !s.hasCoordinates && !overrides[s.id] {
		add("no_coordinates", "warning", "latitude", nil,
			"Capture GPS coordinates on the next visit, or set a geo point in Route Intelligence")
	}
	if blank(s.phone) {
		add("missing_phone", "warning", "school_phone", nil, "Add school phone number")
	}
	if blank(s.contact) {
		add("missing_contact", "warning", "primary_contact_name", nil, "Add primary contact name")
	}
	if s.enrollment == nil || *s.enrollment <= 0 {
		var current *string
		if s.enrollment != nil {
			current = text(strconv.Itoa(*s.enrollment))
		}
		add("missing_enrollment", "warning", "enrollment", current, "Update school pupil enrollment counts")
	}
	if blank(s.schoolType) {
		add("missing_school_type", "warning", "school_type", nil, "Specify whether school is Core, Client, or Partner")
	}
	if blank(s.subCounty) {
		add("missing_sub_county", "warning", "sub_county", nil, "Assign sub-county location")
	}
	if s.duplicateStatus != nil && *s.duplicateStatus == "potential" {
		add("duplicate_risk", "warning", "duplicate_status", nil, "Review and resolve potential duplicate school conflict")
	}
	if blank(s.ownerID) || s.ownerStatus == nil || *s.ownerStatus != "matched" {
		add("unmatched_staff", "warning", "account_owner_id", s.ownerRaw, "Match raw owner name to a registered staff user")
	}
	if blank(s.clusterID) {
		add("no_cluster", "critical", "cluster_id", nil, "Add school to an active cluster")
	}
	if s.ssaStatus == nil || *s.ssaStatus != "done" {
		add("no_ssa", "info", "current_fy_ssa_status", nil, "Collect and upload School Self-Assessment (SSA)")
	}
	return out
}

// stored is an issue row as the reconciliation compares it.
type stored struct {
	id, severity               string
	key                        *string
	currentValue, suggestedFix *string
}

func sameText(a, b *string) bool {
	if a == nil || b == nil {
		return a == nil && b == nil
	}
	return *a == *b
}

// reconcile is reconcile_issues for the operating schools, a batch of 500
// at a time as the sweep batches them.
func reconcile(ctx context.Context, tx pgx.Tx, schools []school, overrides map[string]bool, now time.Time, out *Result) error {
	const batch = 500
	for start := 0; start < len(schools); start += batch {
		end := min(start+batch, len(schools))
		if err := reconcileBatch(ctx, tx, schools[start:end], overrides, now, out); err != nil {
			return err
		}
	}
	return nil
}

func reconcileBatch(ctx context.Context, tx pgx.Tx, schools []school, overrides map[string]bool, now time.Time, out *Result) error {
	fresh := map[string]issue{}
	var order []string
	ids := make([]string, 0, len(schools))
	for _, s := range schools {
		ids = append(ids, s.id)
		for _, is := range build(s, overrides) {
			if _, seen := fresh[is.conditionKey]; !seen {
				order = append(order, is.conditionKey)
			}
			fresh[is.conditionKey] = is
		}
	}
	open, err := openIssues(ctx, tx, ids)
	if err != nil {
		return err
	}
	for key, row := range open {
		built, ok := freshFor(fresh, key)
		if !ok {
			if _, err := tx.Exec(ctx, `UPDATE data_quality_issue SET status = 'resolved', resolved_at = $2 WHERE id = $1`,
				row.id, now); err != nil {
				return fmt.Errorf("dataqualityscan: resolving a cleared issue: %w", err)
			}
			out.Resolved++
			continue
		}
		if row.severity != built.severity || !sameText(row.currentValue, built.currentValue) ||
			!sameText(row.suggestedFix, built.suggestedFix) {
			if _, err := tx.Exec(ctx, `UPDATE data_quality_issue SET severity = $2, current_value = $3, suggested_fix = $4
WHERE id = $1`, row.id, built.severity, built.currentValue, built.suggestedFix); err != nil {
				return fmt.Errorf("dataqualityscan: refreshing an issue: %w", err)
			}
			out.Updated++
		}
	}
	var missing []string
	for _, key := range order {
		if _, ok := open[key]; !ok {
			missing = append(missing, key)
		}
	}
	reopened, err := reopen(ctx, tx, missing, fresh)
	if err != nil {
		return err
	}
	out.Reopened += len(reopened)
	for _, key := range missing {
		if reopened[key] {
			continue
		}
		is := fresh[key]
		if _, err := tx.Exec(ctx, `INSERT INTO data_quality_issue (id, created_at, updated_at, issue_type, severity, field_name,
  current_value, suggested_fix, status, school_id, condition_key)
VALUES ($1, $2, $2, $3, $4, $5, $6, $7, 'open', $8, $9)`, cuid.New(), now, is.issueType, is.severity, is.fieldName,
			is.currentValue, is.suggestedFix, is.schoolID, is.conditionKey); err != nil {
			return fmt.Errorf("dataqualityscan: opening an issue: %w", err)
		}
		out.Created++
	}
	return nil
}

// freshFor reads the built issue for an open row's key; a row with no key
// is never one the builder wants.
func freshFor(fresh map[string]issue, key string) (issue, bool) {
	if key == nullKey {
		return issue{}, false
	}
	is, ok := fresh[key]
	return is, ok
}

// nullKey stands for an open row with no condition key: the existing
// reconciliation keys its rows by condition_key, so such rows share one
// entry and the last one read stands for them.
const nullKey = "\x00"

// openIssues are the batch's open rows by condition key, newest first as
// the model orders them, the last read standing for a key.
func openIssues(ctx context.Context, tx pgx.Tx, schoolIDs []string) (map[string]stored, error) {
	rows, err := tx.Query(ctx, `SELECT id, condition_key, severity, current_value, suggested_fix FROM data_quality_issue
WHERE school_id = ANY($1) AND status = 'open' AND issue_type <> $2
ORDER BY created_at DESC`, schoolIDs, multiplePartnerIssue)
	if err != nil {
		return nil, fmt.Errorf("dataqualityscan: reading the open issues: %w", err)
	}
	defer rows.Close()
	out := map[string]stored{}
	for rows.Next() {
		var s stored
		if err := rows.Scan(&s.id, &s.key, &s.severity, &s.currentValue, &s.suggestedFix); err != nil {
			return nil, err
		}
		key := nullKey
		if s.key != nil {
			key = *s.key
		}
		out[key] = s
	}
	return out, rows.Err()
}

// reopen brings back the resolved row for each missing condition, the most
// recently resolved standing for its key as the existing dict keeps it.
func reopen(ctx context.Context, tx pgx.Tx, keys []string, fresh map[string]issue) (map[string]bool, error) {
	done := map[string]bool{}
	if len(keys) == 0 {
		return done, nil
	}
	rows, err := tx.Query(ctx, `SELECT id, condition_key FROM data_quality_issue
WHERE condition_key = ANY($1) AND status = 'resolved' ORDER BY resolved_at`, keys)
	if err != nil {
		return nil, fmt.Errorf("dataqualityscan: reading the resolved issues: %w", err)
	}
	chosen := map[string]string{}
	for rows.Next() {
		var id, key string
		if err := rows.Scan(&id, &key); err != nil {
			rows.Close()
			return nil, err
		}
		chosen[key] = id
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	for key, id := range chosen {
		built := fresh[key]
		if _, err := tx.Exec(ctx, `UPDATE data_quality_issue SET status = 'open', resolved_at = NULL, severity = $2,
  current_value = $3, suggested_fix = $4 WHERE id = $1`, id, built.severity, built.currentValue, built.suggestedFix); err != nil {
			return nil, fmt.Errorf("dataqualityscan: reopening an issue: %w", err)
		}
		done[key] = true
	}
	return done, nil
}

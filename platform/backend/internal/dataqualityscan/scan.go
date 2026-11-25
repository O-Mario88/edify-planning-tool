// Package dataqualityscan is the nightly data_quality_scan job
// (apps.schools.data_quality.scan_all): duplicate pairs proposed by name
// similarity within a district, then every operating school's quality
// issues reconciled. Reconcile, never delete and recreate: an issue that
// persists keeps its row and its assignee, one whose condition cleared is
// resolved, a condition back after a person resolved it reopens its row, and
// only new conditions add rows. Detection proposes; people decide. Inside
// the caller's transaction.
package dataqualityscan

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/cuid"
)

const (
	// duplicateThreshold is DUPLICATE_SIMILARITY_THRESHOLD.
	duplicateThreshold = 0.62
	// multiplePartnerIssue is MULTIPLE_PARTNER_ISSUE_TYPE: another module
	// owns and reconciles it.
	multiplePartnerIssue = "multiple_partner_support"
)

// Result is what scan_all reports.
type Result struct {
	Schools, Created, Resolved, Updated, Reopened, CandidatesCreated, SchoolsFlagged int
}

// Scan is scan_all.
func Scan(ctx context.Context, tx pgx.Tx, now time.Time) (Result, error) {
	var out Result
	created, flagged, err := detectDuplicates(ctx, tx, now)
	if err != nil {
		return out, err
	}
	out.CandidatesCreated, out.SchoolsFlagged = created, flagged
	overrides, err := locationOverrides(ctx, tx)
	if err != nil {
		return out, err
	}
	schools, err := operatingSchools(ctx, tx)
	if err != nil {
		return out, err
	}
	if err := reconcile(ctx, tx, schools, overrides, now, &out); err != nil {
		return out, err
	}
	out.Schools = len(schools)
	return out, nil
}

// detectDuplicates is detect_duplicate_candidates: each eligible school's
// three closest names in its district at or above the threshold, proposed
// once a pair, the pair's schools flagged potential only from none.
func detectDuplicates(ctx context.Context, tx pgx.Tx, now time.Time) (int, int, error) {
	existing, err := existingPairs(ctx, tx)
	if err != nil {
		return 0, 0, err
	}
	type eligible struct{ id, name, district string }
	rows, err := tx.Query(ctx, `SELECT id, COALESCE(name, ''), COALESCE(district_id, '') FROM school
WHERE deleted_at IS NULL AND (duplicate_status IS NULL OR duplicate_status NOT IN ('merged', 'confirmed'))
ORDER BY created_at DESC`)
	if err != nil {
		return 0, 0, fmt.Errorf("dataqualityscan: reading the schools to compare: %w", err)
	}
	var schools []eligible
	for rows.Next() {
		var s eligible
		if err := rows.Scan(&s.id, &s.name, &s.district); err != nil {
			rows.Close()
			return 0, 0, err
		}
		schools = append(schools, s)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return 0, 0, err
	}
	created := 0
	flagged := map[string]bool{}
	for _, s := range schools {
		if len([]rune(s.name)) < 4 || s.district == "" {
			continue
		}
		matches, err := similarNames(ctx, tx, s.id, s.name, s.district)
		if err != nil {
			return 0, 0, err
		}
		for _, m := range matches {
			key := pairKey(s.id, m.id)
			if existing[key] {
				continue
			}
			existing[key] = true
			if _, err := tx.Exec(ctx, `INSERT INTO school_duplicate_candidate (id, created_at, updated_at, school_id, candidate_id,
  score, reasons, resolved)
VALUES ($1, $2, $2, $3, $4, $5, ARRAY['name_similarity', 'same_district']::varchar[], false)`,
				cuid.New(), now, s.id, m.id, int(m.similarity*100)); err != nil {
				return 0, 0, fmt.Errorf("dataqualityscan: proposing a duplicate pair: %w", err)
			}
			created++
			flagged[s.id], flagged[m.id] = true, true
		}
	}
	if len(flagged) > 0 {
		ids := make([]string, 0, len(flagged))
		for id := range flagged {
			ids = append(ids, id)
		}
		if _, err := tx.Exec(ctx, `SELECT gateway_dataquality.flag_potential_duplicates($1)`, ids); err != nil {
			return 0, 0, fmt.Errorf("dataqualityscan: flagging the paired schools: %w", err)
		}
	}
	return created, len(flagged), nil
}

func pairKey(a, b string) [2]string {
	if a > b {
		a, b = b, a
	}
	return [2]string{a, b}
}

func existingPairs(ctx context.Context, tx pgx.Tx) (map[[2]string]bool, error) {
	rows, err := tx.Query(ctx, `SELECT school_id, candidate_id FROM school_duplicate_candidate`)
	if err != nil {
		return nil, fmt.Errorf("dataqualityscan: reading the proposed pairs: %w", err)
	}
	defer rows.Close()
	out := map[[2]string]bool{}
	for rows.Next() {
		var a, b string
		if err := rows.Scan(&a, &b); err != nil {
			return nil, err
		}
		out[pairKey(a, b)] = true
	}
	return out, rows.Err()
}

type match struct {
	id         string
	similarity float64
}

// similarNames is the pass's TrigramSimilarity query for one school.
func similarNames(ctx context.Context, tx pgx.Tx, id, name, district string) ([]match, error) {
	rows, err := tx.Query(ctx, `SELECT id, similarity(name, $2) AS similarity FROM school
WHERE deleted_at IS NULL AND (duplicate_status IS NULL OR duplicate_status NOT IN ('merged', 'confirmed'))
  AND district_id = $3 AND id <> $1 AND similarity(name, $2) >= $4
ORDER BY similarity DESC LIMIT 3`, id, name, district, duplicateThreshold)
	if err != nil {
		return nil, fmt.Errorf("dataqualityscan: comparing a school's name: %w", err)
	}
	defer rows.Close()
	var out []match
	for rows.Next() {
		var m match
		var similarity float32
		if err := rows.Scan(&m.id, &similarity); err != nil {
			return nil, err
		}
		// The driver the existing pass reads with parses the real's printed
		// digits ("0.84"), not its binary value (0.8399999…): the score
		// int(similarity * 100) is taken from those digits.
		m.similarity, _ = strconv.ParseFloat(strconv.FormatFloat(float64(similarity), 'g', -1, 32), 64)
		out = append(out, m)
	}
	return out, rows.Err()
}

func locationOverrides(ctx context.Context, tx pgx.Tx) (map[string]bool, error) {
	rows, err := tx.Query(ctx, `SELECT school_id FROM school_geo_point`)
	if err != nil {
		return nil, fmt.Errorf("dataqualityscan: reading the location overrides: %w", err)
	}
	defer rows.Close()
	out := map[string]bool{}
	for rows.Next() {
		var id string
		if err := rows.Scan(&id); err != nil {
			return nil, err
		}
		out[id] = true
	}
	return out, rows.Err()
}

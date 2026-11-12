package schooldirectory

import (
	"context"
	"fmt"
)

// What the Programme Schools page (internal/programmeschools) reads from the
// directory, for a whole list at once: each school's visit status and
// cluster training coverage for the year, and its latest confirmed SSA
// average.

// SchoolRef is what the batch reads need of a school.
type SchoolRef struct {
	ID, SchoolType, ClusterID string
}

// VisitStatusesOf is school_status.visit_statuses for many schools.
func VisitStatusesOf(ctx context.Context, q Querier, schoolIDs []string, fy string) (map[string]VisitStatus, error) {
	statuses, err := visitStatuses(ctx, q, schoolIDs, fy)
	if err != nil {
		return nil, err
	}
	out := make(map[string]VisitStatus, len(statuses))
	for id, status := range statuses {
		out[id] = VisitStatus{Label: rules.VisitLabels[status.key], Tone: rules.VisitTones[status.key], Next: status.next}
	}
	return out, nil
}

// CoveragesOf is school_status.cluster_training_coverage for many schools.
func CoveragesOf(ctx context.Context, q Querier, schools []SchoolRef, fy string) (map[string]Coverage, error) {
	page := make([]school, len(schools))
	for i, s := range schools {
		page[i] = school{ID: s.ID, SchoolType: s.SchoolType, ClusterID: s.ClusterID}
	}
	covered, err := trainingCoverage(ctx, q, page, fy)
	if err != nil {
		return nil, err
	}
	out := make(map[string]Coverage, len(covered))
	for id, c := range covered {
		out[id] = Coverage{Planned: c.planned, Label: c.label, Reason: c.reason, ClusterID: c.clusterID, ClusterName: c.clusterName, Day: c.day}
	}
	return out, nil
}

// LatestSSAAverages is programme_schools._ssa_averages: the average of each
// school's latest confirmed assessment, of any year
// (ssa.services.latest_applicable_records and build_ssa_score_summary). A
// school with no confirmed assessment, or one with no score, is absent.
func LatestSSAAverages(ctx context.Context, q Querier, schoolIDs []string) (map[string]float64, error) {
	out := map[string]float64{}
	if len(schoolIDs) == 0 {
		return out, nil
	}
	rows, err := q.Query(ctx, `
SELECT DISTINCT ON (r.school_id) r.school_id, r.id
FROM ssa_record r
WHERE r.school_id = ANY($1) AND r.deleted_at IS NULL AND r.verification_status = 'confirmed'
ORDER BY r.school_id, r.date_of_ssa DESC, r.created_at DESC`, schoolIDs)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading the latest SSA records: %w", err)
	}
	school := map[string]string{}
	recordIDs := []string{}
	for rows.Next() {
		var schoolID, recordID string
		if err := rows.Scan(&schoolID, &recordID); err != nil {
			rows.Close()
			return nil, err
		}
		school[recordID] = schoolID
		recordIDs = append(recordIDs, recordID)
	}
	rows.Close()
	if err := rows.Err(); err != nil || len(recordIDs) == 0 {
		return out, err
	}
	type score = struct {
		intervention string
		score        *float64
	}
	byRecord := map[string][]score{}
	rows, err = q.Query(ctx, `SELECT ssa_record_id, intervention, score::float8 FROM ssa_score WHERE ssa_record_id = ANY($1)`, recordIDs)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading the latest SSA scores: %w", err)
	}
	for rows.Next() {
		var recordID, intervention string
		var value *float64
		if err := rows.Scan(&recordID, &intervention, &value); err != nil {
			rows.Close()
			return nil, err
		}
		byRecord[recordID] = append(byRecord[recordID], score{intervention, value})
	}
	rows.Close()
	for recordID, scores := range byRecord {
		if average := summarize(scores).average; average != nil {
			out[school[recordID]] = *average
		}
	}
	return out, rows.Err()
}

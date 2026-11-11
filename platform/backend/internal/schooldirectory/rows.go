package schooldirectory

import (
	"context"
	"fmt"
	"math"
	"slices"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"
)

// school is one directory row as read.
type school struct {
	ID, SchoolID, Name, SchoolType  string
	DistrictID, DistrictName        string
	ShippingAddress, Phone, Contact string
	OwnerID, OwnerNameRaw           string
	ClusterID, ClusterStatus        string
	Enrollment                      int
	// HasClusterColumn: cluster_id is not NULL. An empty one still counts as
	// clustered (SchoolDirectoryViewModel.from_school).
	HasClusterColumn bool
}

const schoolColumns = `s.id, COALESCE(s.school_id, ''), s.name, COALESCE(s.school_type, ''),
 COALESCE(s.district_id, ''), COALESCE(d.name, ''), COALESCE(s.shipping_address, ''),
 COALESCE(s.school_phone, ''), COALESCE(s.primary_contact_name, ''),
 COALESCE(s.account_owner_id, ''), COALESCE(s.account_owner_name_raw, ''),
 COALESCE(s.cluster_id, ''), COALESCE(s.cluster_status, ''), COALESCE(s.enrollment, 0), s.cluster_id IS NOT NULL`

func scanSchool(row pgx.CollectableRow) (school, error) {
	var s school
	err := row.Scan(&s.ID, &s.SchoolID, &s.Name, &s.SchoolType, &s.DistrictID, &s.DistrictName, &s.ShippingAddress,
		&s.Phone, &s.Contact, &s.OwnerID, &s.OwnerNameRaw, &s.ClusterID, &s.ClusterStatus, &s.Enrollment, &s.HasClusterColumn)
	return s, err
}

func ids(schools []school) []string {
	out := make([]string, 0, len(schools))
	for _, s := range schools {
		out = append(out, s.ID)
	}
	return out
}

// ── SSA ────────────────────────────────────────────────────────────────────

// ssaBand is core.enums.ssa_score_band: (label, tone).
func ssaBand(score *float64) (string, string) {
	switch {
	case score == nil:
		return "No SSA", "neutral"
	case *score >= 10:
		return "Strong", "perfect"
	case *score >= 8:
		return "Strong", "success"
	case *score >= 6:
		return "Improving", "lime"
	case *score >= 5:
		return "Warning", "warning"
	}
	return "Critical", "danger"
}

// pySum is Python's sum() of floats (3.12 and later): Neumaier's
// compensated summation, as CPython does it, so an average on a rounding
// boundary rounds the same way.
func pySum(values []float64) float64 {
	total, c := 0.0, 0.0
	for _, x := range values {
		t := total + x
		if math.Abs(total) >= math.Abs(x) {
			c += (total - t) + x
		} else {
			c += (x - t) + total
		}
		total = t
	}
	if c != 0 && !math.IsInf(c, 0) && !math.IsNaN(c) {
		total += c
	}
	return total
}

// pyRound1 is Python's round(x, 1): correctly rounded from the exact binary
// value, ties to even.
func pyRound1(x float64) float64 {
	v, _ := strconv.ParseFloat(strconv.FormatFloat(x, 'f', 1, 64), 64)
	return v
}

type ssaItem struct {
	code, label, band, tone, group string
	score                          float64
}

type ssaSummary struct {
	average *float64
	tone    string
	groups  [][]ssaItem // in rules.SSAGroups order
}

// summarize is ssa.presentation.build_ssa_score_summary.
func summarize(scores []struct {
	intervention string
	score        *float64
}) ssaSummary {
	order := map[string]int{}
	labels := map[string]string{}
	for i, iv := range rules.SSAInterventions {
		order[iv[0]] = i
		labels[iv[0]] = iv[1]
	}
	items := []ssaItem{}
	for _, raw := range scores {
		if raw.score == nil {
			continue
		}
		value := *raw.score
		group := "warning"
		if value < 5 {
			group = "urgent"
		} else if value >= 7 {
			group = "performing-well"
		}
		band, tone := ssaBand(&value)
		label, ok := labels[raw.intervention]
		if !ok {
			label = raw.intervention
		}
		items = append(items, ssaItem{code: raw.intervention, label: label, score: value, band: band, tone: tone, group: group})
	}
	rank := func(code string) int {
		if i, ok := order[code]; ok {
			return i
		}
		return 999
	}
	slices.SortStableFunc(items, func(a, b ssaItem) int {
		if ra, rb := rank(a.code), rank(b.code); ra != rb {
			return ra - rb
		}
		switch {
		case a.label < b.label:
			return -1
		case a.label > b.label:
			return 1
		}
		return 0
	})
	out := ssaSummary{groups: make([][]ssaItem, len(rules.SSAGroups))}
	values := []float64{}
	for _, item := range items {
		values = append(values, item.score)
		for i, g := range rules.SSAGroups {
			if g[0] == item.group {
				out.groups[i] = append(out.groups[i], item)
			}
		}
	}
	if len(items) > 0 {
		avg := pyRound1(pySum(values) / float64(len(items)))
		out.average = &avg
	}
	_, out.tone = ssaBand(out.average)
	return out
}

// ssaSummaries are bulk_progress' SSA: each school's latest confirmed
// assessment of the year, its scores grouped. Schools without one are absent.
func ssaSummaries(ctx context.Context, q Querier, schoolIDs []string, fy string) (map[string]ssaSummary, error) {
	rows, err := q.Query(ctx, `
SELECT DISTINCT ON (r.school_id) r.school_id, r.id
FROM ssa_record r
WHERE r.school_id = ANY($1) AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL AND r.fy = $2
ORDER BY r.school_id, r.date_of_ssa DESC, r.created_at DESC`, schoolIDs, fy)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading SSA records: %w", err)
	}
	latest := map[string]string{}
	recordIDs := []string{}
	for rows.Next() {
		var schoolID, recordID string
		if err := rows.Scan(&schoolID, &recordID); err != nil {
			rows.Close()
			return nil, err
		}
		latest[schoolID] = recordID
		recordIDs = append(recordIDs, recordID)
	}
	rows.Close()
	type score = struct {
		intervention string
		score        *float64
	}
	byRecord := map[string][]score{}
	if len(recordIDs) > 0 {
		rows, err := q.Query(ctx, `SELECT ssa_record_id, intervention, score::float8 FROM ssa_score WHERE ssa_record_id = ANY($1)`, recordIDs)
		if err != nil {
			return nil, fmt.Errorf("schooldirectory: reading SSA scores: %w", err)
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
	}
	out := map[string]ssaSummary{}
	for schoolID, recordID := range latest {
		out[schoolID] = summarize(byRecord[recordID])
	}
	return out, nil
}

// ── Counts ─────────────────────────────────────────────────────────────────

func countBy(ctx context.Context, q Querier, sql string, args ...any) (map[string]int, error) {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return nil, err
	}
	out := map[string]int{}
	for rows.Next() {
		var id string
		var n int
		if err := rows.Scan(&id, &n); err != nil {
			rows.Close()
			return nil, err
		}
		out[id] += n
	}
	rows.Close()
	return out, rows.Err()
}

// visitCounts are bulk_progress' completed visits, of any year.
func visitCounts(ctx context.Context, q Querier, schoolIDs []string) (map[string]int, error) {
	return countBy(ctx, q, `
SELECT school_id, count(*) FROM activity
WHERE school_id = ANY($1) AND activity_type = ANY($2) AND status = ANY($3) AND deleted_at IS NULL
GROUP BY school_id`, schoolIDs, rules.VisitCountTypes, rules.CompletedWorkStatuses)
}

// trainingCounts is cluster_attendance.training_counts, of any year: the
// school's own completed trainings, the cluster trainings it attended, and
// the attendance arrays of sessions recorded before attendance rows.
func trainingCounts(ctx context.Context, q Querier, schoolIDs []string) (map[string]int, error) {
	own, err := countBy(ctx, q, `
SELECT school_id, count(*) FROM activity
WHERE school_id = ANY($1) AND activity_type = ANY($2) AND status = ANY($3) AND deleted_at IS NULL
GROUP BY school_id`, schoolIDs, rules.SchoolTrainingTypes, rules.CompletedWorkStatuses)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading trainings: %w", err)
	}
	cluster, err := countBy(ctx, q, `
SELECT c.school_id, count(*) FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
WHERE c.school_id = ANY($1) AND c.attended AND a.activity_type = ANY($2) AND a.status = ANY($3) AND a.deleted_at IS NULL
GROUP BY c.school_id`, schoolIDs, rules.ClusterTrainingTypes, rules.ClusterCreditStatuses)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading cluster attendance: %w", err)
	}
	for id, n := range cluster {
		own[id] += n
	}
	// Legacy attendance arrays, for sessions with no attendance row for
	// these schools.
	rows, err := q.Query(ctx, `
SELECT a.id, a.attended_school_ids FROM activity a
WHERE a.activity_type = ANY($2) AND a.status = ANY($3) AND a.deleted_at IS NULL
  AND a.attended_school_ids <> '{}'
  AND NOT EXISTS (SELECT 1 FROM cluster_activity_attendance c WHERE c.activity_id = a.id AND c.school_id = ANY($1) AND c.attended)
  AND a.attended_school_ids && $1::varchar[]`, schoolIDs, rules.ClusterTrainingTypes, rules.ClusterCreditStatuses)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading legacy attendance: %w", err)
	}
	wanted := map[string]bool{}
	for _, id := range schoolIDs {
		wanted[id] = true
	}
	for rows.Next() {
		var activityID string
		var attended []string
		if err := rows.Scan(&activityID, &attended); err != nil {
			rows.Close()
			return nil, err
		}
		for _, id := range attended {
			if wanted[id] {
				own[id]++
			}
		}
	}
	rows.Close()
	return own, rows.Err()
}

// ── Visit status ───────────────────────────────────────────────────────────

type visitStatus struct {
	key  string
	next *time.Time
}

func dayOf(planned, scheduled *time.Time) *time.Time {
	if planned != nil {
		return planned
	}
	if scheduled != nil {
		d := time.Date(scheduled.UTC().Year(), scheduled.UTC().Month(), scheduled.UTC().Day(), 0, 0, 0, 0, time.UTC)
		return &d
	}
	return nil
}

// visitStatuses is school_status.visit_statuses for the year.
func visitStatuses(ctx context.Context, q Querier, schoolIDs []string, fy string) (map[string]visitStatus, error) {
	out := map[string]visitStatus{}
	for _, id := range schoolIDs {
		out[id] = visitStatus{key: "no_visit_planned"}
	}
	rows, err := q.Query(ctx, `
SELECT school_id, status, planned_date, scheduled_date FROM activity
WHERE school_id = ANY($1) AND activity_type = ANY($2) AND deleted_at IS NULL
  AND NOT (status = ANY($3)) AND fy = $4`, schoolIDs, rules.VisitTypes, rules.PendingApprovalStatuses, fy)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading visits: %w", err)
	}
	type best struct {
		rank int
		day  *time.Time
		key  string
	}
	found := map[string]best{}
	for rows.Next() {
		var schoolID, status string
		var planned, scheduled *time.Time
		if err := rows.Scan(&schoolID, &status, &planned, &scheduled); err != nil {
			rows.Close()
			return nil, err
		}
		state := "visit_canceled"
		if !in(rules.DeadStatuses, status) {
			s, ok := rules.VisitStatusStates[status]
			if !ok {
				continue
			}
			state = s
		}
		day := dayOf(planned, scheduled)
		rank := slices.Index(rules.VisitPrecedence, state)
		current, seen := found[schoolID]
		if !seen || rank < current.rank ||
			(rank == current.rank && day != nil && (current.day == nil || day.Before(*current.day))) {
			found[schoolID] = best{rank: rank, day: day, key: state}
		}
	}
	rows.Close()
	for id, b := range found {
		out[id] = visitStatus{key: b.key, next: b.day}
	}
	return out, rows.Err()
}

// ── Cluster training coverage ──────────────────────────────────────────────

type coverage struct {
	planned, required bool
	label, reason     string
	// The planned session's cluster and day, which the profile names.
	clusterID, clusterName string
	day                    *time.Time
}

// trainingCoverage is school_status.cluster_training_coverage for the year.
func trainingCoverage(ctx context.Context, q Querier, page []school, fy string) (map[string]coverage, error) {
	rows, err := q.Query(ctx, `
SELECT c.school_id, a.status, a.activity_type, a.planned_date, a.scheduled_date,
  COALESCE(a.cluster_id, ''), COALESCE(cl.name, '')
FROM cluster_activity_attendance c JOIN activity a ON a.id = c.activity_id
LEFT JOIN cluster cl ON cl.id = a.cluster_id
WHERE c.school_id = ANY($1) AND (c.invited OR c.attended)
  AND a.activity_type = ANY($2) AND a.deleted_at IS NULL AND a.fy = $3`, ids(page), rules.ClusterSessionTypes, fy)
	if err != nil {
		return nil, fmt.Errorf("schooldirectory: reading cluster sessions: %w", err)
	}
	type session struct {
		status, kind           string
		day                    *time.Time
		clusterID, clusterName string
	}
	linked := map[string][]session{}
	for rows.Next() {
		var schoolID string
		var s session
		var planned, scheduled *time.Time
		if err := rows.Scan(&schoolID, &s.status, &s.kind, &planned, &scheduled, &s.clusterID, &s.clusterName); err != nil {
			rows.Close()
			return nil, err
		}
		s.day = dayOf(planned, scheduled)
		linked[schoolID] = append(linked[schoolID], s)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	far := time.Date(9999, 12, 31, 0, 0, 0, 0, time.UTC)
	out := map[string]coverage{}
	for _, sc := range page {
		live := []session{}
		for _, s := range linked[sc.ID] {
			if !in(rules.DeadStatuses, s.status) {
				live = append(live, s)
			}
		}
		if len(live) > 0 {
			slices.SortStableFunc(live, func(a, b session) int {
				da, db := far, far
				if a.day != nil {
					da = *a.day
				}
				if b.day != nil {
					db = *b.day
				}
				return da.Compare(db)
			})
			label := "Training Planned"
			if in(rules.ClusterMeetingTypes, live[0].kind) {
				label = "Cluster Meeting Planned"
			}
			out[sc.ID] = coverage{planned: true, required: true, label: label,
				clusterID: live[0].clusterID, clusterName: live[0].clusterName, day: live[0].day}
			continue
		}
		if sc.SchoolType != "" && !in(rules.TrainedTypes, sc.SchoolType) {
			out[sc.ID] = coverage{label: "No Training Required", reason: "This school type takes no training"}
			continue
		}
		reason := "No cluster training planned"
		switch {
		case sc.ClusterID == "":
			reason = "School not attached to a cluster"
		case len(linked[sc.ID]) > 0:
			reason = "Existing plan canceled"
			for _, s := range linked[sc.ID] {
				if s.status == "returned" || s.status == "returned_by_ia" || s.status == "returned_by_pl" {
					reason = "Existing plan returned"
				}
			}
		}
		out[sc.ID] = coverage{required: true, label: "No Training Planned", reason: reason}
	}
	return out, nil
}

// thousands is Python's "{:,}".
func thousands(n int) string {
	s := strconv.Itoa(int(math.Abs(float64(n))))
	out := ""
	for i, c := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			out += ","
		}
		out += string(c)
	}
	if n < 0 {
		return "-" + out
	}
	return out
}

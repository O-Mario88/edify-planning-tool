package programmerollout

import (
	"context"
	"fmt"
	"slices"
	"sort"
	"strconv"
	"time"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// cycleFYs is PLAnalyticsService._cycle_fys over the portfolio: the latest
// year at or before fy with a confirmed SSA, and the one before it.
func (s *Service) cycleFYs(ctx context.Context, portfolio []string, fy string) (string, string, error) {
	rows, err := s.db.Query(ctx, `SELECT DISTINCT fy FROM ssa_record WHERE school_id = ANY($1) AND verification_status = $2
  AND fy <= $3 AND deleted_at IS NULL AND fy IS NOT NULL`, portfolio, rules.SSA.ConfirmedStatus, fy)
	if err != nil {
		return "", "", fmt.Errorf("programmerollout: reading the SSA cycles: %w", err)
	}
	defer rows.Close()
	years := []string{}
	for rows.Next() {
		var y string
		if err := rows.Scan(&y); err != nil {
			return "", "", fmt.Errorf("programmerollout: reading an SSA cycle: %w", err)
		}
		years = append(years, y)
	}
	if err := rows.Err(); err != nil {
		return "", "", fmt.Errorf("programmerollout: reading the SSA cycles: %w", err)
	}
	sort.Sort(sort.Reverse(sort.StringSlice(years)))
	latest, prev := "", ""
	if len(years) > 0 {
		latest = years[0]
	}
	if len(years) > 1 {
		prev = years[1]
	}
	return latest, prev, nil
}

// teamScore is one of the pair's team averages (ssa_interventions).
type teamScore struct {
	code         string
	score, delta *float64
	band, tone   string
}

func roundDelta(current, previous *float64) *float64 {
	if current == nil || previous == nil {
		return nil
	}
	v := schooldirectory.PyRound1(*current - *previous)
	return &v
}

// teamScores is the pair's rows of PLAnalyticsService.ssa_interventions:
// the portfolio's average per intervention in the latest cycle, with the
// change from the cycle before.
func (s *Service) teamScores(ctx context.Context, portfolio []string, latest, prev string) ([]teamScore, error) {
	average := func(cycle string) (map[string]*float64, error) {
		out := map[string]*float64{}
		rows, err := s.db.Query(ctx, `SELECT x.intervention, AVG(x.score) FROM ssa_score x JOIN ssa_record r ON r.id = x.ssa_record_id
WHERE r.school_id = ANY($1) AND r.verification_status = $2 AND r.fy = $3 AND r.deleted_at IS NULL GROUP BY 1`,
			portfolio, rules.SSA.ConfirmedStatus, cycle)
		if err != nil {
			return nil, fmt.Errorf("programmerollout: reading the team's averages: %w", err)
		}
		defer rows.Close()
		for rows.Next() {
			var code string
			var avg *float64
			if err := rows.Scan(&code, &avg); err != nil {
				return nil, fmt.Errorf("programmerollout: reading a team average: %w", err)
			}
			out[code] = avg
		}
		return out, rows.Err()
	}
	out := []teamScore{}
	if latest == "" {
		for _, code := range rules.Spiritual.Interventions {
			out = append(out, teamScore{code: code, band: "No SSA", tone: "neutral"})
		}
		return out, nil
	}
	current, err := average(latest)
	if err != nil {
		return nil, err
	}
	previous := map[string]*float64{}
	if prev != "" {
		if previous, err = average(prev); err != nil {
			return nil, err
		}
	}
	for _, code := range rules.Spiritual.Interventions {
		t := teamScore{code: code, score: ssaScore(current[code])}
		if prev != "" {
			t.delta = roundDelta(t.score, ssaScore(previous[code]))
		}
		if t.score != nil {
			t.band, t.tone = schooldirectory.SSABand(*t.score)
		} else {
			t.band, t.tone = "No SSA", "neutral"
		}
		out = append(out, t)
	}
	return out, nil
}

// weakItem is one of the pair among a school's three weakest interventions.
type weakItem struct {
	code  string
	score float64
}

// weakest is recommendation_engine.bulk_weakest(portfolio, n=3) kept to the
// pair: each school's latest confirmed record, its lowest scores first,
// ties on the intervention, and only the schools where one of the pair is
// among them.
func (s *Service) weakest(ctx context.Context, portfolio []string) (map[string][]weakItem, error) {
	out := map[string][]weakItem{}
	rows, err := s.db.Query(ctx, `SELECT DISTINCT ON (r.school_id) r.school_id, r.id FROM ssa_record r
WHERE r.school_id = ANY($1) AND r.deleted_at IS NULL AND r.verification_status = $2
ORDER BY r.school_id, r.date_of_ssa DESC NULLS FIRST, r.created_at DESC NULLS FIRST`, portfolio, rules.SSA.ConfirmedStatus)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the latest SSA records: %w", err)
	}
	schoolOf := map[string]string{}
	ids := []string{}
	for rows.Next() {
		var school, id string
		if err := rows.Scan(&school, &id); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading a latest SSA record: %w", err)
		}
		schoolOf[id] = school
		ids = append(ids, id)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("programmerollout: reading the latest SSA records: %w", err)
	}
	if len(ids) == 0 {
		return out, nil
	}
	scores := map[string][]weakItem{}
	rows, err = s.db.Query(ctx, `SELECT ssa_record_id, intervention, score FROM ssa_score WHERE ssa_record_id = ANY($1) AND score IS NOT NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the latest scores: %w", err)
	}
	for rows.Next() {
		var id string
		var w weakItem
		if err := rows.Scan(&id, &w.code, &w.score); err != nil {
			rows.Close()
			return nil, fmt.Errorf("programmerollout: reading a latest score: %w", err)
		}
		scores[schoolOf[id]] = append(scores[schoolOf[id]], w)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("programmerollout: reading the latest scores: %w", err)
	}
	for school, items := range scores {
		sort.Slice(items, func(i, j int) bool {
			if items[i].score != items[j].score {
				return items[i].score < items[j].score
			}
			return items[i].code < items[j].code
		})
		kept := []weakItem{}
		for _, w := range items[:min(len(items), rules.Spiritual.WeakestCount)] {
			if slices.Contains(rules.Spiritual.Interventions, w.code) {
				kept = append(kept, w)
			}
		}
		if len(kept) > 0 {
			out[school] = kept
		}
	}
	return out, nil
}

// response is one activity of the year answering a weak spiritual area.
type response struct {
	name    string
	planned *time.Time
}

// responses is the year's planned work at the weak schools, or at their
// clusters, whose focus or secondary interventions name one of the pair,
// first planned first, by school and intervention.
func (s *Service) responses(ctx context.Context, sc *scope, fy string, weak map[string][]weakItem) (map[[2]string][]response, error) {
	out := map[[2]string][]response{}
	if len(weak) == 0 {
		return out, nil
	}
	schools := []string{}
	clusterSet := map[string]bool{}
	members := map[string][]string{}
	for id := range weak {
		schools = append(schools, id)
		if c := sc.schools[id].cluster; c != "" {
			clusterSet[c] = true
			members[c] = append(members[c], id)
		}
	}
	clusters := []string{}
	for c := range clusterSet {
		clusters = append(clusters, c)
	}
	rows, err := s.db.Query(ctx, `SELECT COALESCE(a.school_id, ''), COALESCE(a.cluster_id, ''), COALESCE(a.focus_intervention, ''),
  COALESCE(a.secondary_focus_interventions, '{}'), COALESCE(a.activity_type, ''), COALESCE(a.activity_name_snapshot, ''),
  COALESCE(c.display_name, ''), a.planned_date
FROM activity a LEFT JOIN activity_catalogue_item c ON c.id = a.training_course_id
WHERE a.fy = $1 AND a.deleted_at IS NULL AND NOT COALESCE(a.status = ANY($2), FALSE)
  AND (a.school_id = ANY($3) OR (a.school_id IS NULL AND a.cluster_id = ANY($4)))
  AND (a.focus_intervention = ANY($5) OR a.secondary_focus_interventions && $5::varchar[])
ORDER BY a.planned_date ASC NULLS LAST, a.id`, fy, rules.NotPlannedStatuses, schools, clusters, rules.Spiritual.Interventions)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the planned responses: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var school, cluster, focus, kind, snapshot, course string
		var secondary []string
		var planned *time.Time
		if err := rows.Scan(&school, &cluster, &focus, &secondary, &kind, &snapshot, &course, &planned); err != nil {
			return nil, fmt.Errorf("programmerollout: reading a planned response: %w", err)
		}
		name := course
		if name == "" {
			name = snapshot
		}
		if name == "" {
			name = rules.TypeLabels[kind]
			if name == "" {
				name = "Activity"
			}
		}
		targets := append([]string{focus}, secondary...)
		at := []string{school}
		if school == "" {
			at = members[cluster]
		}
		for _, id := range at {
			for _, code := range rules.Spiritual.Interventions {
				if slices.Contains(targets, code) {
					key := [2]string{id, code}
					out[key] = append(out[key], response{name: name, planned: planned})
				}
			}
		}
	}
	return out, rows.Err()
}

// weakRow is one school of "Schools weakest in CB or WOG".
type weakRow struct {
	id, code, name, officer, cluster, weak, responses, state string
	lowest                                                   float64
	hasGap                                                   bool
	// firstMissing is the first weak area with nothing planned, which the
	// lead's own school's Plan control opens on.
	firstMissing string
	// planURL is that control's drawer, on the lead's own schools only.
	planURL string
}

// officerScores is each member's flat average of the pair per cycle.
func (s *Service) officerScores(ctx context.Context, portfolio []string, cycles []string) (map[[3]string][]float64, error) {
	out := map[[3]string][]float64{}
	if len(cycles) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT r.school_id, r.fy, x.intervention, x.score FROM ssa_score x JOIN ssa_record r ON r.id = x.ssa_record_id
WHERE r.school_id = ANY($1) AND r.verification_status = $2 AND r.deleted_at IS NULL AND r.fy = ANY($3) AND x.intervention = ANY($4)`,
		portfolio, rules.SSA.ConfirmedStatus, cycles, rules.Spiritual.Interventions)
	if err != nil {
		return nil, fmt.Errorf("programmerollout: reading the officers' scores: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var school, fy, code string
		var score float64
		if err := rows.Scan(&school, &fy, &code, &score); err != nil {
			return nil, fmt.Errorf("programmerollout: reading an officer's score: %w", err)
		}
		key := [3]string{school, fy, code}
		out[key] = append(out[key], score)
	}
	return out, rows.Err()
}

// mean is _mean: the average to one place, or nil with nothing to average.
func mean(values []float64) *float64 {
	if len(values) == 0 {
		return nil
	}
	v := schooldirectory.PyRound1(schooldirectory.PySum(values) / float64(len(values)))
	return &v
}

func signed(v float64) string {
	text := strconv.FormatFloat(v, 'f', 1, 64)
	if v > 0 {
		return "+" + text
	}
	return text
}

// programme is a catalogue item of a spiritual family.
type programme struct{ id, name, family string }

// programmes is _spiritual_programmes: the Christian Transformation courses,
// CC-SEL and the camps.
func (s *Service) programmes(ctx context.Context) (map[string]programme, []string, error) {
	rows, err := s.db.Query(ctx, `SELECT id, COALESCE(display_name, ''), COALESCE(stable_code, ''), COALESCE(activity_type, '')
FROM activity_catalogue_item WHERE training_category = $1 OR stable_code = $2 OR activity_type = $3`,
		rules.Spiritual.ChristianTransformation, rules.Spiritual.CCSELCode, rules.Spiritual.CampCatalogueType)
	if err != nil {
		return nil, nil, fmt.Errorf("programmerollout: reading the spiritual programmes: %w", err)
	}
	defer rows.Close()
	out := map[string]programme{}
	ids := []string{}
	for rows.Next() {
		var p programme
		var code, kind string
		if err := rows.Scan(&p.id, &p.name, &code, &kind); err != nil {
			return nil, nil, fmt.Errorf("programmerollout: reading a spiritual programme: %w", err)
		}
		switch {
		case code == rules.Spiritual.CCSELCode:
			p.family = rules.Spiritual.Families[1][0]
		case kind == rules.Spiritual.CampCatalogueType:
			p.family = rules.Spiritual.Families[2][0]
		default:
			p.family = rules.Spiritual.Families[0][0]
		}
		out[p.id] = p
		ids = append(ids, p.id)
	}
	return out, ids, rows.Err()
}

func familyLabel(key string) string {
	for _, f := range rules.Spiritual.Families {
		if f[0] == key {
			return f[1]
		}
	}
	return key
}

// programmeOf is _programme_id: the in-school course, else the catalogue
// item, when it is a spiritual programme.
func programmeOf(t training, programmes map[string]programme) string {
	for _, id := range []string{t.course, t.catalogue} {
		if _, ok := programmes[id]; ok && id != "" {
			return id
		}
	}
	return ""
}

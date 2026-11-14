package coreoversight

import (
	"context"
	"fmt"
	"strconv"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

func nonNil(ids []string) []string {
	if ids == nil {
		return []string{}
	}
	return ids
}

func each(ctx context.Context, q schooldirectory.Querier, what, sql string, scan func(pgx.Rows) error, args ...any) error {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return fmt.Errorf("coreoversight: reading %s: %w", what, err)
	}
	defer rows.Close()
	for rows.Next() {
		if err := scan(rows); err != nil {
			return fmt.Errorf("coreoversight: reading %s: %w", what, err)
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("coreoversight: reading %s: %w", what, err)
	}
	return nil
}

func text(s *string) string {
	if s == nil {
		return ""
	}
	return *s
}

func intOf(n *int32) *int {
	if n == nil {
		return nil
	}
	v := int(*n)
	return &v
}

// reach is the condition on the schools aliased s that
// oversight_service.scoped_core_queryset puts on the Core schools: a
// Programme Lead's own and team's schools, held by them or in a cluster
// they hold; for everyone else scoping.scoped_school_queryset.
func reach(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope, args *[]any) (string, error) {
	if s.Role != rules.ProgramLeadRole {
		return schooldirectory.AnalyticsReach(s, args), nil
	}
	people := []string{}
	for _, id := range append([]string{s.UserID, s.StaffID}, s.SupervisedStaffIDs...) {
		if id != "" && !in(people, id) {
			people = append(people, id)
		}
	}
	if len(people) == 0 {
		return "false", nil
	}
	clusters := []string{}
	if err := each(ctx, q, "the team's clusters", `
SELECT c.id FROM cluster c WHERE c.deleted_at IS NULL AND c.responsible_staff_id = ANY($1)`, func(rows pgx.Rows) error {
		var id string
		if err := rows.Scan(&id); err != nil {
			return err
		}
		clusters = append(clusters, id)
		return nil
	}, people); err != nil {
		return "", err
	}
	*args = append(*args, people, clusters)
	return fmt.Sprintf("(s.account_owner_id = ANY($%d) OR s.cluster_id = ANY($%d))", len(*args)-1, len(*args)), nil
}

// fyRange is get_fy_date_range: 1 October before the year's end to the
// next 1 October, in UTC.
func fyRange(fy string) (time.Time, time.Time, bool) {
	year, err := strconv.Atoi(fy)
	if err != nil {
		return time.Time{}, time.Time{}, false
	}
	return time.Date(year-1, time.October, 1, 0, 0, 0, 0, time.UTC), time.Date(year, time.October, 1, 0, 0, 0, 0, time.UTC), true
}

// read issues the page's statements for the reader's Core schools in fiscal
// year fy, each in the shape and order the existing page issues it.
// Recommendations are read only for the tab that shows them.
func read(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope, fy string, withRecommendations bool) (*records, error) {
	out := &records{Owners: map[string]string{}, Clusters: map[string]string{}, SubRegions: map[string]string{}, Countries: map[string]string{}}
	previous := previousFY(fy)

	// intelligence.scoped_core_schools: active, Core in its lifecycle, in
	// the reader's scope, with its district; the model's order.
	args := []any{rules.OperatingStatuses, rules.CoreTypes}
	where, err := reach(ctx, q, s, &args)
	if err != nil {
		return nil, err
	}
	if err := each(ctx, q, "the Core schools", `
SELECT s.id, s.school_id, s.name, s.school_type, d.name, s.cluster_id, s.account_owner_id, s.sub_region_id
FROM school s LEFT OUTER JOIN district d ON s.district_id = d.id
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1) AND s.school_type = ANY($2) AND `+where+`
ORDER BY s.created_at DESC`, func(rows pgx.Rows) error {
		var row schoolRow
		var code, kind, district, cluster, owner, sub *string
		if err := rows.Scan(&row.ID, &code, &row.Name, &kind, &district, &cluster, &owner, &sub); err != nil {
			return err
		}
		row.Code, row.Type, row.District, row.ClusterID, row.OwnerID, row.SubRegionID = text(code), text(kind), text(district), text(cluster), text(owner), text(sub)
		out.Schools = append(out.Schools, row)
		return nil
	}, args...); err != nil {
		return nil, err
	}
	if len(out.Schools) == 0 {
		return out, nil
	}
	ids, keys, codes, owners, clusters, subs := []string{}, []string{}, []string{}, []string{}, []string{}, []string{}
	for _, row := range out.Schools {
		ids = append(ids, row.ID)
		keys = append(keys, row.ID)
		if row.Code != "" {
			keys = append(keys, row.Code)
			codes = append(codes, row.Code)
		}
		if row.OwnerID != "" && !in(owners, row.OwnerID) {
			owners = append(owners, row.OwnerID)
		}
		if row.ClusterID != "" && !in(clusters, row.ClusterID) {
			clusters = append(clusters, row.ClusterID)
		}
		if row.SubRegionID != "" && !in(subs, row.SubRegionID) {
			subs = append(subs, row.SubRegionID)
		}
	}

	// _read_names: the officers (_staff_directory, named as _label names
	// them), the clusters not deleted, and the sub-regions.
	if len(owners) > 0 {
		if err := each(ctx, q, "the officers", `
SELECT sp.id, sp.user_id, COALESCE(u.name, ''), COALESCE(u.email, '')
FROM staff_profile sp INNER JOIN "user" u ON sp.user_id = u.id
WHERE sp.deleted_at IS NULL AND (sp.id = ANY($1) OR sp.user_id = ANY($1))`, func(rows pgx.Rows) error {
			var profileID, userID, name, email string
			if err := rows.Scan(&profileID, &userID, &name, &email); err != nil {
				return err
			}
			label := "Unnamed"
			if name != "" {
				label = name
			} else if email != "" {
				label = email
			}
			out.Owners[profileID], out.Owners[userID] = label, label
			return nil
		}, owners); err != nil {
			return nil, err
		}
	}
	if err := each(ctx, q, "the clusters", `
SELECT c.id, c.name FROM cluster c WHERE c.deleted_at IS NULL AND c.id = ANY($1) ORDER BY 2 ASC`, func(rows pgx.Rows) error {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return err
		}
		out.Clusters[id] = name
		return nil
	}, nonNil(clusters)); err != nil {
		return nil, err
	}
	if err := each(ctx, q, "the sub-regions", `SELECT r.id, r.name FROM sub_region r WHERE r.id = ANY($1)`, func(rows pgx.Rows) error {
		var id, name string
		if err := rows.Scan(&id, &name); err != nil {
			return err
		}
		out.SubRegions[id] = name
		return nil
	}, nonNil(subs)); err != nil {
		return nil, err
	}

	if err := readSSARecords(ctx, q, out, ids, fy, previous); err != nil {
		return nil, err
	}
	if err := readWork(ctx, q, out, ids, keys, fy, previous); err != nil {
		return nil, err
	}
	if err := readChampionInputs(ctx, q, out, codes); err != nil {
		return nil, err
	}
	if !withRecommendations {
		return out, nil
	}
	// intelligence.recommendations: open or planned, by school, rank and
	// intervention.
	return out, each(ctx, q, "the SSA recommendations", `
SELECT r.school_id, r.intervention, r.score::text, r.score_band, r.reason, r.state,
  COALESCE(i.display_name, ''), i.id IS NOT NULL, COALESCE(r.unmapped_reason, '')
FROM ssa_recommendation r LEFT JOIN activity_catalogue_item i ON i.id = r.recommended_item_id
WHERE r.school_id = ANY($1) AND r.state = ANY($2)
ORDER BY r.school_id ASC, r.rank ASC, r.intervention ASC`, func(rows pgx.Rows) error {
		var row recommendationRow
		if err := rows.Scan(&row.SchoolID, &row.Intervention, &row.Score, &row.Band, &row.Reason, &row.State,
			&row.Item, &row.HasItem, &row.Unmapped); err != nil {
			return err
		}
		out.Recommendations = append(out.Recommendations, row)
		return nil
	}, ids, rules.RecommendationShownStates)
}

func scores(ctx context.Context, q schooldirectory.Querier, what, where string, records []string) ([]scoreRow, error) {
	found := []scoreRow{}
	if len(records) == 0 {
		return found, nil
	}
	err := each(ctx, q, what, `
SELECT ssa_record_id, intervention, score FROM ssa_score WHERE ssa_record_id = ANY($1::varchar[])`+where,
		func(rows pgx.Rows) error {
			var row scoreRow
			if err := rows.Scan(&row.RecordID, &row.Intervention, &row.Score); err != nil {
				return err
			}
			found = append(found, row)
			return nil
		}, records)
	return found, err
}

// readSSARecords is _read_ssa's statements.
func readSSARecords(ctx context.Context, q schooldirectory.Querier, out *records, ids []string, fy, previous string) error {
	// year_comparison.school_year_scores.
	seen := map[[2]string]bool{}
	missing := []string{}
	if err := each(ctx, q, "the two years' SSA records", `
SELECT r.id, r.school_id, r.fy, r.average_score FROM ssa_record r
WHERE r.deleted_at IS NULL AND r.fy = ANY($1) AND r.school_id = ANY($2) AND r.verification_status = ANY($3)
ORDER BY r.school_id ASC, r.fy ASC, r.date_of_ssa DESC, r.created_at DESC, r.id DESC`, func(rows pgx.Rows) error {
		var row yearRecordRow
		if err := rows.Scan(&row.ID, &row.SchoolID, &row.FY, &row.Average); err != nil {
			return err
		}
		out.YearRecords = append(out.YearRecords, row)
		key := [2]string{row.SchoolID, row.FY}
		if !seen[key] {
			seen[key] = true
			if row.Average == nil {
				missing = append(missing, row.ID)
			}
		}
		return nil
	}, []string{fy, previous}, ids, rules.CurrentSSAStatuses); err != nil {
		return err
	}
	var err error
	if out.YearCarried, err = scores(ctx, q, "the SSA scores of records with no average", " AND score IS NOT NULL", missing); err != nil {
		return err
	}

	// year_comparison.school_current_scores.
	latest := []string{}
	first := map[string]bool{}
	if err := each(ctx, q, "the year's SSA records", `
SELECT r.id, r.school_id, r.average_score FROM ssa_record r
WHERE r.deleted_at IS NULL AND r.school_id = ANY($1::varchar[]) AND r.fy = $2 AND r.verification_status = ANY($3)
ORDER BY r.school_id ASC, r.date_of_ssa DESC, r.created_at DESC, r.id DESC`, func(rows pgx.Rows) error {
		row := yearRecordRow{FY: fy}
		if err := rows.Scan(&row.ID, &row.SchoolID, &row.Average); err != nil {
			return err
		}
		out.CurrentRecords = append(out.CurrentRecords, row)
		if !first[row.SchoolID] {
			first[row.SchoolID] = true
			latest = append(latest, row.ID)
		}
		return nil
	}, ids, fy, rules.CurrentSSAStatuses); err != nil {
		return err
	}
	if out.CurrentScores, err = scores(ctx, q, "the year's SSA scores", " AND score IS NOT NULL", latest); err != nil {
		return err
	}

	// The schools' countries, for the rule in force.
	if err := each(ctx, q, "the schools' countries", `
SELECT s.id, COALESCE(r.country, '') FROM school s LEFT OUTER JOIN region r ON s.region_id = r.id
WHERE s.deleted_at IS NULL AND s.id = ANY($1)`, func(rows pgx.Rows) error {
		var id, country string
		if err := rows.Scan(&id, &country); err != nil {
			return err
		}
		out.Countries[id] = country
		return nil
	}, ids); err != nil {
		return err
	}

	// change_rules.RuleBook: every published rule, newest first.
	if err := each(ctx, q, "the change rules", `
SELECT m.intervention, COALESCE(m.country, ''), COALESCE(m.expected_direction, ''), m.min_meaningful_change::text
FROM activity_intervention_mapping m
WHERE m.active AND m.intervention IS NOT NULL AND m.status = 'published'
ORDER BY m.effective_from DESC, m.version DESC, m.updated_at DESC`, func(rows pgx.Rows) error {
		var row changeRuleRow
		var threshold *string
		if err := rows.Scan(&row.Intervention, &row.Country, &row.Direction, &threshold); err != nil {
			return err
		}
		if threshold != nil {
			v, err := strconv.ParseFloat(*threshold, 64)
			if err != nil {
				return err
			}
			row.Threshold = &v
		}
		out.ChangeRules = append(out.ChangeRules, row)
		return nil
	}); err != nil {
		return err
	}

	// impact_engine.improvement_rows: each school's latest confirmed record
	// of the year, and of the year before for the schools with one now.
	latestOf := func(year string, schools []string) ([]latestRow, error) {
		found := []latestRow{}
		if len(schools) == 0 {
			return found, nil
		}
		err := each(ctx, q, "the latest confirmed SSA records", `
SELECT DISTINCT ON (r.school_id) r.school_id, r.id, (r.date_of_ssa AT TIME ZONE 'UTC')::date::text
FROM ssa_record r
WHERE r.deleted_at IS NULL AND r.school_id = ANY($1::varchar[]) AND r.fy = $2 AND r.verification_status = $3
ORDER BY r.school_id ASC, r.date_of_ssa DESC, r.created_at DESC`, func(rows pgx.Rows) error {
			var row latestRow
			if err := rows.Scan(&row.SchoolID, &row.RecordID, &row.TakenOn); err != nil {
				return err
			}
			found = append(found, row)
			return nil
		}, schools, year, rules.ConfirmedStatus)
		return found, err
	}
	if out.LatestNow, err = latestOf(fy, ids); err != nil {
		return err
	}
	withNow := []string{}
	for _, row := range out.LatestNow {
		withNow = append(withNow, row.SchoolID)
	}
	if out.LatestBefore, err = latestOf(previous, withNow); err != nil {
		return err
	}
	before := map[string]string{}
	for _, row := range out.LatestBefore {
		before[row.SchoolID] = row.RecordID
	}
	nowIDs, beforeIDs := []string{}, []string{}
	for _, row := range out.LatestNow {
		if then, paired := before[row.SchoolID]; paired {
			nowIDs, beforeIDs = append(nowIDs, row.RecordID), append(beforeIDs, then)
		}
	}
	out.PairScores, err = scores(ctx, q, "the paired SSA scores", "", append(nowIDs, beforeIDs...))
	return err
}

// readWork is _read_package, _read_handovers, _read_participation and
// _read_outcomes' statements.
func readWork(ctx context.Context, q schooldirectory.Querier, out *records, ids, keys []string, fy, previous string) error {
	if err := each(ctx, q, "the year's Core plans", `
SELECT p.school_id, p.visits_completed, p.visits_target, p.trainings_completed, p.trainings_target
FROM core_plan p WHERE p.fy = $1 AND p.school_id = ANY($2)`, func(rows pgx.Rows) error {
		var row planRow
		var vd, vt, td, tt int32
		if err := rows.Scan(&row.SchoolKey, &vd, &vt, &td, &tt); err != nil {
			return err
		}
		row.VisitsDone, row.VisitsTarget, row.TrainingsDone, row.TrainingsTarget = int(vd), int(vt), int(td), int(tt)
		out.Plans = append(out.Plans, row)
		return nil
	}, fy, keys); err != nil {
		return err
	}
	if start, end, ok := fyRange(fy); ok {
		if err := each(ctx, q, "the year's hand-overs", `
SELECT a.school_id,
  COUNT(a.id) FILTER (WHERE a.status = ANY($4)), COUNT(a.id) FILTER (WHERE a.status = ANY($5)),
  COUNT(a.id) FILTER (WHERE a.status = $6)
FROM partner_assignment a
WHERE a.created_at >= $1 AND a.created_at < $2 AND a.school_id = ANY($3)
GROUP BY a.school_id`, func(rows pgx.Rows) error {
			var row handoverRow
			if err := rows.Scan(&row.SchoolID, &row.Assigned, &row.Scheduled, &row.Completed); err != nil {
				return err
			}
			out.Handovers = append(out.Handovers, row)
			return nil
		}, start, end, ids, rules.HandoverUnscheduled, rules.HandoverScheduled, rules.HandoverCompleted); err != nil {
			return err
		}
	}
	if err := each(ctx, q, "the session register", `
SELECT c.invited, c.attended, c.school_id, c.teachers, c.leaders
FROM cluster_activity_attendance c
INNER JOIN activity a ON c.activity_id = a.id INNER JOIN school s ON c.school_id = s.id
WHERE a.activity_type = ANY($1) AND a.deleted_at IS NULL AND a.fy = $2 AND a.status = ANY($3) AND c.school_id = ANY($4)
ORDER BY s.name ASC`, func(rows pgx.Rows) error {
		var row registerRow
		var teachers, leaders *int32
		if err := rows.Scan(&row.Invited, &row.Attended, &row.SchoolID, &teachers, &leaders); err != nil {
			return err
		}
		row.Teachers, row.Leaders = intOf(teachers), intOf(leaders)
		out.Register = append(out.Register, row)
		return nil
	}, rules.ClusterSessionTypes, fy, rules.DeliveredStatuses, ids); err != nil {
		return err
	}
	if err := each(ctx, q, "the schools' trainings", `
SELECT a.school_id, a.teachers_attended, a.leaders_attended FROM activity a
WHERE a.deleted_at IS NULL AND a.activity_type = ANY($1) AND a.fy = $2 AND a.school_id = ANY($3)
  AND a.status = ANY($4) AND NOT (a.activity_type = ANY($5))
ORDER BY a.created_at DESC`, func(rows pgx.Rows) error {
		var row trainingRow
		var teachers, leaders *int32
		if err := rows.Scan(&row.SchoolID, &teachers, &leaders); err != nil {
			return err
		}
		row.Teachers, row.Leaders = intOf(teachers), intOf(leaders)
		out.Trainings = append(out.Trainings, row)
		return nil
	}, rules.TrainingTypes, fy, ids, rules.DeliveredStatuses, rules.ClusterSessionTypes); err != nil {
		return err
	}
	if err := each(ctx, q, "the enrolment history", `
SELECT h.school_id, h.fy, h.enrollment FROM school_enrollment_history h
WHERE h.fy = ANY($1) AND h.school_id = ANY($2)`, func(rows pgx.Rows) error {
		var row enrolmentRow
		if err := rows.Scan(&row.SchoolID, &row.FY, &row.Enrollment); err != nil {
			return err
		}
		out.Enrolment = append(out.Enrolment, row)
		return nil
	}, []string{fy, previous}, ids); err != nil {
		return err
	}
	// outcomes._school_scores, in the model's order (a float sum depends on
	// the order its rows are read).
	return each(ctx, q, "the learning results", `
SELECT l.school_id, l.fy, l.mean_score::text, l.max_score::text, COALESCE(l.learners_tested, 0)
FROM impact_learning_result l
WHERE l.deleted_at IS NULL AND l.school_id = ANY($1::varchar[]) AND l.fy = ANY($2) AND l.deleted_at IS NULL
  AND l.verification_status = $3 AND l.mean_score IS NOT NULL AND l.max_score > 0
ORDER BY l.assessed_on DESC, l.school_id ASC`, func(rows pgx.Rows) error {
		var row learningRow
		var meanText, maxText string
		if err := rows.Scan(&row.SchoolID, &row.FY, &meanText, &maxText, &row.Learners); err != nil {
			return err
		}
		var err error
		if row.Mean, err = strconv.ParseFloat(meanText, 64); err != nil {
			return err
		}
		if row.Max, err = strconv.ParseFloat(maxText, 64); err != nil {
			return err
		}
		out.Learning = append(out.Learning, row)
		return nil
	}, ids, []string{fy, previous}, rules.ConfirmedStatus)
}

// readChampionInputs is _read_champion's statements and
// ChampionEligibilityService.scan's.
func readChampionInputs(ctx context.Context, q schooldirectory.Querier, out *records, codes []string) error {
	ch := rules.Champion
	if len(codes) == 0 {
		return nil
	}
	if err := each(ctx, q, "the Core profiles", `
SELECT p.school_id, p.champion_status FROM core_school_profile p WHERE p.school_id = ANY($1)`, func(rows pgx.Rows) error {
		var row storedRow
		if err := rows.Scan(&row.Code, &row.Status); err != nil {
			return err
		}
		out.Stored = append(out.Stored, row)
		if !in(out.ScanProfiles, row.Code) {
			out.ScanProfiles = append(out.ScanProfiles, row.Code)
		}
		return nil
	}, codes); err != nil {
		return err
	}
	profiles := out.ScanProfiles
	if len(profiles) == 0 {
		return nil
	}
	if err := each(ctx, q, "the live plans' package slots", `
SELECT p.school_id, p.fy,
  COUNT(sl.id) FILTER (WHERE sl.activity_type = ANY($3)),
  COUNT(sl.id) FILTER (WHERE sl.activity_type = ANY($3) AND sl.status = ANY($4))
FROM core_plan p LEFT OUTER JOIN core_activity_slot sl ON p.id = sl.core_plan_id
WHERE p.school_id = ANY($1) AND NOT (p.status = ANY($2))
GROUP BY p.school_id, p.fy ORDER BY p.school_id ASC, p.fy DESC`, func(rows pgx.Rows) error {
		var row scanPlanRow
		if err := rows.Scan(&row.Code, &row.FY, &row.Total, &row.Completed); err != nil {
			return err
		}
		out.ScanPlans = append(out.ScanPlans, row)
		return nil
	}, profiles, ch.PlanClosedStatuses, ch.PackageWorkKinds, ch.SlotDoneStatuses); err != nil {
		return err
	}
	latest := map[string]string{}
	order := []string{}
	if err := each(ctx, q, "the confirmed SSAs", `
SELECT r.id, s.school_id, r.average_score FROM ssa_record r INNER JOIN school s ON r.school_id = s.id
WHERE r.deleted_at IS NULL AND s.school_id = ANY($1) AND r.verification_status = $2
ORDER BY s.school_id ASC, r.date_of_ssa ASC, r.created_at ASC`, func(rows pgx.Rows) error {
		var row scanSSARow
		if err := rows.Scan(&row.ID, &row.Code, &row.Average); err != nil {
			return err
		}
		out.ScanSSAs = append(out.ScanSSAs, row)
		if _, seen := latest[row.Code]; !seen {
			order = append(order, row.Code)
		}
		latest[row.Code] = row.ID
		return nil
	}, profiles, ch.ConfirmedSSA); err != nil {
		return err
	}
	latestIDs := []string{}
	for _, code := range order {
		latestIDs = append(latestIDs, latest[code])
	}
	if len(latestIDs) > 0 {
		if err := each(ctx, q, "the latest SSAs' scores", `
SELECT ssa_record_id, score FROM ssa_score WHERE ssa_record_id = ANY($1)`, func(rows pgx.Rows) error {
			var row scanScoreRow
			if err := rows.Scan(&row.RecordID, &row.Score); err != nil {
				return err
			}
			out.ScanScores = append(out.ScanScores, row)
			return nil
		}, latestIDs); err != nil {
			return err
		}
	}
	return each(ctx, q, "the schools' closed activities", `
SELECT s.school_id,
  COUNT(DISTINCT a.id) FILTER (WHERE a.deleted_at IS NULL AND a.status = $2),
  COUNT(DISTINCT a.id) FILTER (WHERE a.deleted_at IS NULL AND a.status = $2 AND a.evidence_status = $3)
FROM school s LEFT OUTER JOIN activity a ON s.id = a.school_id
WHERE s.deleted_at IS NULL AND s.school_id = ANY($1)
GROUP BY s.id, s.school_id`, func(rows pgx.Rows) error {
		var row scanSchoolRow
		if err := rows.Scan(&row.Code, &row.Closed, &row.Clean); err != nil {
			return err
		}
		out.ScanSchools = append(out.ScanSchools, row)
		return nil
	}, profiles, ch.ClosedStatus, ch.CleanEvidence)
}

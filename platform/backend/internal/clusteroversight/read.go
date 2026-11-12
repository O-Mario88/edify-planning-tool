package clusteroversight

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// sqlb gathers a statement's numbered arguments.
type sqlb struct{ args []any }

func (b *sqlb) arg(v any) string {
	b.args = append(b.args, v)
	return fmt.Sprintf("$%d", len(b.args))
}

func nonNil(ids []string) []string {
	if ids == nil {
		return []string{}
	}
	return ids
}

func each(ctx context.Context, q schooldirectory.Querier, what, sql string, scan func(pgx.Rows) error, args ...any) error {
	rows, err := q.Query(ctx, sql, args...)
	if err != nil {
		return fmt.Errorf("clusteroversight: reading %s: %w", what, err)
	}
	defer rows.Close()
	for rows.Next() {
		if err := scan(rows); err != nil {
			return fmt.Errorf("clusteroversight: reading %s: %w", what, err)
		}
	}
	if err := rows.Err(); err != nil {
		return fmt.Errorf("clusteroversight: reading %s: %w", what, err)
	}
	return nil
}

// reach is what scoping.cluster_queryset(scope) reads through for someone
// who is neither a country nor a summary reader: every id a cluster of
// theirs or of their team could be filed under, and the clusters and
// districts of the whole scope's schools.
type reach struct {
	owners, clusters, districts []string
}

// reachOf is scoping.cluster_owner_ids(scope) (the reader's user and staff
// profile ids and their supervisees', each matched to the other id space
// through the live staff profiles, since a cluster's owner is filed under
// either) and _derive_from_schools' cluster_ids and district_ids.
func reachOf(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope) (reach, error) {
	r := reach{}
	add := func(id string) {
		if id != "" && !in(r.owners, id) {
			r.owners = append(r.owners, id)
		}
	}
	add(s.UserID)
	add(s.StaffID)
	for _, id := range s.SupervisedStaffIDs {
		add(id)
	}
	if len(r.owners) > 0 {
		asked := append([]string{}, r.owners...)
		if err := each(ctx, q, "the owner ids", `
SELECT id, COALESCE(user_id, '') FROM staff_profile
WHERE deleted_at IS NULL AND (id = ANY($1) OR user_id = ANY($1))`, func(rows pgx.Rows) error {
			var profileID, userID string
			if err := rows.Scan(&profileID, &userID); err != nil {
				return err
			}
			add(profileID)
			add(userID)
			return nil
		}, asked); err != nil {
			return r, err
		}
	}
	var err error
	r.clusters, r.districts, err = schooldirectory.ScopeGeography(ctx, q, s)
	return r, err
}

// inScope is scoping.cluster_queryset(scope) over the clusters aliased c: a
// country reader's country (the cluster's region, or its district's), every
// cluster for a summary reader, and otherwise the clusters the reader or
// their team is responsible for, those of the scope's schools, and the
// ownerless ones in those schools' districts.
func (b *sqlb) inScope(s schooldirectory.Scope, r reach) string {
	switch {
	case s.CountryScope:
		if s.Country == "" {
			return "TRUE"
		}
		c := b.arg(s.Country)
		return fmt.Sprintf(`(EXISTS (SELECT 1 FROM region r WHERE r.id = c.region_id AND r.country = %[1]s)
  OR EXISTS (SELECT 1 FROM district d2 JOIN region r2 ON r2.id = d2.region_id WHERE d2.id = c.district_id AND r2.country = %[1]s))`, c)
	case s.SummaryOnly:
		return "TRUE"
	}
	return fmt.Sprintf(`(c.responsible_staff_id = ANY(%s) OR c.id = ANY(%s)
  OR ((c.responsible_staff_id IS NULL OR c.responsible_staff_id = '') AND c.district_id = ANY(%s)))`,
		b.arg(nonNil(r.owners)), b.arg(nonNil(r.clusters)), b.arg(nonNil(r.districts)))
}

// float is a numeric or float column read as text, so it is the number
// Python's float() makes of it.
func float(text *string) (*float64, error) {
	if text == nil {
		return nil, nil
	}
	v, err := strconv.ParseFloat(*text, 64)
	return &v, err
}

// read issues the page's statements for the reader's clusters in fiscal
// year fy. Each is the statement the existing page issues, in its shape and
// its order, since a mean of floats depends on the order its rows are read.
func read(ctx context.Context, q schooldirectory.Querier, s schooldirectory.Scope, r reach, fy string) (*records, error) {
	out := &records{Owners: map[string]string{}, LastDelivered: map[string]string{}}
	previous := previousFY(fy)

	// Cluster.objects (not deleted), the reader's, with their districts, by
	// name.
	b := &sqlb{}
	if err := each(ctx, q, "the clusters", `
SELECT c.id, c.name, d.name, c.responsible_staff_id, c.cluster_leader_name, c.cluster_leader_phone
FROM cluster c INNER JOIN district d ON c.district_id = d.id
WHERE c.deleted_at IS NULL AND `+b.inScope(s, r)+` ORDER BY c.name ASC`, func(rows pgx.Rows) error {
		var c clusterRow
		if err := rows.Scan(&c.ID, &c.Name, &c.District, &c.OwnerID, &c.LeaderName, &c.LeaderPhone); err != nil {
			return err
		}
		out.Clusters = append(out.Clusters, c)
		return nil
	}, b.args...); err != nil {
		return nil, err
	}
	ids, owners := []string{}, []string{}
	for _, c := range out.Clusters {
		ids = append(ids, c.ID)
		if c.OwnerID != nil && *c.OwnerID != "" && !in(owners, *c.OwnerID) {
			owners = append(owners, *c.OwnerID)
		}
	}

	// scores.current_settings: the newest weights row.
	var health, impact, teacher, leader, maturity []byte
	switch err := q.QueryRow(ctx, `
SELECT health_weights, impact_weights, teacher_weights, leader_weights, maturity_rules
FROM cluster_score_setting ORDER BY created_at DESC LIMIT 1`).Scan(&health, &impact, &teacher, &leader, &maturity); {
	case errors.Is(err, pgx.ErrNoRows):
	case err != nil:
		return nil, fmt.Errorf("clusteroversight: reading the score weights: %w", err)
	default:
		// A stored value that is not an object names no part.
		object := func(raw []byte) map[string]json.RawMessage {
			parts := map[string]json.RawMessage{}
			_ = json.Unmarshal(raw, &parts)
			return parts
		}
		out.Setting = &settingRow{
			Health: object(health), Impact: object(impact), Teacher: object(teacher),
			Leader: object(leader), Maturity: object(maturity),
		}
	}
	if len(ids) == 0 {
		return out, nil
	}

	// oversight_service._staff_directory: the live profiles a cluster is
	// filed under, by profile id and by user id, named as _label names them.
	if len(owners) > 0 {
		if err := each(ctx, q, "the cluster owners", `
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

	// profile_insights.member_schools: the operating schools, by name.
	schools := []string{}
	if err := each(ctx, q, "the member schools", `
SELECT s.id, s.cluster_id, COALESCE(rg.country, '')
FROM school s LEFT OUTER JOIN region rg ON s.region_id = rg.id
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1) AND s.cluster_id = ANY($2)
ORDER BY s.name ASC`, func(rows pgx.Rows) error {
		var m memberRow
		if err := rows.Scan(&m.ID, &m.ClusterID, &m.Country); err != nil {
			return err
		}
		out.Members = append(out.Members, m)
		schools = append(schools, m.ID)
		return nil
	}, rules.OperatingStatuses, ids); err != nil {
		return nil, err
	}

	// profile_insights._delivered_sessions, in the model's order.
	sessions := []string{}
	if err := each(ctx, q, "the delivered sessions", `
SELECT a.id, a.cluster_id, a.activity_type, COALESCE(a.fy, ''), COALESCE(a.focus_intervention, ''),
  COALESCE(a.attended_school_ids, '{}'), COALESCE(COALESCE(a.actual_delivery_date, a.planned_date)::text, '')
FROM activity a
WHERE a.deleted_at IS NULL AND a.activity_type = ANY($1) AND a.cluster_id = ANY($2) AND a.school_id IS NULL
  AND a.status = ANY($3)
ORDER BY a.created_at DESC`, func(rows pgx.Rows) error {
		var a sessionRow
		if err := rows.Scan(&a.ID, &a.ClusterID, &a.Type, &a.FY, &a.Focus, &a.Attended, &a.HeldOn); err != nil {
			return err
		}
		out.Sessions = append(out.Sessions, a)
		sessions = append(sessions, a.ID)
		return nil
	}, rules.ClusterSessionTypes, ids, rules.DeliveredStatuses); err != nil {
		return nil, err
	}
	if len(sessions) > 0 {
		if err := each(ctx, q, "the session register", `
SELECT activity_id, school_id, invited, attended FROM cluster_activity_attendance WHERE activity_id = ANY($1)`,
			func(rows pgx.Rows) error {
				var row registerRow
				if err := rows.Scan(&row.ActivityID, &row.SchoolID, &row.Invited, &row.Attended); err != nil {
					return err
				}
				out.Register = append(out.Register, row)
				return nil
			}, sessions); err != nil {
			return nil, err
		}
	}

	// scores._session_plan: the year's sessions still in the plan.
	if err := each(ctx, q, "the session plan", `
SELECT a.cluster_id, a.activity_type, a.status, COALESCE(a.planned_date::text, '')
FROM activity a
WHERE a.deleted_at IS NULL AND a.activity_type = ANY($1) AND a.cluster_id = ANY($2) AND a.fy = $3
  AND a.school_id IS NULL AND NOT (a.status = ANY($4))
ORDER BY a.created_at DESC`, func(rows pgx.Rows) error {
		var row planRow
		if err := rows.Scan(&row.ClusterID, &row.Type, &row.Status, &row.Planned); err != nil {
			return err
		}
		out.Plan = append(out.Plan, row)
		return nil
	}, rules.ClusterSessionTypes, ids, fy, rules.NotInPlanStatuses); err != nil {
		return nil, err
	}

	// oversight_service._last_delivered_dates.
	if err := each(ctx, q, "the last activity", `
SELECT a.cluster_id, MAX(COALESCE(a.actual_delivery_date, a.planned_date))::text
FROM activity a
WHERE a.deleted_at IS NULL AND a.activity_type = ANY($1) AND a.cluster_id = ANY($2) AND a.status = ANY($3)
GROUP BY 1`, func(rows pgx.Rows) error {
		var cluster string
		var last *string
		if err := rows.Scan(&cluster, &last); err != nil {
			return err
		}
		if last != nil {
			out.LastDelivered[cluster] = *last
		}
		return nil
	}, rules.LastActivityTypes, ids, rules.DeliveredStatuses); err != nil {
		return nil, err
	}

	// outcomes.stories_by_cluster: filed against a cluster, or written about
	// one of its schools; a draft is its author's own.
	if err := each(ctx, q, "the change stories", `
SELECT COALESCE(m.cluster_id, ''), COALESCE(m.school_id, ''), m.status
FROM mscs_story m
WHERE (m.cluster_id = ANY($1) OR m.school_id = ANY($2)) AND NOT (m.status = $3)
ORDER BY m.story_date DESC, m.created_at DESC`, func(rows pgx.Rows) error {
		var row storyRow
		if err := rows.Scan(&row.ClusterID, &row.SchoolID, &row.Status); err != nil {
			return err
		}
		out.Stories = append(out.Stories, row)
		return nil
	}, ids, schools, rules.StoryDraftStatus); err != nil {
		return nil, err
	}

	// change_rules.RuleBook: every published rule, newest first.
	if err := each(ctx, q, "the change rules", `
SELECT m.intervention, COALESCE(m.country, ''), COALESCE(m.expected_direction, ''), m.min_meaningful_change::text
FROM activity_intervention_mapping m
WHERE m.active AND m.intervention IS NOT NULL AND m.status = $1
ORDER BY m.effective_from DESC, m.version DESC, m.updated_at DESC`, func(rows pgx.Rows) error {
		var row changeRuleRow
		var threshold *string
		if err := rows.Scan(&row.Intervention, &row.Country, &row.Direction, &threshold); err != nil {
			return err
		}
		var err error
		row.Threshold, err = float(threshold)
		out.ChangeRules = append(out.ChangeRules, row)
		return err
	}, rules.PublishedMappingStatus); err != nil {
		return nil, err
	}
	if len(schools) == 0 {
		return out, nil
	}

	// impact_engine._latest_confirmed_records, for the year and the one
	// before: each school's newest confirmed record, in school order.
	latest := func(year string) ([]latestRow, error) {
		found := []latestRow{}
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
	var err error
	if out.LatestNow, err = latest(fy); err != nil {
		return nil, err
	}
	if out.LatestBefore, err = latest(previous); err != nil {
		return nil, err
	}
	scores := func(what, where string, records []string) ([]scoreRow, error) {
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
	// impact_engine.improvement_rows: the scores of the records of the
	// schools that have one in both years, this year's first.
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
	if out.PairScores, err = scores("the paired SSA scores", "", append(nowIDs, beforeIDs...)); err != nil {
		return nil, err
	}

	// year_comparison.school_current_scores: the year's confirmed records,
	// each school's newest first, and their scores.
	yearRecords := []string{}
	seen := map[string]bool{}
	if err := each(ctx, q, "the year's SSA records", `
SELECT r.id, r.school_id, r.average_score
FROM ssa_record r
WHERE r.deleted_at IS NULL AND r.school_id = ANY($1::varchar[]) AND r.fy = $2 AND r.verification_status = ANY($3)
ORDER BY r.school_id ASC, r.date_of_ssa DESC, r.created_at DESC, r.id DESC`, func(rows pgx.Rows) error {
		var row yearRecordRow
		if err := rows.Scan(&row.ID, &row.SchoolID, &row.Average); err != nil {
			return err
		}
		out.YearRecords = append(out.YearRecords, row)
		if !seen[row.SchoolID] {
			seen[row.SchoolID] = true
			yearRecords = append(yearRecords, row.ID)
		}
		return nil
	}, schools, fy, rules.CurrentSSAStatuses); err != nil {
		return nil, err
	}
	if out.YearScores, err = scores("the year's SSA scores", " AND score IS NOT NULL", yearRecords); err != nil {
		return nil, err
	}

	// outcomes.enrolment_by_cluster: the figure of the year and of the one
	// before, for the schools that still exist.
	if err := each(ctx, q, "the enrolment history", `
SELECT h.school_id, h.fy, h.enrollment FROM school_enrollment_history h
WHERE h.school_id = ANY($1::varchar[]) AND h.fy = ANY($2)`, func(rows pgx.Rows) error {
		var row enrolmentRow
		if err := rows.Scan(&row.SchoolID, &row.FY, &row.Enrollment); err != nil {
			return err
		}
		out.Enrolment = append(out.Enrolment, row)
		return nil
	}, schools, []string{fy, previous}); err != nil {
		return nil, err
	}

	// outcomes._school_scores: the confirmed class results of the two years
	// with a mark out of something, in the model's order.
	if err := each(ctx, q, "the learning results", `
SELECT l.school_id, l.fy, l.mean_score::text, l.max_score::text, COALESCE(l.learners_tested, 0)
FROM impact_learning_result l
WHERE l.deleted_at IS NULL AND l.school_id = ANY($1::varchar[]) AND l.fy = ANY($2) AND l.max_score > 0
  AND l.mean_score IS NOT NULL AND l.verification_status = $3
ORDER BY l.assessed_on DESC, 1 ASC`, func(rows pgx.Rows) error {
		var row learningRow
		var meanText, maxText *string
		if err := rows.Scan(&row.SchoolID, &row.FY, &meanText, &maxText, &row.Learners); err != nil {
			return err
		}
		meanScore, err1 := float(meanText)
		maxScore, err2 := float(maxText)
		if err := errors.Join(err1, err2); err != nil {
			return err
		}
		row.Mean, row.Max = *meanScore, *maxScore
		out.Learning = append(out.Learning, row)
		return nil
	}, schools, []string{fy, previous}, rules.ConfirmedStatus); err != nil {
		return nil, err
	}

	// scores._funded_schools. The existing statement asks for distinct
	// schools but, ordered by the model, tells loans apart by their
	// disbursement date and the moment they were made as well: a school with
	// two funded loans is counted twice. Go counts what the page counts.
	return out, each(ctx, q, "the funded loans", `
SELECT DISTINCT l.school_id, l.disbursement_date, l.created_at FROM bt_mfi_loan l
WHERE l.deleted_at IS NULL AND l.school_id = ANY($1::varchar[]) AND l.status = ANY($2)
ORDER BY l.disbursement_date DESC, l.created_at DESC`, func(rows pgx.Rows) error {
		var school string
		var disbursed, created any
		if err := rows.Scan(&school, &disbursed, &created); err != nil {
			return err
		}
		out.Funded = append(out.Funded, school)
		return nil
	}, schools, rules.FundedLoanStatuses)
}

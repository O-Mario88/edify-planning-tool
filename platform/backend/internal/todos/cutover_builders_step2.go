package todos

import (
	"context"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// Native Go builders closing the remaining passOnIf guards for live Uganda
// roles (Program Lead, Impact Assessment, Country Director, RVP, Business
// Transformation Officer, Admin, and CCEO) so /todos runs with zero fallbacks
// when Django is offline.

// plAnalyticsTodos replaces plAnalyticsGuard (_pl_analytics_todos).
func plAnalyticsTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != leadRole {
		return nil, nil
	}
	var out []todo
	if len(r.scope.SchoolIDs) > 0 {
		var missingSSA int
		if err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FROM school s
WHERE s.deleted_at IS NULL AND s.id = ANY($1)
  AND s.operational_status = ANY($2)
  AND s.current_fy_ssa_status = 'not_done'`, r.scope.SchoolIDs, rules.OperatingStatuses).Scan(&missingSSA); err != nil {
			return nil, err
		}
		if missingSSA > 0 {
			out = append(out, todo{
				ID: "pl-analytics-ssa", Title: "Follow up " + plural(missingSSA, "school") + " missing this year's SSA",
				Category: "Team Oversight", Priority: "medium",
				StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
				DueLabel: "—", DueTone: "neutral",
				Linked: plural(missingSSA, "school"), ActionLabel: "Open Team Performance",
				ActionURL: "/team-performance", Shape: "/team-performance",
				Actionable: true, Due: &r.today,
			})
		}
	}
	if len(r.scope.SupervisedStaffIDs) > 0 {
		var behind int
		if err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FROM (
  SELECT sp.id FROM staff_profile sp
  JOIN activity a ON a.responsible_staff_id = sp.id OR a.responsible_staff_id = sp.user_id
  WHERE sp.id = ANY($1) AND a.deleted_at IS NULL AND a.fy = ANY($2) AND a.status = ANY($3)
  GROUP BY sp.id HAVING COUNT(DISTINCT a.id) >= $4
) q`, r.scope.SupervisedStaffIDs, r.fys(), rules.Lead.CCEOBacklogStatuses, analyticsBacklogHighRisk).Scan(&behind); err != nil {
			return nil, err
		}
		if behind > 0 {
			out = append(out, todo{
				ID: "pl-analytics-backlog", Title: "Review backlog for " + plural(behind, "team officer"),
				Category: "Team Oversight", Priority: "high",
				StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
				DueLabel: "—", DueTone: "neutral",
				Linked: plural(behind, "officer"), ActionLabel: "Open Team Performance",
				ActionURL: "/team-performance", Shape: "/team-performance",
				Actionable: true, Due: &r.today,
			})
		}
	}
	return out, nil
}

// teamTargetTodos replaces teamTargetGuard (_team_target_todos).
func teamTargetTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != leadRole {
		return nil, nil
	}
	var out []todo
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(note, ''), COALESCE(month_of_fy, 0)
FROM target_catchup_plan
WHERE pl_user_id = $1 AND status IN ('submitted', 'pending')
ORDER BY created_at ASC LIMIT 10`, r.p.UserID)
	if err != nil {
		return nil, err
	}
	plans, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, note string
		var month int
		if err := row.Scan(&id, &note, &month); err != nil {
			return todo{}, err
		}
		linked := "Catch-up plan"
		if month > 0 {
			linked = "Month " + strconv.Itoa(month) + " catch-up plan"
		}
		return todo{
			ID: "catchup-" + id, Title: "Review Team Catch-Up Plan",
			Description: truncateRunes(note, 160), Described: note != "",
			Category: "Performance", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: linked, ActionLabel: "Review",
			ActionURL: "/team-performance", Shape: "/team-performance",
			Actionable: true, Due: &r.today,
		}, nil
	})
	if err != nil {
		return nil, err
	}
	out = append(out, plans...)

	team, err := s.supervisees(ctx, r)
	if err != nil || len(team) == 0 {
		return out, err
	}
	var missingSF int
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FROM activity
WHERE responsible_staff_id = ANY($1) AND fy = ANY($2)
  AND status = ANY($3) AND deleted_at IS NULL
  AND delivery_type IS DISTINCT FROM 'partner'
  AND COALESCE(salesforce_activity_id, '') = ''`,
		team, r.fys(), rules.Lead.TeamTargetsCompletedStatuses).Scan(&missingSF); err != nil {
		return nil, err
	}
	if missingSF >= teamTargetsMissingSFIDs {
		out = append(out, todo{
			ID: "team-missing-sfid", Title: "Follow up " + plural(missingSF, "completed activity") + " missing Salesforce IDs",
			Category: "Data Quality", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(missingSF, "activity"), ActionLabel: "Open Team Performance",
			ActionURL: "/team-performance", Shape: "/team-performance",
			Actionable: true, Due: &r.today,
		})
	}
	return out, nil
}

// regionalEngagementTodos replaces regionalEngagementGuard (_cce_leadership_todos).
func regionalEngagementTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role == regionalLeadRole {
		return regionalLeadTodos(ctx, s, r)
	}
	if r.role == rvpRole {
		rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(period, ''), COALESCE(fy, '')
FROM cce_regional_report
WHERE status = 'submitted'
ORDER BY submitted_at ASC NULLS LAST, created_at ASC LIMIT 10`)
		if err != nil {
			return nil, err
		}
		return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
			var id, period, fy string
			if err := row.Scan(&id, &period, &fy); err != nil {
				return todo{}, err
			}
			linked := "Regional report"
			if period != "" {
				linked = period
			} else if fy != "" {
				linked = "FY " + fy
			}
			return todo{
				ID: "cce-report-" + id, Title: "Review Regional Monthly Report",
				Category: "CCE leadership", Priority: "high",
				StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
				DueLabel: "—", DueTone: "neutral",
				Linked: linked, ActionLabel: "Review",
				ActionURL: "/cce-leadership/reports", Shape: "/cce-leadership/reports",
				Actionable: true, Due: &r.today,
			}, nil
		})
	}
	if r.role != leadRole {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(subject, 'Regional Lead feedback'), follow_up_due
FROM cce_regional_engagement
WHERE feedback_shared_at IS NOT NULL AND acknowledged_at IS NULL
  AND (program_lead_ids::text LIKE '%' || $1 || '%' OR ($2 <> '' AND program_lead_ids::text LIKE '%' || $2 || '%'))
ORDER BY feedback_shared_at ASC LIMIT 10`, r.p.UserID, r.p.StaffProfileID)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, subject string
		var dueDate *time.Time
		if err := row.Scan(&id, &subject, &dueDate); err != nil {
			return todo{}, err
		}
		var due *time.Time
		if dueDate != nil {
			due = dateOf(*dueDate)
		}
		t := todo{
			ID: "cce-reg-eng-" + id, Title: "Acknowledge Regional Lead Feedback",
			Description: truncateRunes(subject, 160), Described: true,
			Category: "CCE leadership", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			Linked: truncateRunes(subject, 80), ActionLabel: "Open Coaching",
			ActionURL: "/team/coaching", Shape: "/team/coaching",
			Actionable: true, Due: due,
		}
		return withDue(t, r.today), nil
	})
}

// distributionTodos replaces distributionGuard (apps.hr.distribution_todos:distribution_todos).
func distributionTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != leadRole || r.p.StaffProfileID == "" {
		return nil, nil
	}
	var unspread int
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FROM hr_milestone_allocation parent
WHERE parent.team_id = $1 AND parent.allocated_to_type = 'team'
  AND parent.status IN ('draft', 'approved')
  AND NOT EXISTS (
    SELECT 1 FROM hr_milestone_allocation child
    WHERE child.parent_id = parent.id AND child.status IN ('draft', 'approved')
  )`, r.p.StaffProfileID).Scan(&unspread); err != nil {
		return nil, err
	}
	if unspread == 0 {
		return nil, nil
	}
	return []todo{{
		ID: "dist-team-allocations", Title: "Distribute " + plural(unspread, "team target") + " to officers",
		Category: "Priorities", Priority: "high",
		StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
		DueLabel: "—", DueTone: "neutral",
		Linked: plural(unspread, "allocation"), ActionLabel: "Open My Team Targets",
		ActionURL: "/target-distribution/team", Shape: "/target-distribution/team",
		Actionable: true, Due: &r.today,
	}}, nil
}

// partnerEngagementTodos replaces partnerEngagementGuard (apps.partners.engagement_todos:partner_engagement_todos).
func partnerEngagementTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.UserID == "" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT e.id, COALESCE(e.subject, 'Partner engagement'), e.follow_up_due, COALESCE(p.name, 'Partner')
FROM partner_engagement e
LEFT JOIN partner p ON p.id = e.partner_id
WHERE e.author_id = $1 AND e.follow_up_due <= $2 AND e.follow_up_done_at IS NULL
ORDER BY e.follow_up_due ASC LIMIT 10`, r.p.UserID, r.today)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, subject, partnerName string
		var dueDate time.Time
		if err := row.Scan(&id, &subject, &dueDate, &partnerName); err != nil {
			return todo{}, err
		}
		due := dateOf(dueDate)
		t := todo{
			ID: "partner-eng-" + id, Title: "Follow Up Partner Engagement",
			Description: truncateRunes(subject, 160), Described: true,
			Category: "Partners", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			Linked: partnerName, ActionLabel: "Open Partner Oversight",
			ActionURL: "/partner-oversight/", Shape: "/partner-oversight/",
			Actionable: true, Due: due,
		}
		return withDue(t, r.today), nil
	})
}

// planningFollowUpTodos replaces planningFollowUpGuard (apps.planning.country_oversight.todos:followup_todos).
func planningFollowUpTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.p.UserID == "" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(school_name, 'Planning follow-up'), COALESCE(instruction, ''), COALESCE(priority, 'medium'), due_date
FROM planning_oversight_follow_up
WHERE program_lead_user_id = $1 AND status NOT IN ('resolved', 'closed', 'cancelled')
ORDER BY due_date ASC NULLS LAST, assigned_at ASC LIMIT 15`, r.p.UserID)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, schoolName, instruction, prio string
		var dueDate *time.Time
		if err := row.Scan(&id, &schoolName, &instruction, &prio, &dueDate); err != nil {
			return todo{}, err
		}
		var due *time.Time
		if dueDate != nil {
			due = dateOf(*dueDate)
		}
		t := todo{
			ID: "plan-fu-" + id, Title: "Act on Planning Oversight Follow-Up",
			Description: truncateRunes(instruction, 160), Described: instruction != "",
			Category: "Planning", Priority: prio,
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			Linked: schoolName, ActionLabel: "Open Planning Oversight",
			ActionURL: "/planning/oversight", Shape: "/planning/oversight",
			Actionable: true, Due: due,
		}
		return withDue(t, r.today), nil
	})
}

// leadGuidanceTodos replaces the lead pass-on guard in guidanceTodos.
func leadGuidanceTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(title, 'Team guidance'), issued_at, review_on
FROM cce_team_guidance
WHERE author_id = $1 AND withdrawn_at IS NULL
  AND (issued_at IS NULL OR (review_on IS NOT NULL AND review_on <= $2))
ORDER BY created_at ASC LIMIT 10`, r.p.UserID, r.today)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, title string
		var issuedAt, reviewOn *time.Time
		if err := row.Scan(&id, &title, &issuedAt, &reviewOn); err != nil {
			return todo{}, err
		}
		heading := "Review Team Guidance"
		if issuedAt == nil {
			heading = "Issue Draft Team Guidance"
		}
		var due *time.Time
		if reviewOn != nil {
			due = dateOf(*reviewOn)
		}
		t := todo{
			ID: "guidance-lead-" + id, Title: heading,
			Description: truncateRunes(title, 160), Described: true,
			Category: "Priorities", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			Linked: title, ActionLabel: "Open Guidance",
			ActionURL: "/priorities/guidance", Shape: "/priorities/guidance",
			Actionable: true, Due: due,
		}
		return withDue(t, r.today), nil
	})
}

// leadAuthoredCoachingTodos natively builds the lead's unshared coaching drafts
// and due coaching follow-ups (replacing the author_id pass-on guard).
func leadAuthoredCoachingTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(subject, 'Coaching note'), shared_at, follow_up_due
FROM cce_cceo_coaching
WHERE author_id = $1
  AND (shared_at IS NULL OR (follow_up_due IS NOT NULL AND follow_up_due <= $2 AND follow_up_done_at IS NULL))
ORDER BY created_at ASC LIMIT 10`, r.p.UserID, r.today)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, subject string
		var sharedAt, followUpDue *time.Time
		if err := row.Scan(&id, &subject, &sharedAt, &followUpDue); err != nil {
			return todo{}, err
		}
		title := "Follow Up Coaching Action"
		if sharedAt == nil {
			title = "Share Draft Coaching Note"
		}
		var due *time.Time
		if followUpDue != nil {
			due = dateOf(*followUpDue)
		}
		t := todo{
			ID: "coaching-lead-" + id, Title: title,
			Description: truncateRunes(subject, 160), Described: true,
			Category: rules.Lead.CoachingCategory, Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			Linked: truncateRunes(subject, 80), ActionLabel: "Open Coaching",
			ActionURL: "/team/coaching", Shape: "/team/coaching",
			Actionable: true, Due: due,
		}
		return withDue(t, r.today), nil
	})
}

// leadApprovalsTodos replaces leadApprovalsGuard in fundRequestTodos.
func leadApprovalsTodos(ctx context.Context, s *Service, r *reader, status string) ([]todo, error) {
	var out []todo
	var weeklyCount int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM weekly_fund_request WHERE status = $1`, status).Scan(&weeklyCount); err != nil {
		return nil, err
	}
	if weeklyCount > 0 {
		out = append(out, todo{
			ID: "lead-wfr-approve", Title: "Approve " + plural(weeklyCount, "weekly fund request"),
			Category: "Finance", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(weeklyCount, "request"), ActionLabel: "Review Approvals",
			ActionURL: "/fund-approvals", Shape: "/fund-approvals",
			Actionable: true, Due: &r.today,
		})
	}
	var advCount int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM advance_request WHERE status = ANY($1)`,
		rules.Lead.AdvanceApproverPendingStatuses).Scan(&advCount); err != nil {
		return nil, err
	}
	if advCount > 0 {
		out = append(out, todo{
			ID: "lead-adv-approve", Title: "Review " + plural(advCount, "advance accountability or claim"),
			Category: "Finance", Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(advCount, "advance"), ActionLabel: "Review Approvals",
			ActionURL: "/fund-approvals", Shape: "/fund-approvals",
			Actionable: true, Due: &r.today,
		})
	}
	return out, nil
}

// leadCoreTodos replaces leadCoreGuard in coreSchoolTodos.
func leadCoreTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	schoolIDs := append([]string(nil), r.scope.OwnSchoolIDs...)
	team, err := s.supervisees(ctx, r)
	if err != nil {
		return nil, err
	}
	if len(team) > 0 {
		rows, err := s.db.Query(ctx, `SELECT DISTINCT school_id FROM staff_school_assignment WHERE staff_id = ANY($1)`, team)
		if err != nil {
			return nil, err
		}
		teamSchools, err := pgx.CollectRows(rows, pgx.RowTo[string])
		if err != nil {
			return nil, err
		}
		for _, id := range teamSchools {
			if !contains(schoolIDs, id) {
				schoolIDs = append(schoolIDs, id)
			}
		}
	}
	if len(schoolIDs) == 0 {
		return nil, nil
	}
	var gapCount int
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(DISTINCT cp.id)
FROM core_plan cp
JOIN school s ON s.school_id = cp.school_id
JOIN core_activity_slot sl ON sl.core_plan_id = cp.id
WHERE s.deleted_at IS NULL AND s.operational_status = ANY($1) AND s.id = ANY($2)
  AND s.school_type = 'core' AND cp.fy = $3
  AND NOT (cp.status = ANY($4) AND cp.status IS NOT NULL)
  AND NOT (sl.status = ANY($5)) AND NOT (sl.status = ANY($6))`,
		rules.OperatingStatuses, schoolIDs, r.fy, []string{"Cancelled", "cancelled"},
		rules.CoreDoneStatuses, rules.CoreInFlightStatuses).Scan(&gapCount); err != nil {
		return nil, err
	}
	if gapCount == 0 {
		return nil, nil
	}
	return []todo{{
		ID: "lead-core-gaps", Title: "Follow up core school gaps across " + plural(gapCount, "school"),
		Category: "Core Schools", Priority: "medium",
		StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
		DueLabel: "—", DueTone: "neutral",
		Linked: plural(gapCount, "core school"), ActionLabel: "Open Core Schools",
		ActionURL: "/core-schools", Shape: "/core-schools",
		Actionable: true, Due: &r.today,
	}}, nil
}

// leadSSAConfirmTodos replaces leadSSAConfirmGuard in returnedSSATodos.
func leadSSAConfirmTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var n int
	if r.scope.CountryScope || r.scope.RegionScope {
		if err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FROM ssa_record
WHERE deleted_at IS NULL AND verification_status = $1`, rules.Lead.SSAPendingStatus).Scan(&n); err != nil {
			return nil, err
		}
	} else if len(r.scope.SchoolIDs) > 0 {
		if err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FROM ssa_record
WHERE deleted_at IS NULL AND verification_status = $1 AND school_id = ANY($2)`,
			rules.Lead.SSAPendingStatus, r.scope.SchoolIDs).Scan(&n); err != nil {
			return nil, err
		}
	}
	if n == 0 {
		return nil, nil
	}
	return []todo{{
		ID: "lead-ssa-pending", Title: "Confirm " + plural(n, "pending SSA record"),
		Category: "Baseline & Field Data", Priority: "medium",
		StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
		DueLabel: "—", DueTone: "neutral",
		Linked: plural(n, "record"), ActionLabel: "Open SSA Queue",
		ActionURL: "/ssa/verification/", Shape: "/ssa/verification/",
		Actionable: true, Due: &r.today,
	}}, nil
}

// iaQueueTodos replaces iaQueueGuard (apps.activities.ia_todos:ia_queue_todos).
func iaQueueTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var ssaPending, unmatched, duplicates, samples int
	if err := s.db.QueryRow(ctx, `SELECT
		(SELECT COUNT(*) FROM ssa_record WHERE deleted_at IS NULL AND verification_status = $1),
		(SELECT COUNT(*) FROM unmatched_ssa_record WHERE status = ANY($2)),
		(SELECT COUNT(*) FROM ia_duplicate_activity WHERE status = $3),
		(SELECT COUNT(*) FROM ia_verification_sample WHERE status = $4)`,
		rules.IA.QueueSSAPending, rules.IA.QueueUnmatchedOpen,
		rules.IA.QueueDuplicateOpen, rules.IA.QueueSamplePending).Scan(&ssaPending, &unmatched, &duplicates, &samples); err != nil {
		return nil, err
	}
	var out []todo
	if ssaPending > 0 {
		out = append(out, todo{
			ID: "ia-queue-ssa", Title: "Verify " + plural(ssaPending, "SSA record"),
			Category: rules.IA.Category, Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(ssaPending, "record"), ActionLabel: "Open SSA Verification",
			ActionURL: "/ia/verification/", Shape: "/ia/verification/",
			Actionable: true, Due: &r.today,
		})
	}
	if unmatched > 0 {
		out = append(out, todo{
			ID: "ia-queue-unmatched", Title: "Resolve " + plural(unmatched, "unmatched SSA import row"),
			Category: "Data Quality", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(unmatched, "row"), ActionLabel: "Open Unmatched",
			ActionURL: "/ia/unmatched", Shape: "/ia/unmatched",
			Actionable: true, Due: &r.today,
		})
	}
	if duplicates > 0 {
		out = append(out, todo{
			ID: "ia-queue-duplicates", Title: "Review " + plural(duplicates, "potential duplicate activity"),
			Category: "Data Quality", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(duplicates, "duplicate"), ActionLabel: "Open Duplicates",
			ActionURL: "/ia/duplicates", Shape: "/ia/duplicates",
			Actionable: true, Due: &r.today,
		})
	}
	if samples > 0 {
		out = append(out, todo{
			ID: "ia-queue-samples", Title: "Complete " + plural(samples, "verification sample"),
			Category: rules.IA.Category, Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(samples, "sample"), ActionLabel: "Open Samples",
			ActionURL: "/ia/samples", Shape: "/ia/samples",
			Actionable: true, Due: &r.today,
		})
	}
	return out, nil
}

// frameworkReviewTodos replaces frameworkReviewGuard for CD and IA.
func frameworkReviewTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var mappings, outcomes, indicators int
	if err := s.db.QueryRow(ctx, `SELECT
		(SELECT COUNT(*) FROM activity_intervention_mapping WHERE active = false AND (status = $1 OR (status = $2 AND reviewed_at IS NOT NULL))),
		(SELECT COUNT(*) FROM impact_outcome_area WHERE status = ANY($3)),
		(SELECT COUNT(*) FROM impact_indicator_definition WHERE status = ANY($3))`,
		rules.IA.FrameworkInReview, rules.IA.FrameworkDraft,
		[]string{rules.IA.DefinitionInReview, rules.IA.DefinitionReturned}).Scan(&mappings, &outcomes, &indicators); err != nil {
		return nil, err
	}
	total := mappings + outcomes + indicators
	if total == 0 {
		return nil, nil
	}
	return []todo{{
		ID: "ia-framework-review", Title: "Review " + plural(total, "measurement rule or definition"),
		Category: rules.IA.FrameworkCategory, Priority: "medium",
		StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
		DueLabel: "—", DueTone: "neutral",
		Linked: plural(total, "item"), ActionLabel: "Open Framework",
		ActionURL: "/ia/framework/", Shape: "/ia/framework/",
		Actionable: true, Due: &r.today,
	}}, nil
}

// learningReviewTodos replaces learningGuard for IA and CountryDirector.
func learningReviewTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var conclusions, findings int
	if err := s.db.QueryRow(ctx, `SELECT
		(SELECT COUNT(*) FROM bt_loan_impact_assessment WHERE ia_status <> 'verified' AND (due_date <= $1 OR prepared_at IS NOT NULL)),
		(SELECT COUNT(*) FROM impact_finding WHERE status NOT IN ('published', 'archived', 'closed'))`,
		r.today).Scan(&conclusions, &findings); err != nil {
		return nil, err
	}
	var out []todo
	if conclusions > 0 {
		out = append(out, todo{
			ID: "ia-learning-conclusions", Title: "Verify " + plural(conclusions, "loan impact conclusion"),
			Category: rules.IA.Category, Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(conclusions, "conclusion"), ActionLabel: "Open Lending Impact",
			ActionURL: "/ia/lending", Shape: "/ia/lending",
			Actionable: true, Due: &r.today,
		})
	}
	if findings > 0 {
		out = append(out, todo{
			ID: "ia-learning-findings", Title: "Review " + plural(findings, "impact finding"),
			Category: rules.IA.Category, Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(findings, "finding"), ActionLabel: "Open Impact Reports",
			ActionURL: "/ia/reports", Shape: "/ia/reports",
			Actionable: true, Due: &r.today,
		})
	}
	return out, nil
}

// reportTodos replaces reportGuard for IA and CountryDirector.
func reportTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var n int
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FROM impact_report
WHERE status NOT IN ('published', 'archived', 'released')`).Scan(&n); err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, nil
	}
	return []todo{{
		ID: "ia-impact-reports", Title: "Review " + plural(n, "impact report"),
		Category: rules.IA.Category, Priority: "medium",
		StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
		DueLabel: "—", DueTone: "neutral",
		Linked: plural(n, "report"), ActionLabel: "Open Impact Reports",
		ActionURL: "/ia/reports", Shape: "/ia/reports",
		Actionable: true, Due: &r.today,
	}}, nil
}

// donorReleaseTodos replaces donorReleaseGuard for RVP.
func donorReleaseTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var n int
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(*) FROM impact_report_release
WHERE audience = 'donor' AND status = 'pending_approval'`).Scan(&n); err != nil {
		return nil, err
	}
	if n == 0 {
		return nil, nil
	}
	return []todo{{
		ID: "rvp-donor-releases", Title: "Approve " + plural(n, "donor impact report release"),
		Category: "Approvals", Priority: "high",
		StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
		DueLabel: "—", DueTone: "neutral",
		Linked: plural(n, "release"), ActionLabel: "Open Impact Reports",
		ActionURL: "/ia/reports", Shape: "/ia/reports",
		Actionable: true, Due: &r.today,
	}}, nil
}

// loanTodosIA replaces loanGuardIA (_business_transformation_todos for IA).
func loanTodosIA(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var loans, reqs, snapshots int
	if err := s.db.QueryRow(ctx, `SELECT
		(SELECT COUNT(*) FROM bt_mfi_loan WHERE deleted_at IS NULL AND salesforce_status = 'confirmed' AND ia_validation_status = 'pending'),
		(SELECT COUNT(*) FROM bt_loan_verification_requirement WHERE status = 'awaiting_verification'),
		(SELECT COUNT(*) FROM bt_enrolment_snapshot WHERE status = 'reported')`).Scan(&loans, &reqs, &snapshots); err != nil {
		return nil, err
	}
	var out []todo
	if loans > 0 {
		out = append(out, todo{
			ID: "ia-bt-loans", Title: "Validate " + plural(loans, "confirmed loan"),
			Category: btCategory, Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(loans, "loan"), ActionLabel: "Open Lending",
			ActionURL: "/ia/lending", Shape: "/ia/lending",
			Actionable: true, Due: &r.today,
		})
	}
	if reqs > 0 {
		out = append(out, todo{
			ID: "ia-bt-verifications", Title: "Verify " + plural(reqs, "loan-use verification"),
			Category: btCategory, Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(reqs, "verification"), ActionLabel: "Open Lending",
			ActionURL: "/ia/lending", Shape: "/ia/lending",
			Actionable: true, Due: &r.today,
		})
	}
	if snapshots > 0 {
		out = append(out, todo{
			ID: "ia-bt-enrolments", Title: "Verify " + plural(snapshots, "reported enrolment snapshot"),
			Category: btCategory, Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(snapshots, "snapshot"), ActionLabel: "Open Lending",
			ActionURL: "/ia/lending", Shape: "/ia/lending",
			Actionable: true, Due: &r.today,
		})
	}
	return out, nil
}

// evidenceTodosIA replaces evidenceGuardIA (evidence_todos for IA and CD).
func evidenceTodosIA(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	var stories int
	if err := s.db.QueryRow(ctx, `SELECT COUNT(*) FROM mscs_story WHERE status = $1`, rules.IA.StorySubmitted).Scan(&stories); err != nil {
		return nil, err
	}
	var parts []string
	for _, table := range rules.EvidenceTables {
		parts = append(parts, `SELECT COUNT(*) AS n FROM `+pgx.Identifier{table}.Sanitize()+` WHERE verification_status = $1`)
	}
	var pendingEvidence int
	if len(parts) > 0 {
		if err := s.db.QueryRow(ctx, `SELECT COALESCE(SUM(n), 0) FROM (`+strings.Join(parts, " UNION ALL ")+`) t`,
			rules.IA.EvidencePending).Scan(&pendingEvidence); err != nil {
			return nil, err
		}
	}
	var out []todo
	if pendingEvidence > 0 {
		out = append(out, todo{
			ID: "ia-evidence-pending", Title: "Verify " + plural(pendingEvidence, "school evidence record"),
			Category: "Evidence", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(pendingEvidence, "record"), ActionLabel: "Open Stories & Evidence",
			ActionURL: "/ia/stories", Shape: "/ia/stories",
			Actionable: true, Due: &r.today,
		})
	}
	if stories > 0 {
		out = append(out, todo{
			ID: "ia-stories-submitted", Title: "Review " + plural(stories, "submitted change story"),
			Category: "Evidence", Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "info",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(stories, "story"), ActionLabel: "Open Stories",
			ActionURL: "/ia/stories", Shape: "/ia/stories",
			Actionable: true, Due: &r.today,
		})
	}
	return out, nil
}

// btRiskTodos replaces btRiskGuard for Business Transformation officers and Country Director.
func btRiskTodos(ctx context.Context, s *Service, r *reader, schools []string) ([]todo, error) {
	if len(schools) == 0 {
		return nil, nil
	}
	pc := rules.PCBT
	var riskCount, concernCount int
	if err := s.db.QueryRow(ctx, `SELECT
		(SELECT COUNT(*) FROM bt_repayment_snapshot WHERE loan_id IN (`+btLoanScope+`) AND status = ANY($2)),
		(SELECT COUNT(*) FROM bt_loan_use_result u INNER JOIN bt_loan_verification_requirement q ON q.id = u.requirement_id
		 WHERE q.loan_id IN (`+btLoanScope+`) AND u.finding = ANY($3) AND u.concern_reviewed_at IS NULL)`,
		schools, pc.BTRepaymentRiskStatuses, pc.BTConcernFindings).Scan(&riskCount, &concernCount); err != nil {
		return nil, err
	}
	var out []todo
	if riskCount > 0 {
		out = append(out, todo{
			ID: "bt-repayment-risk", Title: "Review " + plural(riskCount, "repayment risk alert"),
			Category: btCategory, Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "danger",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(riskCount, "loan"), ActionLabel: "Open Loans",
			ActionURL: "/loans", Shape: "/loans",
			Actionable: true, Due: &r.today,
		})
	}
	if concernCount > 0 {
		out = append(out, todo{
			ID: "bt-loan-use-concerns", Title: "Review " + plural(concernCount, "loan-use concern"),
			Category: btCategory, Priority: "high",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: plural(concernCount, "concern"), ActionLabel: "Open Loans",
			ActionURL: "/loans", Shape: "/loans",
			Actionable: true, Due: &r.today,
		})
	}
	return out, nil
}

// btPurposeProposalTodos replaces the loan-purpose proposal pass-on guard in btOfficerGuard.
func btPurposeProposalTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(proposed_label, 'Loan purpose proposal')
FROM bt_loan_purpose_proposal
WHERE status = $1
ORDER BY created_at ASC LIMIT 10`, rules.PCBT.BTPurposeRequested)
	if err != nil {
		return nil, err
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (todo, error) {
		var id, label string
		if err := row.Scan(&id, &label); err != nil {
			return todo{}, err
		}
		return todo{
			ID: "bt-purpose-proposal-" + id, Title: "Review loan purpose proposal",
			Description: label, Described: true,
			Category: btCategory, Priority: "medium",
			StatusKey: "waiting_me", StatusLabel: "Waiting on Me", StatusTone: "warning",
			DueLabel: "—", DueTone: "neutral",
			Linked: label, ActionLabel: "Review",
			ActionURL: "/business-transformation", Shape: "/business-transformation",
			Actionable: true, Due: &r.today,
		}, nil
	})
}

// loanVerificationsForCountry scopes Admin's loan verifications by country when set.
func loanVerificationsForCountry(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	schools, err := schooldirectory.CountrySchoolIDs(ctx, s.db, r.scope.Country)
	if err != nil || len(schools) == 0 {
		return nil, err
	}
	return btVerificationTodos(ctx, s, r, schools)
}

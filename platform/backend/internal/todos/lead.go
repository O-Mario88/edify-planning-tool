package todos

import (
	"context"
	"net/url"
	"time"

	"github.com/jackc/pgx/v5"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/trainingsummary"
)

// leadRole is the Programme Lead (EdifyRole.COUNTRY_PROGRAM_LEAD).
const leadRole = "Program Lead"

// LeadRules are the vocabularies of the Programme Lead's builders
// (export_todos_rules.lead_rules).
type LeadRules struct {
	ReviewerRoles                  map[string][]string `json:"reviewer_roles"`
	ReviewCategory                 string              `json:"review_category"`
	ReviewStageManagerReview       string              `json:"review_stage_manager_review"`
	ReviewStagesBeforeConversation []string            `json:"review_stages_before_conversation"`
	ReviewDoneStages               []string            `json:"review_done_stages"`
	ReviewClosedStatuses           []string            `json:"review_closed_statuses"`
	ConversationWindows            []string            `json:"conversation_windows"`
	CoachingCategory               string              `json:"coaching_category"`
	CoachingRowLimit               int                 `json:"coaching_row_limit"`
	OneToOneKind                   string              `json:"one_to_one_kind"`
	OneToOneDueDay                 int                 `json:"one_to_one_due_day"`
	LeadReviewableStatuses         []string            `json:"lead_reviewable_statuses"`
	AdvanceApproverPendingStatuses []string            `json:"advance_approver_pending_statuses"`
	CCEOBacklogStatuses            []string            `json:"cceo_backlog_statuses"`
	AnalyticsCompletedStatuses     []string            `json:"analytics_completed_statuses"`
	TeamTargetsCompletedStatuses   []string            `json:"team_targets_completed_statuses"`
	SSAPendingStatus               string              `json:"ssa_pending_status"`
}

// analyticsBacklogHighRisk is the backlog at which cceo_performance's
// _cceo_risk adds a point; with no schools an officer reaches "High" only
// with it (target 2 + backlog 1).
const analyticsBacklogHighRisk = 4

// teamTargetsMissingSFIDs is the count of missing Salesforce IDs from which
// _team_target_todos raises its row.
const teamTargetsMissingSFIDs = 5

func init() {
	for name, build := range map[string]func(context.Context, *Service, *reader) ([]todo, error){
		"_pl_review_todos":       plReviewGuard,
		"_partner_invoice_todos": partnerInvoiceGuard,
		"_leave_todos":           leaveGuard,
		"_cd_flag_todos":         cdFlagGuard,
		"_pl_analytics_todos":    plAnalyticsGuard,
		"_team_target_todos":     teamTargetGuard,
		"_cce_leadership_todos":  regionalEngagementGuard,
		"apps.flags.escalation_todos:pl_escalation_todos":         escalationGuard,
		"apps.hr.review_todos:reviewer_todos":                     reviewerTodos,
		"apps.hr.distribution_todos:distribution_todos":           distributionGuard,
		"apps.partners.engagement_todos:partner_engagement_todos": partnerEngagementGuard,
		"apps.planning.coverage_todos:missing_training_todos":     portfolioGuard,
		"apps.planning.country_oversight.todos:followup_todos":    planningFollowUpGuard,
	} {
		Handled[name] = build
	}
}

// fys are the operational year read in UTC (get_operational_fy()) and on
// the local day (get_operational_fy(today)): the builders use one or the
// other, and a guard asks about both.
func (r *reader) fys() []string {
	return []string{r.fy, schooldirectory.OperationalFY(r.today)}
}

func attendanceCategory(role string) string {
	if role == leadRole {
		return "Programme Implementation"
	}
	return "Planning"
}

// supervisees are the reader's direct supervisees' profile and account ids
// (StaffSupervisorAssignment.supervisor = the reader's profile).
func (s *Service) supervisees(ctx context.Context, r *reader) ([]string, error) {
	if r.p.StaffProfileID == "" {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `SELECT sp.id, COALESCE(sp.user_id, '') FROM staff_supervisor_assignment a
JOIN staff_profile sp ON sp.id = a.supervisee_id WHERE a.supervisor_id = $1`, r.p.StaffProfileID)
	if err != nil {
		return nil, err
	}
	pairs, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) ([2]string, error) {
		var p [2]string
		return p, row.Scan(&p[0], &p[1])
	})
	var ids []string
	for _, p := range pairs {
		for _, id := range p {
			if id != "" && !contains(ids, id) {
				ids = append(ids, id)
			}
		}
	}
	return ids, err
}

// portfolioGuard stands for what the lead's portfolio drives
// (missing_training_todos' training_coverage, the analytics signals): a
// reader with any school, or a country or region lens, is passed on.
func portfolioGuard(_ context.Context, _ *Service, r *reader) ([]todo, error) {
	sc := r.scope
	return passOnIf(sc.CountryScope || sc.RegionScope || len(sc.SchoolIDs) > 0, nil)
}

// plReviewGuard stands for _pl_review_todos: any completion waiting on a
// lead (pl_review.LEAD_REVIEWABLE_STATUSES), the reader's or not.
func plReviewGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM activity WHERE deleted_at IS NULL AND status = ANY($1)`,
		rules.Lead.LeadReviewableStatuses))
}

// partnerInvoiceGuard stands for _partner_invoice_todos: any partner invoice.
func partnerInvoiceGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM partner_invoice`))
}

// leaveGuard stands for _leave_todos: any leave request.
func leaveGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM leave`))
}

// cdFlagGuard stands for _cd_flag_todos: a flag assigned to the reader.
func cdFlagGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM cd_flag WHERE assigned_to_user_id = $1`, r.p.UserID))
}

// escalationGuard stands for pl_escalation_todos: any leadership escalation.
func escalationGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM leadership_escalation`))
}

// regionalEngagementGuard stands for the Regional Lead's coaching and
// training feedback (_cce_leadership_todos for a lead, the Regional Lead
// row of coaching_todos, the observations of partner_engagement_todos):
// any Regional Lead engagement.
func regionalEngagementGuard(ctx context.Context, s *Service, _ *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM cce_regional_engagement`))
}

// distributionGuard stands for distribution_todos: a milestone allocated
// to the reader's team (its spread rows hang under such an allocation).
func distributionGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM hr_milestone_allocation WHERE team_id = $1`, r.p.StaffProfileID))
}

// partnerEngagementGuard stands for partner_engagement_todos: a partner
// engagement the reader wrote, a Regional Lead observation, or a flag
// assigned to the reader.
func partnerEngagementGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM partner_engagement WHERE author_id = $1
UNION ALL SELECT 1 FROM cce_regional_engagement
UNION ALL SELECT 1 FROM cd_flag WHERE assigned_to_user_id = $1`, r.p.UserID))
}

// planningFollowUpGuard stands for followup_todos: a Planning Oversight
// follow-up addressed to the reader.
func planningFollowUpGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	return passOnIf(s.exists(ctx, `SELECT 1 FROM planning_oversight_follow_up WHERE program_lead_user_id = $1`, r.p.UserID))
}

// leadApprovalsGuard stands for the approver half of _fund_request_todos:
// any weekly request at the lead's approval step, or any accountability or
// claim waiting on a lead.
func leadApprovalsGuard(ctx context.Context, s *Service, status string) (bool, error) {
	return s.exists(ctx, `SELECT 1 FROM weekly_fund_request WHERE status = $1
UNION ALL SELECT 1 FROM advance_request WHERE status = ANY($2)`, status, rules.Lead.AdvanceApproverPendingStatuses)
}

// leadCoreGuard stands for _core_school_todos for a lead: their own core
// schools' slots, and a follow-up per officer whose core schools have gaps
// (_team_core_school_todos, which needs a school assigned to the team).
func leadCoreGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if len(r.scope.OwnSchoolIDs) > 0 {
		return nil, errPassOn
	}
	team, err := s.supervisees(ctx, r)
	if err != nil {
		return nil, err
	}
	return passOnIf(s.exists(ctx, `SELECT 1 FROM staff_school_assignment WHERE staff_id = ANY($1)`, team))
}

// leadSSAConfirmGuard stands for collection_todos' lead rows: a pending
// SSA record the lead may read (readable_records: the country, or the
// scope's schools).
func leadSSAConfirmGuard(ctx context.Context, s *Service, r *reader) (bool, error) {
	if r.scope.CountryScope || r.scope.RegionScope {
		return true, nil
	}
	if len(r.scope.SchoolIDs) == 0 {
		return false, nil
	}
	return s.exists(ctx, `SELECT 1 FROM ssa_record WHERE deleted_at IS NULL AND verification_status = $1 AND school_id = ANY($2)`,
		rules.Lead.SSAPendingStatus, r.scope.SchoolIDs)
}

// plAnalyticsGuard stands for _pl_analytics_todos (PLAnalyticsService.pl_todos):
// schools without SSA and weak clusters need a portfolio; an officer is
// "behind" with no schools only with a backlog of analyticsBacklogHighRisk.
func plAnalyticsGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if _, err := portfolioGuard(ctx, s, r); err != nil {
		return nil, err
	}
	sup := r.scope.SupervisedStaffIDs
	if len(sup) == 0 {
		return nil, nil
	}
	if found, err := s.exists(ctx, `SELECT 1 FROM staff_school_assignment WHERE staff_id = ANY($1)`, sup); err != nil || found {
		return passOnIf(found, err)
	}
	return passOnIf(s.exists(ctx, `SELECT 1 FROM staff_profile sp JOIN activity a
  ON a.responsible_staff_id = sp.id OR a.responsible_staff_id = sp.user_id
WHERE sp.id = ANY($1) AND a.deleted_at IS NULL AND a.fy = ANY($2) AND a.status = ANY($3)
GROUP BY sp.id HAVING count(DISTINCT a.id) >= $4`, sup, r.fys(), rules.Lead.CCEOBacklogStatuses, analyticsBacklogHighRisk))
}

// teamTargetGuard stands for _team_target_todos: a team member with
// targets (an agreed priorities review or a monthly target), a catch-up
// plan sent to the reader, or teamTargetsMissingSFIDs completed staff
// activities of the team without a Salesforce ID this year.
func teamTargetGuard(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	team, err := s.supervisees(ctx, r)
	if err != nil {
		return nil, err
	}
	if found, err := s.exists(ctx, `SELECT 1 FROM target_catchup_plan WHERE pl_user_id = $1`, r.p.UserID); err != nil || found {
		return passOnIf(found, err)
	}
	if len(team) == 0 {
		return nil, nil
	}
	found, err := s.exists(ctx, `SELECT 1 FROM hr_performance_review WHERE staff_id = ANY($1) AND review_type = $2 AND NOT (stage = ANY($3))
UNION ALL SELECT 1 FROM monthly_personal_target WHERE user_id = ANY($1) AND target > 0`,
		team, rules.TargetReviewType, rules.TargetReviewStagesNotAgreed)
	if err != nil || found {
		return passOnIf(found, err)
	}
	return passOnIf(s.exists(ctx, `SELECT 1 FROM activity WHERE responsible_staff_id = ANY($1) AND fy = ANY($2)
  AND status = ANY($3) AND deleted_at IS NULL AND delivery_type IS DISTINCT FROM 'partner'
  AND COALESCE(salesforce_activity_id, '') = '' HAVING count(*) >= $4`,
		team, r.fys(), rules.Lead.TeamTargetsCompletedStatuses, teamTargetsMissingSFIDs))
}

// guidanceTodos is guidance_todos: for an officer, guidance to acknowledge
// passes them on; for a lead, guidance they issued passes them on.
func guidanceTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role == leadRole {
		return passOnIf(s.exists(ctx, `SELECT 1 FROM cce_team_guidance WHERE author_id = $1`, r.p.UserID))
	}
	return guidanceGuard(ctx, s, r)
}

// coachingTodos is coaching_todos. An officer's coaching to acknowledge
// passes them on. For a lead, the month's one-to-ones still to hold are
// built (cce_leadership.todos._lead_todos, coaching.monthly_one_to_ones);
// coaching the lead wrote (drafts to share, follow-ups due) and Regional
// Lead coaching pass the lead on.
func coachingTodos(ctx context.Context, s *Service, r *reader) ([]todo, error) {
	if r.role != leadRole {
		return coachingGuard(ctx, s, r)
	}
	if found, err := s.exists(ctx, `SELECT 1 FROM cce_cceo_coaching WHERE author_id = $1
UNION ALL SELECT 1 FROM cce_regional_engagement`, r.p.UserID); err != nil || found {
		return passOnIf(found, err)
	}
	members, err := trainingsummary.TeamMembers(ctx, s.db, r.p.StaffProfileID, r.now)
	if err != nil || len(members) == 0 {
		return nil, err
	}
	ids := make([]string, len(members))
	for i, m := range members {
		ids[i] = m.StaffID
	}
	start := time.Date(r.today.Year(), r.today.Month(), 1, 0, 0, 0, 0, time.UTC)
	end := start.AddDate(0, 1, 0)
	monthEnd := end.AddDate(0, 0, -1)
	dueFrom := start.AddDate(0, 0, rules.Lead.OneToOneDueDay-1)
	rows, err := s.db.Query(ctx, `SELECT DISTINCT cceo_staff_id FROM cce_cceo_coaching
WHERE kind = $1 AND cceo_staff_id = ANY($2) AND held_on >= $3 AND held_on < $4`,
		rules.Lead.OneToOneKind, ids, start, end)
	if err != nil {
		return nil, err
	}
	held, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	if r.today.Before(dueFrom) {
		return nil, nil
	}
	priority := "medium"
	if r.today.Day() >= 20 {
		priority = "high"
	}
	status := "waiting_me"
	if monthEnd.Equal(r.today) {
		status = "due_today"
	}
	var out []todo
	for _, m := range members {
		if contains(held, m.StaffID) || len(out) == rules.Lead.CoachingRowLimit {
			continue
		}
		name := m.Name
		if name == "" {
			name = "Officer"
		}
		q := url.Values{"open": {"new"}, "cceo": {m.StaffID}, "kind": {"one_to_one"}}
		due := monthEnd
		out = append(out, todo{Title: "Hold " + start.Format("January") + " one-to-one with " + name,
			Category: rules.Lead.CoachingCategory, Priority: priority, StatusKey: status, Actionable: true, Linked: name,
			ActionLabel: "Log one-to-one", ActionURL: "/team/coaching?" + pyURLEncode(q, "open", "cceo", "kind"),
			Shape: "/team/coaching?open=new&cceo={id}&kind=one_to_one", Due: &due})
	}
	return out, nil
}

// pyURLEncode is urlencode() of the keys in the order the dict gave them.
func pyURLEncode(q url.Values, keys ...string) string {
	out := ""
	for i, k := range keys {
		if i > 0 {
			out += "&"
		}
		out += url.QueryEscape(k) + "=" + url.QueryEscape(q.Get(k))
	}
	return out
}

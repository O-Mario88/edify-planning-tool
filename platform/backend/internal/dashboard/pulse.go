package dashboard

import (
	"context"
	"fmt"
	"math"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/budgetpage"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/escalations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/plreview"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// The lead's team pulse (ProgramLeadDashboardService.kpis over its
// DashboardContext): six figures, one per responsibility, each opening the
// view that explains it.

// leadCtx is what one build knows about the lead's team (DashboardContext).
type leadCtx struct {
	p           auth.Principal
	fy          string
	now, today  time.Time
	team        []officer
	ownIDs      []string
	portfolio   int
	schoolRef   []string
	teamIDs     []string
	teamUserIDs []string
	teamStaff   []string
}

// readLeadCtx is DashboardContext: the line-managed team (supervised, by
// name), the portfolio's operating schools, and the schools assigned to the
// staff the lead's scope spans.
func readLeadCtx(ctx context.Context, db schooldirectory.Querier, p auth.Principal, fy string, now, today time.Time,
	supervised []officer, onTeam map[string]bool) (*leadCtx, error) {
	c := &leadCtx{p: p, fy: fy, now: now, today: today, ownIDs: []string{p.UserID, p.StaffProfileID}}
	for _, o := range supervised {
		if onTeam[o.staffID] {
			c.team = append(c.team, o)
			c.teamStaff = append(c.teamStaff, o.staffID)
			c.teamIDs = append(c.teamIDs, o.ids()...)
			if o.userID != "" {
				c.teamUserIDs = append(c.teamUserIDs, o.userID)
			}
		}
	}
	scope, err := schooldirectory.ResolveScope(ctx, db, p, now)
	if err != nil {
		return nil, err
	}
	ops := rules.Lead.OperatingStatuses
	if err := db.QueryRow(ctx, `SELECT count(*) FROM school WHERE id = ANY($1) AND deleted_at IS NULL
AND operational_status = ANY($2)`, scope.SchoolIDs, ops).Scan(&c.portfolio); err != nil {
		return nil, fmt.Errorf("dashboard: the portfolio: %w", err)
	}
	staff := []string{scope.StaffID}
	covered, err := collectIDs(ctx, db, `SELECT original_staff_id FROM temporary_coverage_assignment
WHERE covering_staff_id = $1 AND start_datetime <= $2 AND end_datetime >= $2 AND status = 'active'`, scope.StaffID, now)
	if err != nil {
		return nil, err
	}
	staff = append(append(staff, covered...), scope.SupervisedStaffIDs...)
	if c.schoolRef, err = collectIDs(ctx, db, `SELECT id FROM school WHERE deleted_at IS NULL AND operational_status = ANY($2)
AND id IN (SELECT school_id FROM staff_school_assignment WHERE staff_id = ANY($1))`, staff, ops); err != nil {
		return nil, err
	}
	return c, nil
}

func collectIDs(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) ([]string, error) {
	rows, err := db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("dashboard: %w", err)
	}
	defer rows.Close()
	var out []string
	for rows.Next() {
		var id *string
		if err := rows.Scan(&id); err != nil {
			return nil, fmt.Errorf("dashboard: %w", err)
		}
		if id != nil {
			out = append(out, *id)
		}
	}
	return out, rows.Err()
}

func count(ctx context.Context, db schooldirectory.Querier, sql string, args ...any) (int, error) {
	var n int
	if err := db.QueryRow(ctx, sql, args...).Scan(&n); err != nil {
		return 0, fmt.Errorf("dashboard: %w", err)
	}
	return n, nil
}

// pulse is every figure the strip shows.
type pulse struct {
	teamPct                       *float64
	onTrack, measurable, contract int
	waiting                       int
	escalations                   escalations.Dashboard
	confirmed, ssaPortfolio       int
	trainingsPlanned, delivered   int
	openHandoffs                  int
}

func (s *Service) readPulse(ctx context.Context, c *leadCtx) (pulse, error) {
	var out pulse
	var err error
	if err = s.targetStatus(ctx, c, &out); err != nil {
		return out, err
	}
	if out.waiting, out.escalations, err = s.waitingOnYou(ctx, c); err != nil {
		return out, err
	}
	if err = s.ssaRollout(ctx, c, &out); err != nil {
		return out, err
	}
	if err = s.trainingCounts(ctx, c, &out); err != nil {
		return out, err
	}
	out.openHandoffs, err = s.openHandoffs(ctx, c, out.escalations)
	return out, err
}

// targetStatus is _team_target_status: the lead's contract's progress and
// rows, and how many officers with a measurable contract keep the year's pace.
func (s *Service) targetStatus(ctx context.Context, c *leadCtx, out *pulse) error {
	contract, err := allocations.Read(ctx, s.db, c.p, c.fy, c.now, c.today)
	if err != nil {
		return err
	}
	out.teamPct, out.contract = contract.Pct, len(contract.Rows)
	if len(c.teamUserIDs) == 0 {
		return nil
	}
	rows, err := s.db.Query(ctx, `SELECT u.id, COALESCE(u.active_role, ''), COALESCE(sp.id, '') FROM "user" u
LEFT JOIN staff_profile sp ON sp.user_id = u.id WHERE u.id = ANY($1) AND u.deleted_at IS NULL`, c.teamUserIDs)
	if err != nil {
		return fmt.Errorf("dashboard: the team's accounts: %w", err)
	}
	var officers []auth.Principal
	for rows.Next() {
		var a auth.Account
		if err := rows.Scan(&a.UserID, &a.ActiveRole, &a.StaffProfileID); err != nil {
			rows.Close()
			return fmt.Errorf("dashboard: the team's accounts: %w", err)
		}
		officers = append(officers, auth.Principal{Account: a})
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return fmt.Errorf("dashboard: the team's accounts: %w", err)
	}
	expected := float64(expectedPace(c.fy, c.today))
	for _, o := range officers {
		score, err := allocations.Read(ctx, s.db, o, c.fy, c.now, c.today)
		if err != nil {
			return err
		}
		if score.Pct == nil {
			continue
		}
		out.measurable++
		if *score.Pct >= expected {
			out.onTrack++
		}
	}
	return nil
}

// expectedPace is _expected_pace: the share of the year gone, 0 to 100.
func expectedPace(fy string, today time.Time) int {
	var year int
	if _, err := fmt.Sscan(fy, &year); err != nil {
		return 0
	}
	start := time.Date(year-1, time.October, 1, 0, 0, 0, 0, time.UTC)
	end := time.Date(year, time.October, 1, 0, 0, 0, 0, time.UTC)
	switch {
	case !today.After(start):
		return 0
	case !today.Before(end):
		return 100
	}
	gone := today.Sub(start).Hours() / 24
	return int(math.RoundToEven(gone / (end.Sub(start).Hours() / 24) * 100))
}

// waitingOnYou is waiting_on_you's total: the team's fund requests, the
// completions to confirm, leave to decide, escalations addressed to the
// lead, and field debriefs to review.
func (s *Service) waitingOnYou(ctx context.Context, c *leadCtx) (int, escalations.Dashboard, error) {
	total := 0
	fund, err := count(ctx, s.db, `SELECT count(*) FROM weekly_fund_request WHERE status = 'submitted_to_pl'
AND responsible_user = ANY($1)`, c.teamUserIDs)
	if err != nil {
		return 0, escalations.Dashboard{}, err
	}
	completions, err := plreview.NewService(s.db, func() time.Time { return c.now }).Waiting(ctx, c.p)
	if err != nil {
		return 0, escalations.Dashboard{}, err
	}
	leave, err := s.pendingLeave(ctx, c)
	if err != nil {
		return 0, escalations.Dashboard{}, err
	}
	esc, err := escalations.ForDashboard(ctx, s.db, c.p, c.now, rules.Lead.ListRows*2, rules.Lead.ListRows, rules.Lead.DelegatedBackDays)
	if err != nil {
		return 0, escalations.Dashboard{}, err
	}
	debriefs, err := count(ctx, s.db, `SELECT count(*) FROM daily_debrief WHERE submitted_by_user_id = ANY($1)
AND status IN ('submitted', 'updated')`, c.teamUserIDs)
	if err != nil {
		return 0, escalations.Dashboard{}, err
	}
	total = fund + completions + leave + esc.ToDecide + debriefs
	return total, esc, nil
}

// pendingLeave is _pending_leave: the team's pending leave whose type's
// approval floor a Programme Lead clears.
func (s *Service) pendingLeave(ctx context.Context, c *leadCtx) (int, error) {
	if len(c.teamStaff) == 0 {
		return 0, nil
	}
	rows, err := s.db.Query(ctx, `SELECT l.type, p.approver_role FROM leave l
LEFT JOIN staff_profile sp ON sp.id = l.staff_id
LEFT JOIN leave_type_policy p ON p.leave_type = l.type
WHERE l.status = 'pending' AND l.staff_id = ANY($1) AND sp.user_id IS DISTINCT FROM $2`, c.teamStaff, c.p.UserID)
	if err != nil {
		return 0, fmt.Errorf("dashboard: pending leave: %w", err)
	}
	defer rows.Close()
	lead := rules.Lead.ApproverSeniority["pl"]
	n := 0
	for rows.Next() {
		var kind string
		var approver *string
		if err := rows.Scan(&kind, &approver); err != nil {
			return 0, fmt.Errorf("dashboard: pending leave: %w", err)
		}
		floor := ""
		if approver != nil {
			floor = seniorityKey(*approver)
		}
		if rules.Lead.ApproverSeniority[floor] <= lead {
			n++
		}
	}
	return n, rows.Err()
}

// seniorityKey is _seniority_key: a policy's approver role in short form.
func seniorityKey(role string) string {
	raw := strings.ToLower(strings.ReplaceAll(strings.Join(strings.Fields(role), ""), "_", ""))
	switch raw {
	case "cceo":
		return "cceo"
	case "programlead", "pl":
		return "pl"
	case "countrydirector", "cd":
		return "cd"
	case "regionalvicepresident", "rvp":
		return "rvp"
	}
	return ""
}

// ssaRollout is ssa_rollout's coverage: schools holding a confirmed SSA this
// year, of the portfolio.
func (s *Service) ssaRollout(ctx context.Context, c *leadCtx, out *pulse) error {
	out.ssaPortfolio = c.portfolio
	if c.portfolio == 0 {
		return nil
	}
	n, err := count(ctx, s.db, `SELECT count(DISTINCT school_id) FROM ssa_record WHERE deleted_at IS NULL
AND school_id = ANY($1) AND fy = $2 AND verification_status = 'confirmed'`, c.schoolRef, c.fy)
	out.confirmed = n
	return err
}

// trainingCounts is training_counts over the team's activities this year
// (_team_acts): trainings not released, and those delivered.
func (s *Service) trainingCounts(ctx context.Context, c *leadCtx, out *pulse) error {
	ids := append(append([]string{}, c.teamIDs...), c.ownIDs...)
	return s.db.QueryRow(ctx, `SELECT count(*), count(*) FILTER (WHERE a.status = ANY($5)) FROM activity a
WHERE a.fy = $1 AND a.deleted_at IS NULL AND (a.responsible_staff_id = ANY($2) OR a.school_id = ANY($3))
AND a.activity_type = ANY($4) AND NOT COALESCE(a.status = ANY($6), false)`,
		c.fy, ids, c.schoolRef, rules.Lead.TrainingTypes, rules.Lead.CompletedStatuses, rules.Lead.ReleasedStatuses).
		Scan(&out.trainingsPlanned, &out.delivered)
}

// openHandoffs is collaboration_items' open_total: the Country Director's
// open flags (the first fifty), the Regional Lead's feedback and coaching to
// acknowledge, the lead's own escalations still open and delegated back,
// visit requests awaiting the lead, and partner invoices to confirm.
func (s *Service) openHandoffs(ctx context.Context, c *leadCtx, esc escalations.Dashboard) (int, error) {
	flags, err := count(ctx, s.db, `SELECT count(*) FROM (SELECT 1 FROM cd_flag WHERE assigned_to_user_id = $1
AND status IN ('open', 'acknowledged') LIMIT 50) f`, c.p.UserID)
	if err != nil {
		return 0, err
	}
	regional := 0
	if c.p.StaffProfileID != "" {
		if regional, err = count(ctx, s.db, `SELECT count(*) FROM cce_regional_engagement WHERE kind IN ('training_observation', 'pl_coaching')
AND feedback_shared_at IS NOT NULL AND acknowledged_at IS NULL AND program_lead_ids @> ARRAY[$1]::varchar[]`, c.p.StaffProfileID); err != nil {
			return 0, err
		}
	}
	visits, err := count(ctx, s.db, `SELECT count(*) FROM activity WHERE deleted_at IS NULL AND status = 'awaiting_owner_approval'
AND approval_owner_id = ANY($1)`, c.ownIDs)
	if err != nil {
		return 0, err
	}
	invoices := 0
	if len(c.teamIDs) > 0 {
		if invoices, err = count(ctx, s.db, `SELECT count(DISTINCT i.id) FROM partner_invoice i
JOIN partner_invoice_item it ON it.invoice_id = i.id JOIN activity a ON a.id = it.activity_id
WHERE i.status = 'submitted_to_pl' AND (a.responsible_staff_id = ANY($1)
  OR (a.responsible_staff_id IS NULL AND a.monitored_by_staff_id = ANY($1)))`, c.teamIDs); err != nil {
			return 0, err
		}
	}
	return flags + regional + esc.RaisedOpen + esc.DelegatedBack + visits + invoices, nil
}

// pulseStrip is the strip as the feed reads it: each figure's line cut to a
// second figure (the sentence kept as its note), its tone on the line.
func (p pulse) strip(fy string) *screensv1.PageBlock {
	type tile struct{ label, value, helper, tone, view string }
	ofNoun := func(n int, one, many string) string {
		if n == 1 {
			return one
		}
		return many
	}
	tiles := []tile{}
	if p.teamPct != nil {
		tiles = append(tiles, tile{"Team Priority Progress", fmt.Sprintf("%d%%", int(math.RoundToEven(*p.teamPct))),
			fmt.Sprintf("verified against %d team %s", p.contract, ofNoun(p.contract, "priority", "priorities")), "info", "priorities"})
	} else {
		tiles = append(tiles, tile{"Team Priority Progress", "Not measured", "No approved allocation yet", "info", "priorities"})
	}
	if p.measurable > 0 {
		tone := "warning"
		if p.onTrack == p.measurable {
			tone = "success"
		}
		tiles = append(tiles, tile{"CCEOs On Track", fmt.Sprintf("%d / %d", p.onTrack, p.measurable), "at the year's expected pace", tone, "coaching"})
	} else {
		tiles = append(tiles, tile{"CCEOs On Track", "Not measured", "No approved priorities yet", "warning", "coaching"})
	}
	waitingTone := "success"
	if p.waiting > 0 {
		waitingTone = "warning"
	}
	tiles = append(tiles, tile{"Waiting on You", fmt.Sprint(p.waiting), "team handoffs to decide", waitingTone, "team"})
	if p.ssaPortfolio > 0 {
		tiles = append(tiles, tile{"SSA Coverage", fmt.Sprintf("%d%%", budgetpage.Percentage(int64(p.confirmed), int64(p.ssaPortfolio))),
			fmt.Sprintf("%s of %s schools", comma(p.confirmed), comma(p.ssaPortfolio)), "info", "programmes"})
	} else {
		tiles = append(tiles, tile{"SSA Coverage", "Not measured", "No schools in your portfolio", "info", "programmes"})
	}
	tiles = append(tiles, tile{"Trainings Delivered", fmt.Sprint(p.delivered), "of " + comma(p.trainingsPlanned) + " planned", "info", "programmes"})
	handoffTone := "success"
	if p.openHandoffs > 0 {
		handoffTone = "warning"
	}
	tiles = append(tiles, tile{"Open Handoffs", fmt.Sprint(p.openHandoffs), "with the CD, RL and partners", handoffTone, "collaboration"})
	strip := &screensv1.PageStrip{Title: "Team pulse"}
	for _, t := range tiles {
		m := &screensv1.PageMetric{Label: t.label, Value: t.value, Href: fmt.Sprintf("/dashboard?fy=%s&view=%s", fy, t.view)}
		if brief := schoolprofile.BriefHelper(t.helper); brief != t.helper {
			m.Note = t.helper
			m.Helper = brief
		} else {
			m.Helper = t.helper
		}
		if m.Helper != "" {
			m.Tone = t.tone
		}
		strip.Metrics = append(strip.Metrics, m)
	}
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: strip}}
}

// comma is f"{n:,}".
func comma(n int) string {
	s := fmt.Sprint(n)
	var b strings.Builder
	for i, r := range s {
		if i > 0 && (len(s)-i)%3 == 0 {
			b.WriteByte(',')
		}
		b.WriteRune(r)
	}
	return b.String()
}

package dashboard

import (
	"context"
	"fmt"
	"math"
	"slices"
	"sort"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
)

// The lead's leadership attention (ProgramLeadDashboardService
// .leadership_attention): at most four things that need the lead now. Only
// the number of them and the first one's action reach the page on This
// Week: the phone's header names them ("Needs attention: 2") and opens the
// most pressing.

// card is one attention card: how pressing it is and where it opens.
type card struct{ tone, action, url string }

func (s *Service) attention(ctx context.Context, c *leadCtx, esc pulseEscalations) ([]card, error) {
	u := rules.Lead.CardURLs
	var cards []card
	if esc.toDecide > 0 {
		cards = append(cards, card{pressing(esc.overdue > 0), "Open escalations", u["escalations"]})
	}
	flags, overdue, err := s.cdFlags(ctx, c)
	if err != nil {
		return nil, err
	}
	if flags > 0 {
		cards = append(cards, card{pressing(overdue > 0), "Respond to flags", u["quality_flags"]})
	}
	feedback, coaching, err := s.regionalNotes(ctx, c)
	if err != nil {
		return nil, err
	}
	if feedback+coaching > 0 {
		url := u["regional_coaching"]
		if feedback > 0 {
			url = u["training_feedback"]
		}
		cards = append(cards, card{"warning", "Acknowledge", url})
	}
	highRisk, critical, err := s.officerRisk(ctx, c)
	if err != nil {
		return nil, err
	}
	catchUp, err := count(ctx, s.db, `SELECT count(*) FROM target_catchup_plan WHERE pl_user_id = $1 AND status = 'submitted'
AND staff_user_id = ANY($2)`, c.p.UserID, c.teamUserIDs)
	if err != nil {
		return nil, err
	}
	if highRisk > 0 || catchUp > 0 {
		cards = append(cards, card{pressing(critical), "Open Team Targets", u["team_targets"]})
	}
	overloaded, err := s.overloaded(ctx, c)
	if err != nil {
		return nil, err
	}
	conflicts, err := s.leaveConflicts(ctx, c)
	if err != nil {
		return nil, err
	}
	if overloaded > 0 || conflicts > 0 {
		cards = append(cards, card{"warning", "Open team availability", u["team_availability"]})
	}
	late, err := s.partnerLate(ctx, c)
	if err != nil {
		return nil, err
	}
	if late > 0 {
		cards = append(cards, card{"warning", "Open Partner Oversight", u["partner_oversight"]})
	}
	order := map[string]int{"danger": 0, "warning": 1}
	sort.SliceStable(cards, func(i, j int) bool { return order[cards[i].tone] < order[cards[j].tone] })
	if len(cards) > rules.Lead.AttentionLimit {
		cards = cards[:rules.Lead.AttentionLimit]
	}
	return cards, nil
}

func pressing(danger bool) string {
	if danger {
		return "danger"
	}
	return "warning"
}

// pulseEscalations is what the cards read of the escalations the strip
// counted.
type pulseEscalations struct{ toDecide, overdue int }

// cdFlags is the Country Director's flags open for the lead (the first
// fifty, by due date), and how many of those are past their due date.
func (s *Service) cdFlags(ctx context.Context, c *leadCtx) (int, int, error) {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(due_date, '') FROM cd_flag WHERE assigned_to_user_id = $1
AND status IN ('open', 'acknowledged') ORDER BY due_date ASC, created_at ASC LIMIT 50`, c.p.UserID)
	if err != nil {
		return 0, 0, fmt.Errorf("dashboard: flags: %w", err)
	}
	defer rows.Close()
	n, overdue := 0, 0
	for rows.Next() {
		var due string
		if err := rows.Scan(&due); err != nil {
			return 0, 0, fmt.Errorf("dashboard: flags: %w", err)
		}
		n++
		if d, err := time.Parse(time.DateOnly, first10(due)); err == nil && d.Before(c.today) {
			overdue++
		}
	}
	return n, overdue, rows.Err()
}

func first10(s string) string {
	if len(s) > 10 {
		return s[:10]
	}
	return s
}

// regionalNotes is the Regional Lead's training feedback and coaching shared
// with the lead and not yet acknowledged.
func (s *Service) regionalNotes(ctx context.Context, c *leadCtx) (int, int, error) {
	if c.p.StaffProfileID == "" {
		return 0, 0, nil
	}
	var feedback, coaching int
	err := s.db.QueryRow(ctx, `SELECT count(*) FILTER (WHERE kind = 'training_observation'), count(*) FILTER (WHERE kind = 'pl_coaching')
FROM cce_regional_engagement WHERE feedback_shared_at IS NOT NULL AND acknowledged_at IS NULL
AND program_lead_ids @> ARRAY[$1]::varchar[]`, c.p.StaffProfileID).Scan(&feedback, &coaching)
	if err != nil {
		return 0, 0, fmt.Errorf("dashboard: regional notes: %w", err)
	}
	return feedback, coaching, nil
}

// officerSchools is each line-managed officer's operating schools.
func (s *Service) officerSchools(ctx context.Context, c *leadCtx) (map[string][]string, error) {
	out := map[string][]string{}
	if len(c.teamStaff) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT DISTINCT a.staff_id, a.school_id FROM staff_school_assignment a
JOIN school s ON s.id = a.school_id WHERE a.staff_id = ANY($1) AND s.deleted_at IS NULL AND s.operational_status = ANY($2)`,
		c.teamStaff, rules.Lead.OperatingStatuses)
	if err != nil {
		return nil, fmt.Errorf("dashboard: officers' schools: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var staff, school string
		if err := rows.Scan(&staff, &school); err != nil {
			return nil, fmt.Errorf("dashboard: officers' schools: %w", err)
		}
		out[staff] = append(out[staff], school)
	}
	return out, rows.Err()
}

// teamActivityWhere is _team_activity_qs over the line-managed team for
// the year: the team's own work, the partner work they monitor, and work at
// the portfolio's schools, called-off work left out.
const teamActivityWhere = `a.fy = $1 AND a.deleted_at IS NULL AND NOT COALESCE(a.status = ANY($2), false)
AND (a.responsible_staff_id = ANY($3) OR (a.delivery_type = 'partner' AND a.monitored_by_staff_id = ANY($3))
  OR a.school_id = ANY($4))`

// officerRisk is how many line-managed officers PLAnalyticsService._cceo_risk
// puts at High or Critical, and whether any is Critical.
func (s *Service) officerRisk(ctx context.Context, c *leadCtx) (int, bool, error) {
	if len(c.team) == 0 {
		return 0, false, nil
	}
	schools, err := s.officerSchools(ctx, c)
	if err != nil {
		return 0, false, err
	}
	targets := map[string]int{}
	rows, err := s.db.Query(ctx, `SELECT staff_id, COALESCE(visits_target, 0) + COALESCE(trainings_target, 0)
  + COALESCE(cluster_meetings_target, 0) + COALESCE(ssa_target, 0) FROM staff_target_profile WHERE staff_id = ANY($1) AND fy = $2`,
		c.teamStaff, c.fy)
	if err != nil {
		return 0, false, fmt.Errorf("dashboard: officers' targets: %w", err)
	}
	for rows.Next() {
		var staff string
		var total int
		if err := rows.Scan(&staff, &total); err != nil {
			rows.Close()
			return 0, false, fmt.Errorf("dashboard: officers' targets: %w", err)
		}
		targets[staff] = total
	}
	rows.Close()
	ownerOf := map[string]string{}
	for _, o := range c.team {
		for _, id := range o.ids() {
			ownerOf[id] = o.staffID
		}
	}
	args := []any{c.fy, rules.Lead.NotInPlanStatuses, c.teamIDs, c.schoolRef}
	achieved := map[string]int{}
	acts, err := s.db.Query(ctx, `SELECT a.responsible_staff_id, a.monitored_by_staff_id, a.activity_type FROM activity a
WHERE `+teamActivityWhere+` AND a.status = ANY($5)
AND (a.responsible_staff_id = ANY($3) OR (a.responsible_staff_id IS NULL AND a.monitored_by_staff_id = ANY($3)))`,
		append(args, rules.Lead.CompletedStatuses)...)
	if err != nil {
		return 0, false, fmt.Errorf("dashboard: officers' completed work: %w", err)
	}
	buckets := [][]string{rules.Lead.VisitTypes, rules.Lead.TrainingTypes, rules.Lead.ClusterMeetingTypes, rules.Lead.SSACollectionTypes}
	for acts.Next() {
		var resp, mon *string
		var kind string
		if err := acts.Scan(&resp, &mon, &kind); err != nil {
			acts.Close()
			return 0, false, fmt.Errorf("dashboard: officers' completed work: %w", err)
		}
		owner := ""
		if resp == nil {
			owner = ownerOf[deref(mon)]
		} else {
			owner = ownerOf[*resp]
		}
		if owner == "" {
			continue
		}
		for _, b := range buckets {
			if slices.Contains(b, kind) {
				achieved[owner]++
			}
		}
	}
	acts.Close()
	latest, err := s.latestSSAYear(ctx, c)
	if err != nil {
		return 0, false, err
	}
	high, critical := 0, false
	for _, o := range c.team {
		backlog, err := count(ctx, s.db, `SELECT count(*) FROM activity a WHERE `+teamActivityWhere+`
AND a.status = ANY($5) AND (a.responsible_staff_id = ANY($6) OR a.school_id = ANY($7))`,
			c.fy, rules.Lead.NotInPlanStatuses, c.teamIDs, c.schoolRef, rules.Lead.CCEOBacklogStatuses, o.ids(), schools[o.staffID])
		if err != nil {
			return 0, false, err
		}
		pct := 0
		if t := targets[o.staffID]; t > 0 {
			pct = int(math.RoundToEven(float64(achieved[o.staffID]) / float64(t) * 100))
		}
		avg, err := s.averageSSA(ctx, latest, schools[o.staffID])
		if err != nil {
			return 0, false, err
		}
		switch cceoRisk(pct, targets[o.staffID], backlog, avg, len(schools[o.staffID])) {
		case "Critical":
			high++
			critical = true
		case "High":
			high++
		}
	}
	return high, critical, nil
}

// latestSSAYear is _cycle_fys' latest: the newest year up to this one with
// a confirmed SSA at a portfolio school.
func (s *Service) latestSSAYear(ctx context.Context, c *leadCtx) (string, error) {
	var fy *string
	if err := s.db.QueryRow(ctx, `SELECT max(fy) FROM ssa_record WHERE deleted_at IS NULL AND school_id = ANY($1)
AND verification_status = 'confirmed' AND fy <= $2`, c.schoolRef, c.fy).Scan(&fy); err != nil {
		return "", fmt.Errorf("dashboard: the SSA year: %w", err)
	}
	return deref(fy), nil
}

// averageSSA is an officer's mean confirmed SSA score in the year, over
// records (a school with two weighs twice), on the 0–10 scale to one place.
func (s *Service) averageSSA(ctx context.Context, fy string, schools []string) (*float64, error) {
	if fy == "" || len(schools) == 0 {
		return nil, nil
	}
	var sum *float64
	var n int
	if err := s.db.QueryRow(ctx, `SELECT sum(average_score), count(*) FROM ssa_record WHERE deleted_at IS NULL
AND school_id = ANY($1) AND verification_status = 'confirmed' AND fy = $2 AND average_score IS NOT NULL`, schools, fy).
		Scan(&sum, &n); err != nil {
		return nil, fmt.Errorf("dashboard: an officer's SSA: %w", err)
	}
	if n == 0 || sum == nil {
		return nil, nil
	}
	v := roundTo(roundTo(*sum/float64(n), 6), 1)
	return &v, nil
}

func roundTo(v float64, places int) float64 {
	p := math.Pow(10, float64(places))
	return math.RoundToEven(v*p) / p
}

// cceoRisk is _cceo_risk's band.
func cceoRisk(targetPct, targetTotal, backlog int, avgSSA *float64, schools int) string {
	score, expected := 0, 50
	switch {
	case targetTotal > 0 && float64(targetPct) < float64(expected)*0.5:
		score += 2
	case targetTotal > 0 && targetPct < expected:
		score++
	}
	switch {
	case backlog >= 10:
		score += 2
	case backlog >= 4:
		score++
	}
	switch {
	case avgSSA != nil && *avgSSA < 4:
		score += 2
	case avgSSA != nil && *avgSSA < 6:
		score++
	}
	if avgSSA == nil && schools > 0 {
		score++
	}
	switch {
	case score >= 5:
		return "Critical"
	case score >= 3:
		return "High"
	case score >= 1:
		return "Moderate"
	}
	return "Low"
}

// overloaded is _overloaded_cceos: officers holding more schools than one
// officer can, or more work scheduled this week than one can deliver.
func (s *Service) overloaded(ctx context.Context, c *leadCtx) (int, error) {
	if len(c.team) == 0 {
		return 0, nil
	}
	schools, err := s.officerSchools(ctx, c)
	if err != nil {
		return 0, err
	}
	monday := c.today.AddDate(0, 0, -((int(c.today.Weekday()) + 6) % 7))
	ids := append(append([]string{}, c.teamIDs...), c.ownIDs...)
	n := 0
	for _, o := range c.team {
		load, err := count(ctx, s.db, `SELECT count(*) FROM activity a WHERE a.fy = $1 AND a.deleted_at IS NULL
AND (a.responsible_staff_id = ANY($2) OR a.school_id = ANY($3)) AND a.responsible_staff_id = ANY($4)
AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date BETWEEN $5 AND $6`,
			c.fy, ids, c.schoolRef, o.ids(), monday.Format(time.DateOnly), monday.AddDate(0, 0, 6).Format(time.DateOnly))
		if err != nil {
			return 0, err
		}
		if len(schools[o.staffID]) > rules.Lead.SchoolCapacity || load > rules.Lead.WeeklyCapacity {
			n++
		}
	}
	return n, nil
}

// leaveConflicts is _leave_conflicts: the team's approved or pending leave
// in the next week that overlaps work scheduled inside it.
func (s *Service) leaveConflicts(ctx context.Context, c *leadCtx) (int, error) {
	if len(c.teamStaff) == 0 {
		return 0, nil
	}
	horizon := c.today.AddDate(0, 0, rules.Lead.LeaveLookaheadDays)
	rows, err := s.db.Query(ctx, `SELECT staff_id, start_date, end_date FROM leave WHERE staff_id = ANY($1)
AND status IN ('approved', 'pending') AND start_date <= $2 AND end_date >= $3`,
		c.teamStaff, horizon.Format(time.DateOnly), c.today.Format(time.DateOnly))
	if err != nil {
		return 0, fmt.Errorf("dashboard: leave conflicts: %w", err)
	}
	type window struct {
		staff      string
		start, end time.Time
	}
	var windows []window
	for rows.Next() {
		var w window
		var b, e string
		if err := rows.Scan(&w.staff, &b, &e); err != nil {
			rows.Close()
			return 0, fmt.Errorf("dashboard: leave conflicts: %w", err)
		}
		var errB, errE error
		w.start, errB = time.Parse(time.DateOnly, first10(b))
		w.end, errE = time.Parse(time.DateOnly, first10(e))
		if errB == nil && errE == nil {
			windows = append(windows, w)
		}
	}
	rows.Close()
	if len(windows) == 0 {
		return 0, nil
	}
	first, last := windows[0].start, windows[0].end
	for _, w := range windows {
		if w.start.Before(first) {
			first = w.start
		}
		if w.end.After(last) {
			last = w.end
		}
	}
	ownerOf := map[string]string{}
	for _, o := range c.team {
		for _, id := range o.ids() {
			ownerOf[id] = o.staffID
		}
	}
	acts, err := s.db.Query(ctx, `SELECT a.responsible_staff_id, a.monitored_by_staff_id, (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date
FROM activity a WHERE a.deleted_at IS NULL
AND (a.responsible_staff_id = ANY($1) OR (a.responsible_staff_id IS NULL AND a.monitored_by_staff_id = ANY($1)))
AND (a.scheduled_date AT TIME ZONE 'Africa/Nairobi')::date BETWEEN $2 AND $3 AND a.status IS DISTINCT FROM 'cancelled'`,
		c.teamIDs, first.Format(time.DateOnly), last.Format(time.DateOnly))
	if err != nil {
		return 0, fmt.Errorf("dashboard: leave conflicts: %w", err)
	}
	scheduled := map[string][]time.Time{}
	for acts.Next() {
		var resp, mon *string
		var when time.Time
		if err := acts.Scan(&resp, &mon, &when); err != nil {
			acts.Close()
			return 0, fmt.Errorf("dashboard: leave conflicts: %w", err)
		}
		owner := ""
		if resp != nil && *resp != "" {
			owner = ownerOf[*resp]
		} else {
			owner = ownerOf[deref(mon)]
		}
		if owner != "" {
			scheduled[owner] = append(scheduled[owner], when)
		}
	}
	acts.Close()
	n := 0
	for _, w := range windows {
		for _, d := range scheduled[w.staff] {
			if !d.Before(w.start) && !d.After(w.end) {
				n++
				break
			}
		}
	}
	return n, nil
}

// partnerLate is partner_delivery's late: partner work the team monitors this
// year past its planned date and neither settled nor completed.
func (s *Service) partnerLate(ctx context.Context, c *leadCtx) (int, error) {
	if len(c.teamIDs) == 0 {
		return 0, nil
	}
	return count(ctx, s.db, `SELECT count(*) FROM activity a WHERE a.fy = $1 AND a.deleted_at IS NULL AND a.delivery_type = 'partner'
AND (a.responsible_staff_id = ANY($2) OR (a.responsible_staff_id IS NULL AND a.monitored_by_staff_id = ANY($2)))
AND NOT COALESCE(a.status = ANY($3), false) AND a.planned_date < $4
AND NOT COALESCE(a.status = ANY($5), false) AND NOT COALESCE(a.status = ANY($6), false)`,
		c.fy, c.teamIDs, rules.Lead.ReleasedStatuses, c.today.Format(time.DateOnly),
		rules.Lead.PartnerSettledStatuses, rules.Lead.CompletedStatuses)
}

// leadHeader is the phone's header over the lead's dashboard: how many
// things need them, and the most pressing one's action (else their team's
// plans).
func leadHeader(cards []card, fy string) *screensv1.PageHeader {
	h := &screensv1.PageHeader{
		Eyebrow:     "Program leadership",
		Title:       "Lead the team forward",
		Description: "Start with what your team is waiting on, then coach, direct and follow up.",
		Badges:      []*screensv1.PageBadge{{Text: fmt.Sprintf("Needs attention: %d", len(cards)), Tone: "plain"}},
	}
	label, url := "Open Planning Oversight", rules.Lead.TeamOversightURL+"?fy="+fy
	path := rules.Lead.TeamOversightURL
	if len(cards) > 0 {
		label, url, path = cards[0].action, cards[0].url, cards[0].url
	}
	if rules.Lead.Opens[path] {
		h.Actions = []*screensv1.PageAction{{Key: "primary-action", Label: label, Primary: true, Enabled: true, Href: url}}
	}
	return h
}

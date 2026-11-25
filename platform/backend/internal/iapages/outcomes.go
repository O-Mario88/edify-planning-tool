package iapages

import (
	"context"
	"fmt"
	"math"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/allocations"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolcode"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schoolprofile"
)

// outcomeRules is the Outcomes view's vocabulary (export_ia_pages_rules
// _outcomes).
type outcomeRules struct {
	Interventions       [][2]string       `json:"interventions"`
	StateLabels         map[string]string `json:"state_labels"`
	Measured            []string          `json:"measured"`
	Limitation          string            `json:"limitation"`
	PortfolioLimitation string            `json:"portfolio_limitation"`
	CohortPeriod        string            `json:"cohort_period"`
	RuleSentence        string            `json:"rule_sentence"`
	FallbackLabel       string            `json:"fallback_label"`
	MinIntervalDays     int               `json:"min_interval_days"`
	MinN                int               `json:"min_n"`
	InsufficientLabel   string            `json:"insufficient_label"`
	AreaApprovedStatus  string            `json:"area_approved_status"`
	RulePublishedStatus string            `json:"rule_published_status"`
}

// outcomesPageSize is TABLE_PAGE_SIZE, the enrolments' page.
const outcomesPageSize = 50

// enrolment is one project-school enrolment as evidence_row reads it.
type enrolment struct {
	id, schoolID, school, ownerID, projectID, project string
	intervention, classification                      string
	baselineScore, followUpScore                      *float64
	baselineSet, followUpSet                          bool
	baselineOK, followUpOK                            bool
	baselineAt, followUpAt                            *time.Time
	due, start                                        *time.Time
	created                                           time.Time
	// What a frozen report snapshot keeps (reports.ROW_KEYS).
	baselineID, followUpID string
	mappingVersion         *int
}

// evidenceRow is ia_workflow.evidence_row's result.
type evidenceRow struct {
	schoolID, school, ownerID, owner, projectID, project string
	code, intervention, state, status, action, due       string
	// schoolCode is the school's ID as the web fills it in.
	schoolCode         string
	baseline, followUp *float64
	measured           bool
	delta              *float64
	// What a frozen report snapshot keeps (reports.ROW_KEYS).
	assignmentID, baselineID, followUpID, baselineDate, followUpDate string
	mappingVersion                                                   *int
}

// cohortDomain is one row of _cohort_domains.
type cohortDomain struct {
	name                               string
	pairs, schools, improved, declined int
	improvedPct, declinedPct           *int
	delta                              *float64
	withheld                           bool
}

// outcomeWorkspace is ia_workflow.outcome_workspace.
type outcomeWorkspace struct {
	rows                                            []evidenceRow
	projects                                        [][2]string
	project                                         string
	total, uniqueSchools, measured, measuredSchools int
	counts                                          map[string]int
	domains                                         []cohortDomain
	scopeLabel                                      string
}

// share is ia_workflow._share: a whole percentage, rounded as Python rounds.
func share(part, whole int) *int {
	if whole == 0 {
		return nil
	}
	v := int(math.RoundToEven(100 * float64(part) / float64(whole)))
	return &v
}

// medianOf is ia_workflow._median.
func medianOf(values []float64) *float64 {
	if len(values) == 0 {
		return nil
	}
	v := slices.Clone(values)
	sort.Float64s(v)
	m := v[len(v)/2]
	if len(v)%2 == 0 {
		m = (v[len(v)/2-1] + v[len(v)/2]) / 2
	}
	r := math.RoundToEven(m*100) / 100
	return &r
}

// chosenFY is ia_workflow._chosen_fy: a valid ?fy=, else the operational
// year; every year after the first can be compared.
func chosenFY(query url.Values, now time.Time) (string, []string) {
	options := schooldirectory.FYOptions(now)
	choices := []string{}
	for _, o := range options {
		if o > options[0] {
			choices = append(choices, o)
		}
	}
	fy := strings.TrimSpace(query.Get("fy"))
	if !slices.Contains(choices, fy) {
		fy = schooldirectory.OperationalFY(now)
	}
	return fy, choices
}

// nairobi is the platform's local time (TIME_ZONE).
var nairobi = func() *time.Location {
	z, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		return time.FixedZone("EAT", 3*60*60)
	}
	return z
}()

func utcDay(t time.Time) time.Time {
	t = t.UTC()
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

func localDay(t time.Time) time.Time {
	t = t.In(nairobi)
	return time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
}

// outcomes is the Outcomes view's blocks, or served false where it reads
// what Go does not draw yet: paired SSAs, published measurement rules,
// evidence beyond the SSA, an empty scope or enrolment list, or a second
// page.
func (s *Service) outcomes(ctx context.Context, scope schooldirectory.Scope, query url.Values, now time.Time) ([]*screensv1.PageBlock, bool, error) {
	o := rules.Dashboard.Outcomes
	if scope.SummaryOnly {
		return nil, false, nil
	}
	fy, choices := chosenFY(query, now)
	prev := strconv.Itoa(mustInt(fy) - 1)
	schools, sargs := activeSchools(scope)
	var inScope int
	var paired, published, evidence bool
	n := len(sargs)
	if err := s.db.QueryRow(ctx, fmt.Sprintf(`
WITH sc AS (SELECT s.id FROM school s WHERE %[1]s),
cur AS (SELECT DISTINCT ON (r.school_id) r.school_id, (r.date_of_ssa AT TIME ZONE 'UTC')::date AS d FROM ssa_record r
        WHERE r.school_id IN (SELECT id FROM sc) AND r.fy = $%[2]d AND r.deleted_at IS NULL AND r.verification_status = 'confirmed'
        ORDER BY r.school_id, r.date_of_ssa DESC, r.created_at DESC),
pre AS (SELECT DISTINCT ON (r.school_id) r.school_id, (r.date_of_ssa AT TIME ZONE 'UTC')::date AS d FROM ssa_record r
        WHERE r.school_id IN (SELECT school_id FROM cur) AND r.fy = $%[3]d AND r.deleted_at IS NULL AND r.verification_status = 'confirmed'
        ORDER BY r.school_id, r.date_of_ssa DESC, r.created_at DESC)
SELECT (SELECT count(*) FROM sc),
       EXISTS (SELECT 1 FROM cur JOIN pre USING (school_id) WHERE cur.d IS NULL OR pre.d IS NULL OR cur.d - pre.d >= $%[4]d),
       EXISTS (SELECT 1 FROM activity_intervention_mapping m WHERE m.status = $%[5]d AND m.active
               AND COALESCE(m.intervention, '') <> '' AND btrim(COALESCE(m.country, '')) = ''),
       EXISTS (SELECT 1 FROM impact_learning_result) OR EXISTS (SELECT 1 FROM impact_discipleship_record)
       OR EXISTS (SELECT 1 FROM impact_edtech_deployment) OR EXISTS (SELECT 1 FROM impact_edtech_check)
       OR EXISTS (SELECT 1 FROM mscs_story)`, schools, n+1, n+2, n+3, n+4),
		append(slices.Clone(sargs), fy, prev, o.MinIntervalDays, o.RulePublishedStatus)...).Scan(&inScope, &paired, &published, &evidence); err != nil {
		return nil, true, fmt.Errorf("iapages: reading the portfolio's evidence: %w", err)
	}
	// Each of these reads figures Go does not compute yet.
	if inScope == 0 || paired || published || evidence {
		return nil, false, nil
	}
	groups, err := s.outcomeAreaGroups(ctx)
	if err != nil {
		return nil, true, err
	}
	if len(groups) > outcomesPageSize {
		return nil, false, nil
	}
	w, err := s.workspace(ctx, scope, schools, sargs, query.Get("project"), now)
	if err != nil {
		return nil, true, err
	}
	if w.total == 0 || w.total > outcomesPageSize {
		// The empty table's words and a second page are not drawn here yet.
		return nil, false, nil
	}
	blocks := outcomeFilters(fy, choices, w)
	blocks = append(blocks, portfolioBlocks(w.scopeLabel, fy, prev, inScope, groups)...)
	blocks = append(blocks, beyondSSABlocks()...)
	blocks = append(blocks, cohortBlocks(w)...)
	return blocks, true, nil
}

func mustInt(s string) int {
	n, _ := strconv.Atoi(s)
	return n
}

// activeSchools is scoped_school_queryset(scope, active_schools()) over
// school `s`.
func activeSchools(scope schooldirectory.Scope) (string, []any) {
	args := []any{}
	where := schooldirectory.AnalyticsReach(scope, &args)
	args = append(args, rules.Dashboard.OperatingStatuses)
	return fmt.Sprintf("%s AND s.operational_status = ANY($%d)", where, len(args)), args
}

// areaGroup is one of _outcome_area_groups: an approved area's name and its
// SSA domains, or the domains no area claims.
type areaGroup struct {
	name    string
	domains []string
}

// outcomeAreaGroups is _outcome_area_groups' names.
func (s *Service) outcomeAreaGroups(ctx context.Context) ([]string, error) {
	groups, err := s.areaGroups(ctx)
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(groups))
	for _, g := range groups {
		names = append(names, g.name)
	}
	return names, nil
}

// areaGroups is _outcome_area_groups: the approved areas (the newest
// approved version of each code) by name, then the domains no area claims.
func (s *Service) areaGroups(ctx context.Context) ([]areaGroup, error) {
	o := rules.Dashboard.Outcomes
	rows, err := s.db.Query(ctx, `
SELECT a.code, a.name, a.version, d.intervention FROM impact_outcome_area_domain d JOIN impact_outcome_area a ON a.id = d.area_id
WHERE a.status = $1 ORDER BY a.code, a.version DESC, d.intervention`, o.AreaApprovedStatus)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the outcome areas: %w", err)
	}
	defer rows.Close()
	type area struct {
		name    string
		version int
		domains []string
	}
	areas := map[string]*area{}
	order := []string{}
	for rows.Next() {
		var code, name, intervention string
		var version int
		if err := rows.Scan(&code, &name, &version, &intervention); err != nil {
			return nil, fmt.Errorf("iapages: reading an outcome area: %w", err)
		}
		a := areas[code]
		if a == nil {
			a = &area{name: name, version: version}
			areas[code] = a
			order = append(order, code)
		}
		if version == a.version && !slices.Contains(a.domains, intervention) {
			a.domains = append(a.domains, intervention)
		}
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iapages: reading the outcome areas: %w", err)
	}
	list := []*area{}
	for _, code := range order {
		list = append(list, areas[code])
	}
	sort.SliceStable(list, func(i, j int) bool { return strings.ToLower(list[i].name) < strings.ToLower(list[j].name) })
	claimed := map[string]bool{}
	groups := []areaGroup{}
	for _, a := range list {
		groups = append(groups, areaGroup{name: a.name, domains: a.domains})
		for _, d := range a.domains {
			claimed[d] = true
		}
	}
	unclaimed := []string{}
	for _, i := range o.Interventions {
		if !claimed[i[0]] {
			unclaimed = append(unclaimed, i[0])
		}
	}
	if len(unclaimed) > 0 {
		groups = append(groups, areaGroup{name: "Not yet in an approved outcome area", domains: unclaimed})
	}
	return groups, nil
}

// workspace reads the project enrolments in scope (current_enrolments over
// the scope's operating schools) and makes their rows.
func (s *Service) workspace(ctx context.Context, scope schooldirectory.Scope, schools string, sargs []any, project string, now time.Time) (outcomeWorkspace, error) {
	w := outcomeWorkspace{project: project, counts: map[string]int{}, scopeLabel: scope.Country}
	if w.scopeLabel == "" {
		w.scopeLabel = "Assigned access scope"
	}
	from := `FROM project_school_assignment a JOIN school s ON s.id = a.school_id JOIN project pr ON pr.id = a.project_id`
	where := ` WHERE ` + schools + ` AND pr.deleted_at IS NULL`
	prows, err := s.db.Query(ctx, "SELECT DISTINCT a.project_id, pr.name "+from+where+" ORDER BY pr.name", sargs...)
	if err != nil {
		return w, fmt.Errorf("iapages: reading the enrolled projects: %w", err)
	}
	for prows.Next() {
		var id, name string
		if err := prows.Scan(&id, &name); err != nil {
			prows.Close()
			return w, fmt.Errorf("iapages: reading an enrolled project: %w", err)
		}
		w.projects = append(w.projects, [2]string{id, name})
	}
	prows.Close()
	args := slices.Clone(sargs)
	if project != "" {
		args = append(args, project)
		where += fmt.Sprintf(" AND a.project_id = $%d", len(args))
	}
	today := localDay(now)
	args = append(args, today)
	t := len(args)
	rows, err := s.db.Query(ctx, fmt.Sprintf(`
SELECT a.id, a.school_id, s.name, COALESCE(s.account_owner_id, ''), a.project_id, pr.name,
       COALESCE(NULLIF(a.matched_intervention, ''), NULLIF(pr.intervention, ''), ''), COALESCE(a.impact_classification, ''),
       a.baseline_score, a.follow_up_score, a.baseline_ssa_id IS NOT NULL, a.follow_up_ssa_id IS NOT NULL,
       COALESCE(b.deleted_at IS NULL AND b.verification_status = 'confirmed' AND b.school_id = a.school_id
                AND (b.date_of_ssa AT TIME ZONE 'UTC')::date <= $%[2]d, FALSE), b.date_of_ssa,
       COALESCE(f.deleted_at IS NULL AND f.verification_status = 'confirmed' AND f.school_id = a.school_id
                AND (f.date_of_ssa AT TIME ZONE 'UTC')::date <= $%[2]d, FALSE), f.date_of_ssa,
       a.follow_up_due_on, a.start_date, a.created_at, COALESCE(a.baseline_ssa_id, ''), COALESCE(a.follow_up_ssa_id, ''), a.mapping_version
%[1]s
LEFT JOIN ssa_record b ON b.id = a.baseline_ssa_id LEFT JOIN ssa_record f ON f.id = a.follow_up_ssa_id%[3]s
ORDER BY a.follow_up_due_on ASC NULLS LAST, s.name, a.project_id`, from, t, where), args...)
	if err != nil {
		return w, fmt.Errorf("iapages: reading the enrolments: %w", err)
	}
	list := []enrolment{}
	for rows.Next() {
		var e enrolment
		if err := rows.Scan(&e.id, &e.schoolID, &e.school, &e.ownerID, &e.projectID, &e.project, &e.intervention, &e.classification,
			&e.baselineScore, &e.followUpScore, &e.baselineSet, &e.followUpSet, &e.baselineOK, &e.baselineAt,
			&e.followUpOK, &e.followUpAt, &e.due, &e.start, &e.created, &e.baselineID, &e.followUpID, &e.mappingVersion); err != nil {
			rows.Close()
			return w, fmt.Errorf("iapages: reading an enrolment: %w", err)
		}
		list = append(list, e)
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return w, fmt.Errorf("iapages: reading the enrolments: %w", err)
	}
	for _, e := range list {
		w.rows = append(w.rows, e.row(today))
	}
	if err := s.baselineDetails(ctx, list, w.rows); err != nil {
		return w, err
	}
	refs := make([]string, 0, len(w.rows))
	for _, r := range w.rows {
		refs = append(refs, r.schoolID)
	}
	codes, err := schoolcode.Lookup(ctx, s.db, refs)
	if err != nil {
		return w, err
	}
	for i := range w.rows {
		w.rows[i].schoolCode = codes.Of(w.rows[i].schoolID)
	}
	owners := []string{}
	for _, r := range w.rows {
		if r.ownerID != "" {
			owners = append(owners, r.ownerID)
		}
	}
	names, err := liveStaffNames(ctx, s, owners)
	if err != nil {
		return w, err
	}
	schoolsSeen, measuredSeen := map[string]bool{}, map[string]bool{}
	measured := []evidenceRow{}
	for i := range w.rows {
		r := &w.rows[i]
		r.owner = "Unassigned — coordinate with programme lead"
		if name, ok := names[r.ownerID]; ok {
			r.owner = name
		}
		w.counts[r.state]++
		schoolsSeen[r.schoolID] = true
		if r.measured {
			measured = append(measured, *r)
			measuredSeen[r.schoolID] = true
		}
	}
	w.total, w.uniqueSchools = len(w.rows), len(schoolsSeen)
	w.measured, w.measuredSchools = len(measured), len(measuredSeen)
	w.domains = cohortDomains(measured)
	return w, nil
}

// liveStaffNames is each live People record's account name.
func liveStaffNames(ctx context.Context, s *Service, ids []string) (map[string]string, error) {
	out := map[string]string{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.db.Query(ctx, `SELECT sp.id, u.name FROM staff_profile sp JOIN "user" u ON u.id = sp.user_id
WHERE sp.id = ANY($1) AND sp.deleted_at IS NULL`, ids)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the account owners: %w", err)
	}
	defer rows.Close()
	for rows.Next() {
		var id string
		var name *string
		if err := rows.Scan(&id, &name); err != nil {
			return nil, fmt.Errorf("iapages: reading an account owner: %w", err)
		}
		if name != nil {
			out[id] = *name
		}
	}
	return out, rows.Err()
}

func inRange(v *float64) bool { return v != nil && *v >= 0 && *v <= 10 }

// row is evidence_row.
func (e enrolment) row(today time.Time) evidenceRow {
	o := rules.Dashboard.Outcomes
	validBaseline := e.baselineSet && e.baselineOK && inRange(e.baselineScore)
	validFollowUp := e.followUpSet && e.followUpOK && inRange(e.followUpScore) && validBaseline &&
		e.followUpAt != nil && e.baselineAt != nil && e.followUpAt.After(*e.baselineAt)
	measured := validFollowUp && slices.Contains(o.Measured, e.classification)
	var state, action string
	switch {
	case !validBaseline:
		state, action = "baseline_missing", "Collect or confirm the previous FY SSA"
	case measured:
		state, action = e.classification, "Review findings with the school"
	case e.followUpSet:
		state, action = "evidence_review", "Review follow-up evidence and classification"
	case e.due == nil:
		state, action = "not_scheduled", "Review verified delivery and set the follow-up window"
	case e.due.Before(today):
		state, action = "overdue", "Coordinate the overdue follow-up"
	case e.due.Equal(today):
		state, action = "due", "Collect the follow-up assessment"
	default:
		state, action = "upcoming", "Prepare the follow-up assessment"
	}
	label := "Not mapped"
	for _, i := range o.Interventions {
		if i[0] == e.intervention {
			label = i[1]
		}
	}
	status, ok := o.StateLabels[state]
	if !ok {
		words := strings.ReplaceAll(state, "_", " ")
		status = strings.ToUpper(words[:1]) + strings.ToLower(words[1:])
	}
	r := evidenceRow{schoolID: e.schoolID, school: e.school, ownerID: e.ownerID, projectID: e.projectID, project: e.project,
		code: e.intervention, intervention: label, state: state, status: status, action: action, measured: measured}
	r.assignmentID, r.mappingVersion = e.id, e.mappingVersion
	if validBaseline {
		r.baseline, r.baselineID = e.baselineScore, e.baselineID
		r.baselineDate = e.baselineAt.UTC().Format(time.DateOnly)
	}
	if validFollowUp {
		r.followUp, r.followUpID = e.followUpScore, e.followUpID
		r.followUpDate = e.followUpAt.UTC().Format(time.DateOnly)
	}
	if e.due != nil {
		r.due = e.due.Format("2006-01-02")
	}
	if measured {
		d := math.RoundToEven((*e.followUpScore-*e.baselineScore)*100) / 100
		r.delta = &d
	}
	return r
}

// baselineDetails is _baseline_details: a missing previous FY SSA whose
// confirmed reading exists, or whose enrolment names no domain, says so.
func (s *Service) baselineDetails(ctx context.Context, list []enrolment, rows []evidenceRow) error {
	open := map[[2]string]bool{}
	schools, codes := []string{}, []string{}
	for i, e := range list {
		if rows[i].state != "baseline_missing" || e.baselineScore != nil || e.intervention == "" {
			continue
		}
		if !open[[2]string{e.schoolID, e.intervention}] {
			open[[2]string{e.schoolID, e.intervention}] = true
			schools, codes = append(schools, e.schoolID), append(codes, e.intervention)
		}
	}
	readings := map[[2]string][]time.Time{}
	if len(schools) > 0 {
		rs, err := s.db.Query(ctx, `
SELECT r.school_id, sc.intervention, r.date_of_ssa, sc.score FROM ssa_score sc JOIN ssa_record r ON r.id = sc.ssa_record_id
WHERE r.school_id = ANY($1) AND r.verification_status = 'confirmed' AND r.deleted_at IS NULL AND sc.intervention = ANY($2)
ORDER BY r.date_of_ssa, r.id`, schools, codes)
		if err != nil {
			return fmt.Errorf("iapages: reading the baseline readings: %w", err)
		}
		for rs.Next() {
			var school, code string
			var at *time.Time
			var score *float64
			if err := rs.Scan(&school, &code, &at, &score); err != nil {
				rs.Close()
				return fmt.Errorf("iapages: reading a baseline reading: %w", err)
			}
			if at == nil || !inRange(score) {
				continue
			}
			readings[[2]string{school, code}] = append(readings[[2]string{school, code}], localDay(*at))
		}
		rs.Close()
		if err := rs.Err(); err != nil {
			return fmt.Errorf("iapages: reading the baseline readings: %w", err)
		}
	}
	for i, e := range list {
		if rows[i].state != "baseline_missing" || e.baselineScore != nil {
			continue
		}
		if e.intervention == "" {
			rows[i].action = "Name the SSA domain this enrolment measures"
			continue
		}
		start := localDay(e.created)
		if e.start != nil {
			start = utcDay(*e.start)
		}
		found := false
		for _, on := range readings[[2]string{e.schoolID, e.intervention}] {
			if on.After(start) {
				break
			}
			found = true
		}
		if found {
			rows[i].action = "A confirmed SSA exists; it is captured as the previous FY SSA on the next refresh"
		}
	}
	return nil
}

// cohortDomains is _cohort_domains.
func cohortDomains(measured []evidenceRow) []cohortDomain {
	o := rules.Dashboard.Outcomes
	out := []cohortDomain{}
	for _, i := range o.Interventions {
		d := cohortDomain{name: i[1]}
		schools := map[string]bool{}
		moved := []float64{}
		for _, r := range measured {
			if r.code != i[0] {
				continue
			}
			d.pairs++
			schools[r.schoolID] = true
			switch r.state {
			case "improved":
				d.improved++
			case "declined":
				d.declined++
			}
			if r.state != "maintained_strong" && r.delta != nil {
				moved = append(moved, *r.delta)
			}
		}
		d.schools = len(schools)
		d.improvedPct, d.declinedPct = share(d.improved, d.pairs), share(d.declined, d.pairs)
		if d.schools >= o.MinN {
			d.delta = medianOf(moved)
		}
		d.withheld = d.schools > 0 && d.schools < o.MinN
		out = append(out, d)
	}
	return out
}

// metricTile is one registry tile before the strip reads it.
type metricTile struct {
	label, value, helper, tone, href string
}

func tile(label, value, helper, tone, href string) metricTile {
	return metricTile{label, value, helper, tone, href}
}

// tileStrip is components/context_metrics.html as the feed reads it: the
// strip the profile pages draw (the line under a figure kept when brief,
// else read as the note, the SSA domains abbreviated), each figure's tone
// only beside a kept line.
func tileStrip(title string, tiles []metricTile) *screensv1.PageBlock {
	figures := make([]schoolprofile.StripFigure, len(tiles))
	for i, t := range tiles {
		figures[i] = schoolprofile.StripFigure{Label: t.label, Value: t.value, Link: t.href, Helper: t.helper}
	}
	block := schoolprofile.Strip(title, figures)
	for i, m := range block.GetStrip().GetMetrics() {
		if m.Helper != "" {
			m.Tone = tiles[i].tone
		}
	}
	return block
}

func outcomeFilters(fy string, choices []string, w outcomeWorkspace) []*screensv1.PageBlock {
	years := &screensv1.PageFilter{Name: "fy", Value: fy, Caption: "Financial year"}
	for _, c := range choices {
		years.Options = append(years.Options, &screensv1.PageFilterOption{Value: c, Label: fmt.Sprintf("FY%s against FY%d", c, mustInt(c)-1)})
	}
	filters := []*screensv1.PageFilter{years}
	if len(w.projects) > 0 {
		projects := &screensv1.PageFilter{Name: "project", Value: w.project, Caption: "Project cohort",
			Options: []*screensv1.PageFilterOption{{Value: "", Label: "All accessible projects"}}}
		for _, p := range w.projects {
			projects.Options = append(projects.Options, &screensv1.PageFilterOption{Value: p[0], Label: p[1]})
		}
		if !slices.ContainsFunc(w.projects, func(p [2]string) bool { return p[0] == w.project }) {
			projects.Value = ""
		}
		filters = append(filters, projects)
	}
	return []*screensv1.PageBlock{{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
		Filters: filters, Hidden: map[string]string{"view": "outcomes"}}}}}
}

func cell(text string) *screensv1.PageCell { return &screensv1.PageCell{Text: text} }

func columns(labels ...string) []*screensv1.PageColumn {
	out := []*screensv1.PageColumn{}
	for _, l := range labels {
		out = append(out, &screensv1.PageColumn{Label: l})
	}
	return out
}

func tableBlock(t *screensv1.PageTable) *screensv1.PageBlock {
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t}}
}

// portfolioBlocks is School change across the portfolio with nothing
// measured: every area unmeasured.
func portfolioBlocks(scopeLabel, fy, prev string, inScope int, groups []string) []*screensv1.PageBlock {
	o := rules.Dashboard.Outcomes
	period := fmt.Sprintf("FY%s → FY%s", prev, fy)
	strip := tileStrip("School change", []metricTile{
		tile("Schools With Paired Confirmed SSAs", fmt.Sprintf("0 / %d", inScope), period+", readings at least 120 days apart", "info", ""),
		tile("Schools Improved (Share of Measured)", "Not measured", "no school has two comparable confirmed SSAs", "neutral", ""),
		tile("Schools Declined (Share of Measured)", "Not measured", "no school has two comparable confirmed SSAs", "neutral", ""),
		tile("Median Days Between Paired SSAs", "Not measured", "between the two confirmed readings compared", "neutral", ""),
	})
	t := &screensv1.PageTable{Columns: columns("Outcome area / domain", "Schools measured", "Improved", "Declined", "No change", "Median change", "Evidence")}
	for _, g := range groups {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: g, Strong: true}, cell("Not measured"), cell("—"), cell("—"), cell("—"), cell("Not measured"), cell(o.InsufficientLabel),
		}})
	}
	return []*screensv1.PageBlock{
		panelOf("School change across the portfolio", textItem(fmt.Sprintf("%s · every school in scope with a confirmed SSA in FY%s and FY%s · %s",
			scopeLabel, prev, fy, o.FallbackLabel))),
		strip,
		panelOf("By outcome area and SSA domain"),
		tableBlock(t),
		panelOf("", textItem(o.PortfolioLimitation+" "+o.RuleSentence)),
	}
}

// beyondSSABlocks is Student learning, discipleship and EdTech with no
// record of any of them.
func beyondSSABlocks() []*screensv1.PageBlock {
	o := rules.Dashboard.Outcomes
	t := &screensv1.PageTable{Columns: columns("Measure", "Schools with confirmed evidence", "What it shows", "Awaiting verification", "Evidence")}
	for _, r := range [][4]string{
		{"Student learning results", "/ia/school-evidence/?tab=learning", "No class has confirmed results in both years", o.InsufficientLabel},
		{"Discipleship practice", "/ia/school-evidence/?tab=discipleship", "No confirmed discipleship record this year", o.InsufficientLabel},
		{"Most Significant Change stories", "/ia/stories/", "Reviewed stories of spiritual formation, beside the self-scored Christ-like Behaviour and Word of God domains", "Qualitative"},
		{"EdTech rollout", "/ia/school-evidence/?tab=edtech", "No confirmed deployment", o.InsufficientLabel},
	} {
		t.Rows = append(t.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			{Text: r[0], Href: r[1]}, cell("Not measured"), cell(r[2]), cell("0"), cell(r[3]),
		}})
	}
	return []*screensv1.PageBlock{panelOf("Student learning, discipleship and EdTech"), tableBlock(t)}
}

func plural(n int, word string) string {
	if n == 1 {
		return word
	}
	return word + "s"
}

func pctText(p *int) string {
	if p == nil {
		return "None%"
	}
	return strconv.Itoa(*p) + "%"
}

func score(v *float64) string {
	if v == nil {
		return "Missing"
	}
	return allocations.Repr(*v)
}

// cohortBlocks is the project cohorts: the tiles, the evidence context, the
// domains and the enrolments.
func cohortBlocks(w outcomeWorkspace) []*screensv1.PageBlock {
	o := rules.Dashboard.Outcomes
	suffix := ""
	if w.project != "" {
		suffix = "&project=" + w.project
	}
	collection := DashboardPath + "?view=collection" + suffix
	improved, declined := w.counts["improved"], w.counts["declined"]
	tiles := []metricTile{
		tile("Project Enrolments Measured", fmt.Sprintf("%d / %d", w.measured, w.total),
			fmt.Sprintf("%d of %d unique schools", w.measuredSchools, w.uniqueSchools), "info", ""),
	}
	for _, c := range []struct {
		label string
		n     int
		tone  string
	}{{"Project Enrolments Improved", improved, "success"}, {"Project Enrolments Declined", declined, "danger"}} {
		if w.measured == 0 {
			tiles = append(tiles, tile(c.label, "Not measured", "no enrolment has a confirmed previous and current FY SSA", "neutral", ""))
			continue
		}
		tone := c.tone
		if c.tone == "danger" && c.n == 0 {
			tone = "neutral"
		}
		tiles = append(tiles, tile(c.label, pctText(share(c.n, w.measured)), fmt.Sprintf("%d of %d measured enrolments", c.n, w.measured), tone, ""))
	}
	missing, overdue := w.counts["baseline_missing"], w.counts["overdue"]
	tiles = append(tiles,
		tile("Project Enrolments Missing Previous FY SSA", strconv.Itoa(missing), "no confirmed previous FY SSA captured",
			map[bool]string{true: "warning", false: "info"}[missing > 0], collection),
		tile("Project Follow-ups Overdue", strconv.Itoa(overdue), "past the follow-up window",
			map[bool]string{true: "danger", false: "info"}[overdue > 0], collection))
	head := panelOf("Project cohorts", textItem(o.CohortPeriod))
	head.GetPanel().Subtitle = fmt.Sprintf("%s · %d project-school %s in %d unique %s",
		w.scopeLabel, w.total, plural(w.total, "enrolment"), w.uniqueSchools, plural(w.uniqueSchools, "school"))
	domains := &screensv1.PageTable{Columns: columns("Domain", "Measured enrolments", "Unique schools", "Improved", "Declined", "Median change")}
	for _, d := range w.domains {
		measured, imp, dec, median := "Not measured", "—", "—", "Not measured"
		if d.pairs > 0 {
			measured = strconv.Itoa(d.pairs)
			imp = fmt.Sprintf("%s (%d)", pctText(d.improvedPct), d.improved)
			dec = fmt.Sprintf("%s (%d)", pctText(d.declinedPct), d.declined)
		}
		switch {
		case d.withheld:
			median = "n too small"
		case d.delta != nil:
			median = strconv.FormatFloat(*d.delta, 'f', 2, 64)
		}
		domains.Rows = append(domains.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(d.name), cell(measured), cell(strconv.Itoa(d.schools)), cell(imp), cell(dec), cell(median),
		}})
	}
	list := &screensv1.PageTable{Columns: columns("School ID", "School", "Project", "Domain", "SSA scores", "Evidence", "Follow-up due", "Account owner", "Next action")}
	for _, r := range w.rows {
		code := r.schoolCode
		if r.schoolID == "" {
			code = "—"
		}
		due := r.due
		if due == "" {
			due = "Not scheduled"
		}
		list.Rows = append(list.Rows, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cell(code), {Text: r.school, Href: "/schools/" + r.schoolID}, {Text: r.project, Href: "/projects/" + r.projectID},
			cell(r.intervention), cell(score(r.baseline) + " → " + score(r.followUp)), cell(r.status), cell(due), cell(r.owner), cell(r.action),
		}})
	}
	return []*screensv1.PageBlock{
		head,
		tileStrip("Project cohorts", tiles),
		panelOf("", headingItem(fmt.Sprintf("Evidence context %d unmeasured enrolments", w.total-w.measured)),
			textItem(fmt.Sprintf("%d maintained strong performance · %d unchanged · %d follow-ups due today · %d without a follow-up date.",
				w.counts["maintained_strong"], w.counts["no_change"], w.counts["due"], w.counts["not_scheduled"])),
			textItem(o.Limitation)),
		panelOf("Project cohorts by SSA domain"),
		tableBlock(domains),
		panelOf("Project enrolments and next actions"),
		tableBlock(list),
	}
}

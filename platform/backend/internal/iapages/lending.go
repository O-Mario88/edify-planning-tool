package iapages

import (
	"context"
	"fmt"
	"net/url"
	"slices"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// LendingPath is Lending Evidence (apps.frontend.views.ia_lending_views:
// lending_evidence_page over apps.business_transformation.lending_impact):
// the loan-use, enrolment, purpose-output and teacher-completion evidence a
// lending partner reported, the loan impact conclusions, and the financed
// cohorts. It reads; it writes nothing.
const LendingPath = "/ia/lending-evidence/"

type lendingRules struct {
	MoneyRoles           []string          `json:"money_roles"`
	Scope                map[string]string `json:"scope"`
	LegacyPreparer       string            `json:"legacy_preparer"`
	Tabs                 [][2]string       `json:"tabs"`
	StateLabels          map[string]string `json:"state_labels"`
	ClassificationLabels map[string]string `json:"classification_labels"`
	Positive             []string          `json:"positive"`
	Neutral              []string          `json:"neutral"`
	Negative             string            `json:"negative"`
	SnapshotKinds        map[string]string `json:"snapshot_kinds"`
	BaselineKind         string            `json:"baseline_kind"`
	UseReported          string            `json:"use_reported"`
	EvidenceReported     string            `json:"evidence_reported"`
	EvidenceVerified     string            `json:"evidence_verified"`
	IAPending            string            `json:"ia_pending"`
	IAReturned           string            `json:"ia_returned"`
	IAVerified           string            `json:"ia_verified"`
	MinN                 int               `json:"min_n"`
	GradeLabels          map[string]string `json:"grade_labels"`
	PageSize             int               `json:"page_size"`
	CohortCaveat         string            `json:"cohort_caveat"`
}

// The queues' and conclusions' keys (ia_lending_views).
const (
	tabUse         = "use"
	tabEnrolment   = "enrolment"
	tabOutputs     = "outputs"
	tabTeachers    = "teachers"
	tabConclusions = "conclusions"
	tabCohorts     = "cohorts"

	stateToPrepare = "to_prepare"
	stateAwaiting  = "awaiting"
	stateReturned  = "returned"
	stateVerified  = "verified"
)

var stateOrder = []string{stateToPrepare, stateAwaiting, stateReturned, stateVerified}

// lendingQuery is the query the page reads.
var lendingQuery = []string{"tab", "state", "page"}

// inScope is the loans (not deleted) a reader's impact work reaches.
const inScope = "(SELECT l.id FROM bt_mfi_loan l WHERE l.deleted_at IS NULL AND %s)"

// loanScope is scoped_impact_loans as a WHERE over bt_mfi_loan l.
func (s *Service) loanScope(ctx context.Context, p auth.Principal, args *[]any) (string, error) {
	arg := func(v any) string { *args = append(*args, v); return "$" + strconv.Itoa(len(*args)) }
	switch rules.Lending.Scope[p.ActiveRole] {
	case "mfi":
		return "l.mfi_id IN (SELECT mfi_id FROM bt_mfi_membership WHERE user_id = " + arg(p.UserID) + " AND active)", nil
	case "country_bound":
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return "", err
		}
		if scope.CountryScope && scope.Country != "" {
			return "l.school_id IN (SELECT sc.id FROM school sc JOIN region r ON r.id = sc.region_id WHERE r.country = " +
				arg(scope.Country) + ")", nil
		}
		return "TRUE", nil
	case "country":
		return "TRUE", nil
	case "portfolio":
		scope, err := schooldirectory.ResolveScope(ctx, s.db, p, s.now())
		if err != nil {
			return "", err
		}
		return "l.school_id = ANY(" + arg(scope.SchoolIDs) + ")", nil
	}
	return "FALSE", nil
}

type lendingRow struct {
	cells  []string
	action string // the drawer the row's button opens
}

type lendingTab struct {
	description, title, emptyTitle, emptyBody string
	headings                                  []string
	rows                                      []lendingRow
	filter                                    *screensv1.PageFilter
	hidden                                    map[string]string
}

// lendingDay is _day: "6 Nov 2026"; a stored moment is the day Django hands
// back (UTC).
func lendingDay(t time.Time) string { return t.UTC().Format("2 Jan 2006") }

// cellText is _cell's text: None or "" is "—".
func cellText(s *string) string {
	if s == nil || *s == "" {
		return "—"
	}
	return *s
}

func plainCell(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

func numberCell(n *int64) string {
	if n == nil {
		return "—"
	}
	return strconv.FormatInt(*n, 10)
}

// pyCapitalize is str.capitalize(): the first letter up, the rest down.
func pyCapitalize(s string) string {
	r := []rune(strings.ToLower(s))
	if len(r) > 0 {
		r[0] = []rune(strings.ToUpper(string(r[0])))[0]
	}
	return string(r)
}

func (s *Service) lending(ctx context.Context, p auth.Principal, role Role, query url.Values) (*screensv1.GetPageResponse, bool, error) {
	for key := range query {
		if !slices.Contains(lendingQuery, key) {
			return nil, false, nil
		}
	}
	tab := query.Get("tab")
	known := false
	for _, t := range rules.Lending.Tabs {
		known = known || t[0] == tab
	}
	if !known {
		tab = tabUse
	}
	var args []any
	scope, err := s.loanScope(ctx, p, &args)
	if err != nil {
		return nil, true, err
	}
	n := s.now().In(zone)
	today := time.Date(n.Year(), n.Month(), n.Day(), 0, 0, 0, 0, time.UTC)
	counts, err := s.lendingCounts(ctx, scope, args, today)
	if err != nil {
		return nil, true, err
	}
	var t lendingTab
	switch tab {
	case tabUse:
		t, err = s.useTab(ctx, scope, args, slices.Contains(rules.Lending.MoneyRoles, p.ActiveRole))
	case tabEnrolment:
		t, err = s.enrolmentTab(ctx, scope, args)
	case tabOutputs:
		t, err = s.outputTab(ctx, scope, args)
	case tabTeachers:
		t, err = s.teacherTab(ctx, scope, args)
	case tabConclusions:
		t, err = s.conclusionTab(ctx, scope, args, query.Get("state"), today)
	case tabCohorts:
		t, err = s.cohortTab(ctx, scope, args, today)
	}
	if err != nil {
		return nil, true, err
	}
	if len(t.rows) > rules.Lending.PageSize {
		// A queue past one page carries a pager (not built here).
		return nil, false, nil
	}
	return lendingPage(role, tab, counts, t), true, nil
}

type lendingCounts struct {
	toPrepare, awaiting, returned int
	evidence                      map[string]int
}

// unprepared is _unprepared_q over bt_loan_impact_assessment a.
func unprepared(args *[]any) string {
	*args = append(*args, rules.Lending.LegacyPreparer)
	return fmt.Sprintf("(a.prepared_at IS NULL OR a.prepared_by IS NULL OR a.prepared_by = $%d)", len(*args))
}

// lendingCounts is queue_counts.
func (s *Service) lendingCounts(ctx context.Context, scope string, base []any, today time.Time) (lendingCounts, error) {
	c := lendingCounts{evidence: map[string]int{}}
	args := append([]any{}, base...)
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	pending, returned, todayArg := arg(rules.Lending.IAPending), arg(rules.Lending.IAReturned), arg(today)
	un := unprepared(&args)
	loans := fmt.Sprintf(inScope, scope)
	err := s.db.QueryRow(ctx, `SELECT
		  COUNT(*) FILTER (WHERE a.due_date <= `+todayArg+` AND a.ia_status = `+pending+` AND `+un+`),
		  COUNT(*) FILTER (WHERE a.ia_status = `+pending+` AND NOT `+un+`),
		  COUNT(*) FILTER (WHERE a.ia_status = `+returned+`)
		FROM bt_loan_impact_assessment a WHERE a.loan_id IN `+loans, args...).Scan(&c.toPrepare, &c.awaiting, &c.returned)
	if err != nil {
		return c, fmt.Errorf("iapages: counting the conclusions: %w", err)
	}
	queues := map[string]string{
		tabUse:       `SELECT COUNT(*) FROM bt_loan_purpose_allocation x WHERE x.status = $%d AND x.loan_id IN ` + loans,
		tabEnrolment: `SELECT COUNT(*) FROM bt_enrolment_snapshot x WHERE x.status = $%d AND x.loan_id IN ` + loans,
		tabOutputs: `SELECT COUNT(*) FROM bt_purpose_asset_output x JOIN bt_loan_purpose_allocation pa ON pa.id = x.allocation_id
			WHERE x.status = $%d AND pa.loan_id IN ` + loans,
		tabTeachers: `SELECT COUNT(*) FROM bt_teacher_degree_beneficiary x WHERE x.status = $%d AND x.completed_on IS NOT NULL
			AND x.loan_id IN ` + loans,
	}
	for tab, sql := range queues {
		status := rules.Lending.EvidenceReported
		if tab == tabUse {
			status = rules.Lending.UseReported
		}
		qa := append(append([]any{}, base...), status)
		var count int
		if err := s.db.QueryRow(ctx, fmt.Sprintf(sql, len(qa)), qa...).Scan(&count); err != nil {
			return c, fmt.Errorf("iapages: counting the %s queue: %w", tab, err)
		}
		c.evidence[tab] = count
	}
	return c, nil
}

func (s *Service) collect(ctx context.Context, what, sql string, args []any, scan func(pgx.Rows) (lendingRow, error)) ([]lendingRow, error) {
	rows, err := s.db.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("iapages: reading the %s: %w", what, err)
	}
	defer rows.Close()
	out := []lendingRow{}
	for rows.Next() {
		r, err := scan(rows)
		if err != nil {
			return nil, fmt.Errorf("iapages: reading the %s: %w", what, err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

func (s *Service) useTab(ctx context.Context, scope string, base []any, money bool) (lendingTab, error) {
	args := append(append([]any{}, base...), rules.Lending.UseReported)
	rows, err := s.collect(ctx, "loan use", `
		SELECT x.id, sc.name, m.name, pu.label, x.planned_amount::text, x.reported_amount::text,
		       COALESCE(x.intended_output, ''), x.updated_at
		FROM bt_loan_purpose_allocation x
		JOIN bt_mfi_loan l ON l.id = x.loan_id JOIN school sc ON sc.id = l.school_id
		JOIN bt_mfi_organization m ON m.id = l.mfi_id JOIN bt_loan_purpose pu ON pu.id = x.purpose_id
		WHERE x.status = $`+strconv.Itoa(len(args))+` AND x.loan_id IN `+fmt.Sprintf(inScope, scope)+`
		ORDER BY x.updated_at`, args, func(r pgx.Rows) (lendingRow, error) {
		var id, output string
		var school, mfi, purpose, planned, reported *string
		var at time.Time
		if err := r.Scan(&id, &school, &mfi, &purpose, &planned, &reported, &output, &at); err != nil {
			return lendingRow{}, err
		}
		plannedText, reportedText := cellText(planned), cellText(reported)
		if !money {
			plannedText, reportedText = "Withheld", "Withheld"
		}
		if o := []rune(output); len(o) > 80 {
			output = string(o[:80])
		}
		return lendingRow{cells: []string{cellText(school), cellText(mfi), cellText(purpose), plannedText, reportedText,
			plainCell(output), lendingDay(at)}, action: LendingPath + "use/" + id + "/"}, nil
	})
	return lendingTab{
		description: "Loan money the lending partner reports as used for its purpose. Verify the amount the evidence supports, or return it.",
		title:       "Loan use to verify", emptyTitle: "No reported loan use waiting",
		emptyBody: "Reported purpose use appears here until Impact Assessment verifies it.",
		headings:  []string{"School", "Lending partner", "Purpose", "Planned", "Reported use", "Intended output", "Reported"},
		rows:      rows,
	}, err
}

func (s *Service) enrolmentTab(ctx context.Context, scope string, base []any) (lendingTab, error) {
	args := append(append([]any{}, base...), rules.Lending.EvidenceReported)
	rows, err := s.collect(ctx, "enrolment snapshots", `
		SELECT x.id, sc.name, m.name, COALESCE(x.kind, ''), x.as_of_date, x.learner_count, sc.enrollment, COALESCE(x.evidence_reference, '')
		FROM bt_enrolment_snapshot x
		JOIN bt_mfi_loan l ON l.id = x.loan_id JOIN school sc ON sc.id = l.school_id JOIN bt_mfi_organization m ON m.id = l.mfi_id
		WHERE x.status = $`+strconv.Itoa(len(args))+` AND x.loan_id IN `+fmt.Sprintf(inScope, scope)+`
		ORDER BY x.as_of_date`, args, func(r pgx.Rows) (lendingRow, error) {
		var id, kind, evidence string
		var school, mfi *string
		var asOf time.Time
		var learners, record *int64
		if err := r.Scan(&id, &school, &mfi, &kind, &asOf, &learners, &record, &evidence); err != nil {
			return lendingRow{}, err
		}
		label, ok := rules.Lending.SnapshotKinds[kind]
		if !ok {
			label = kind
		}
		return lendingRow{cells: []string{cellText(school), cellText(mfi), plainCell(label), lendingDay(asOf),
			numberCell(learners), numberCell(record), plainCell(evidence)}, action: LendingPath + "enrolment/" + id + "/"}, nil
	})
	return lendingTab{
		description: "Learner counts reported before and after financing. Check the register against the school's record before verifying.",
		title:       "Enrolment snapshots to verify", emptyTitle: "No reported enrolment waiting",
		emptyBody: "Baseline and follow-up enrolment appear here until verified.",
		headings:  []string{"School", "Lending partner", "Snapshot", "As of", "Learners", "School record", "Evidence"},
		rows:      rows,
	}, err
}

func (s *Service) outputTab(ctx context.Context, scope string, base []any) (lendingTab, error) {
	args := append(append([]any{}, base...), rules.Lending.EvidenceReported)
	rows, err := s.collect(ctx, "purpose outputs", `
		SELECT x.id, sc.name, pu.label, COALESCE(x.asset_type, ''), x.planned_quantity, x.reported_quantity,
		       x.reported_operational_quantity, COALESCE(x.evidence_reference, '')
		FROM bt_purpose_asset_output x
		JOIN bt_loan_purpose_allocation pa ON pa.id = x.allocation_id JOIN bt_loan_purpose pu ON pu.id = pa.purpose_id
		JOIN bt_mfi_loan l ON l.id = pa.loan_id JOIN school sc ON sc.id = l.school_id
		WHERE x.status = $`+strconv.Itoa(len(args))+` AND pa.loan_id IN `+fmt.Sprintf(inScope, scope)+`
		ORDER BY x.updated_at`, args, func(r pgx.Rows) (lendingRow, error) {
		var id, asset, evidence string
		var school, purpose *string
		var planned, reported, operational *int64
		if err := r.Scan(&id, &school, &purpose, &asset, &planned, &reported, &operational, &evidence); err != nil {
			return lendingRow{}, err
		}
		return lendingRow{cells: []string{cellText(school), cellText(purpose), plainCell(pyCapitalize(strings.ReplaceAll(asset, "_", " "))),
			numberCell(planned), numberCell(reported), numberCell(operational), plainCell(evidence)}, action: LendingPath + "outputs/" + id + "/"}, nil
	})
	return lendingTab{
		description: "What the loan bought or built: classrooms, computers, land. Verify what exists and works.",
		title:       "Purpose outputs to verify", emptyTitle: "No reported outputs waiting",
		emptyBody: "Reported purpose outputs appear here until verified.",
		headings:  []string{"School", "Purpose", "Output", "Planned", "Reported", "Operational", "Evidence"},
		rows:      rows,
	}, err
}

func (s *Service) teacherTab(ctx context.Context, scope string, base []any) (lendingTab, error) {
	args := append(append([]any{}, base...), rules.Lending.EvidenceReported)
	rows, err := s.collect(ctx, "teacher completions", `
		SELECT x.id, sc.name, COALESCE(x.anonymized_reference, ''), COALESCE(x.programme, ''), COALESCE(x.institution, ''),
		       x.completed_on, COALESCE(x.evidence_reference, '')
		FROM bt_teacher_degree_beneficiary x
		JOIN bt_mfi_loan l ON l.id = x.loan_id JOIN school sc ON sc.id = l.school_id
		WHERE x.status = $`+strconv.Itoa(len(args))+` AND x.completed_on IS NOT NULL AND x.loan_id IN `+fmt.Sprintf(inScope, scope)+`
		ORDER BY x.completed_on`, args, func(r pgx.Rows) (lendingRow, error) {
		var id, ref, programme, institution, evidence string
		var school *string
		var completed time.Time
		if err := r.Scan(&id, &school, &ref, &programme, &institution, &completed, &evidence); err != nil {
			return lendingRow{}, err
		}
		return lendingRow{cells: []string{cellText(school), plainCell(ref), programme + " · " + institution,
			lendingDay(completed), plainCell(evidence)}, action: LendingPath + "teachers/" + id + "/"}, nil
	})
	return lendingTab{
		description: "Teachers whose degree upgrade a loan financed and who are reported as completed.",
		title:       "Teacher completions to verify", emptyTitle: "No reported completions waiting",
		emptyBody: "Reported teacher completions appear here until verified.",
		headings:  []string{"School", "Teacher reference", "Programme", "Completed", "Evidence"},
		rows:      rows,
	}, err
}

func (s *Service) conclusionTab(ctx context.Context, scope string, base []any, state string, today time.Time) (lendingTab, error) {
	if _, ok := rules.Lending.StateLabels[state]; !ok {
		state = ""
	}
	args := append([]any{}, base...)
	arg := func(v any) string { args = append(args, v); return "$" + strconv.Itoa(len(args)) }
	un := unprepared(&args)
	var where string
	switch state {
	case stateToPrepare:
		where = "a.due_date <= " + arg(today) + " AND a.ia_status = " + arg(rules.Lending.IAPending) + " AND " + un
	case stateAwaiting:
		where = "a.ia_status = " + arg(rules.Lending.IAPending) + " AND NOT " + un
	case stateReturned:
		where = "a.ia_status = " + arg(rules.Lending.IAReturned)
	case stateVerified:
		where = "a.ia_status = " + arg(rules.Lending.IAVerified)
	default:
		where = "(a.due_date <= " + arg(today) + " OR NOT " + un + ")"
	}
	rows, err := s.collect(ctx, "conclusions", `
		SELECT a.id, sc.name, m.name, pu.label, a.due_date, COALESCE(a.classification, ''), COALESCE(a.ia_status, ''),
		       `+un+`, COALESCE(a.ia_note, '')
		FROM bt_loan_impact_assessment a
		JOIN bt_mfi_loan l ON l.id = a.loan_id JOIN school sc ON sc.id = l.school_id JOIN bt_mfi_organization m ON m.id = l.mfi_id
		LEFT JOIN bt_loan_purpose pu ON pu.id = l.purpose_id
		WHERE `+where+` AND a.loan_id IN `+fmt.Sprintf(inScope, scope)+`
		ORDER BY a.due_date, a.created_at`, args, func(r pgx.Rows) (lendingRow, error) {
		var id, classification, ia, note string
		var school, mfi, purpose *string
		var due time.Time
		var notPrepared bool
		if err := r.Scan(&id, &school, &mfi, &purpose, &due, &classification, &ia, &notPrepared, &note); err != nil {
			return lendingRow{}, err
		}
		state := stateAwaiting
		switch {
		case ia == rules.Lending.IAVerified:
			state = stateVerified
		case ia == rules.Lending.IAReturned:
			state = stateReturned
		case notPrepared:
			state = stateToPrepare
		}
		shown := ""
		if state != stateToPrepare {
			shown = classification
			if l, ok := rules.Lending.ClassificationLabels[classification]; ok {
				shown = l
			}
		}
		stateText := rules.Lending.StateLabels[state]
		if state == stateReturned && note != "" {
			stateText += ": " + note
		}
		return lendingRow{cells: []string{cellText(school), cellText(mfi), cellText(purpose), lendingDay(due),
			plainCell(shown), stateText}, action: LendingPath + "conclusions/" + id + "/"}, nil
	})
	options := []*screensv1.PageFilterOption{{Value: "", Label: "Due or in progress"}}
	for _, k := range stateOrder {
		options = append(options, &screensv1.PageFilterOption{Value: k, Label: rules.Lending.StateLabels[k]})
	}
	return lendingTab{
		description: "Business Transformation prepares each due conclusion from verified evidence (Impact Assessment only where " +
			"the country has no BT officer); someone other than the preparer verifies it before the classification is published.",
		title: "Loan impact conclusions", emptyTitle: "No conclusions due",
		emptyBody: "Conclusions are scheduled from each loan's first disbursement.",
		headings:  []string{"School", "Lending partner", "Purpose", "Due", "Classification", "State"},
		rows:      rows,
		filter:    &screensv1.PageFilter{Name: "state", Value: state, Caption: "State", Options: options},
		hidden:    map[string]string{"tab": tabConclusions},
	}, err
}

// pyMedian is statistics.median.
func pyMedian(xs []float64) float64 {
	s := append([]float64{}, xs...)
	sort.Float64s(s)
	n := len(s)
	if n%2 == 1 {
		return s[n/2]
	}
	return (s[n/2-1] + s[n/2]) / 2
}

type cohort struct {
	year                                                  int
	purpose                                               string
	followUp                                              int
	loans, due, positive, neutral, negative, insufficient int
	schools                                               map[string]bool
	days, changes                                         []float64
}

type firstDisbursement struct {
	school, purpose, label string
	followUp               int
	on                     time.Time
}

// firstDisbursements is each loan's first disbursement not reversed, in the
// order they were made.
func (s *Service) firstDisbursements(ctx context.Context, scope string, base []any) (map[string]firstDisbursement, []string, error) {
	rows, err := s.db.Query(ctx, `
		SELECT d.loan_id, l.school_id, l.purpose_id, pu.label, pu.follow_up_days, d.disbursed_on
		FROM bt_loan_disbursement d JOIN bt_mfi_loan l ON l.id = d.loan_id LEFT JOIN bt_loan_purpose pu ON pu.id = l.purpose_id
		WHERE d.loan_id IN `+fmt.Sprintf(inScope, scope)+`
		  AND NOT EXISTS (SELECT 1 FROM bt_loan_disbursement_reversal r WHERE r.disbursement_id = d.id)
		ORDER BY d.disbursed_on`, base...)
	if err != nil {
		return nil, nil, fmt.Errorf("iapages: reading the disbursements: %w", err)
	}
	defer rows.Close()
	firsts, order := map[string]firstDisbursement{}, []string{}
	for rows.Next() {
		var loan string
		var school, purpose, label *string
		var followUp *int
		var on time.Time
		if err := rows.Scan(&loan, &school, &purpose, &label, &followUp, &on); err != nil {
			return nil, nil, fmt.Errorf("iapages: reading a disbursement: %w", err)
		}
		if _, seen := firsts[loan]; seen {
			continue
		}
		f := firstDisbursement{on: on, school: deref(school), purpose: deref(purpose), label: deref(label)}
		if followUp != nil {
			f.followUp = *followUp
		}
		firsts[loan] = f
		order = append(order, loan)
	}
	return firsts, order, rows.Err()
}

type cohortAssessment struct {
	due                time.Time
	ia, classification string
}

type enrolmentPair struct{ baseline, followUp *int64 }

func (s *Service) cohortEvidence(ctx context.Context, loans []string) (map[string][]cohortAssessment, map[string]*enrolmentPair, error) {
	assessments := map[string][]cohortAssessment{}
	ar, err := s.db.Query(ctx, `SELECT loan_id, due_date, COALESCE(ia_status, ''), COALESCE(classification, '')
		FROM bt_loan_impact_assessment WHERE loan_id = ANY($1)`, loans)
	if err != nil {
		return nil, nil, fmt.Errorf("iapages: reading the conclusions: %w", err)
	}
	for ar.Next() {
		var loan string
		var a cohortAssessment
		if err := ar.Scan(&loan, &a.due, &a.ia, &a.classification); err != nil {
			ar.Close()
			return nil, nil, fmt.Errorf("iapages: reading a conclusion: %w", err)
		}
		assessments[loan] = append(assessments[loan], a)
	}
	ar.Close()
	pairs := map[string]*enrolmentPair{}
	sr, err := s.db.Query(ctx, `SELECT loan_id, COALESCE(kind, ''), learner_count FROM bt_enrolment_snapshot
		WHERE loan_id = ANY($1) AND status = $2 ORDER BY as_of_date`, loans, rules.Lending.EvidenceVerified)
	if err != nil {
		return nil, nil, fmt.Errorf("iapages: reading the enrolment: %w", err)
	}
	defer sr.Close()
	for sr.Next() {
		var loan, kind string
		var count *int64
		if err := sr.Scan(&loan, &kind, &count); err != nil {
			return nil, nil, fmt.Errorf("iapages: reading a snapshot: %w", err)
		}
		pp := pairs[loan]
		if pp == nil {
			pp = &enrolmentPair{}
			pairs[loan] = pp
		}
		if kind == rules.Lending.BaselineKind {
			if pp.baseline == nil {
				pp.baseline = count
			}
		} else {
			pp.followUp = count
		}
	}
	return assessments, pairs, sr.Err()
}

// cohortTab is financed_cohorts: disbursement year × purpose.
func (s *Service) cohortTab(ctx context.Context, scope string, base []any, today time.Time) (lendingTab, error) {
	tab := lendingTab{
		description: rules.Lending.CohortCaveat, title: "Financed cohorts",
		emptyTitle: "No disbursed loans in your country", emptyBody: "Cohorts form from each loan's first confirmed disbursement.",
		headings: []string{"Cohort", "Loans · schools", "Running", "Conclusions due",
			"Verified: positive / no change / negative / insufficient", "Verified enrolment change", "Evidence"},
		rows: []lendingRow{},
	}
	firsts, order, err := s.firstDisbursements(ctx, scope, base)
	if err != nil || len(firsts) == 0 {
		return tab, err
	}
	assessments, pairs, err := s.cohortEvidence(ctx, order)
	if err != nil {
		return tab, err
	}
	cohorts := map[string]*cohort{}
	for _, loan := range order {
		f := firsts[loan]
		key := strconv.Itoa(f.on.Year()) + "\x00" + f.purpose
		c := cohorts[key]
		if c == nil {
			label := f.label
			if label == "" {
				label = "No purpose recorded"
			}
			c = &cohort{year: f.on.Year(), purpose: label, followUp: f.followUp, schools: map[string]bool{}}
			cohorts[key] = c
		}
		c.loans++
		c.schools[f.school] = true
		c.days = append(c.days, float64(int(today.Sub(f.on).Hours()/24)))
		for _, a := range assessments[loan] {
			if !a.due.After(today) {
				c.due++
			}
			if a.ia != rules.Lending.IAVerified {
				continue
			}
			switch {
			case slices.Contains(rules.Lending.Positive, a.classification):
				c.positive++
			case slices.Contains(rules.Lending.Neutral, a.classification):
				c.neutral++
			case a.classification == rules.Lending.Negative:
				c.negative++
			default:
				c.insufficient++
			}
		}
		if pp := pairs[loan]; pp != nil && pp.baseline != nil && *pp.baseline != 0 && pp.followUp != nil {
			c.changes = append(c.changes, float64(*pp.followUp-*pp.baseline)/float64(*pp.baseline)*100)
		}
	}
	list := make([]*cohort, 0, len(cohorts))
	for _, c := range cohorts {
		list = append(list, c)
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].year != list[j].year {
			return list[i].year > list[j].year
		}
		return list[i].purpose < list[j].purpose
	})
	for _, c := range list {
		tab.rows = append(tab.rows, lendingRow{cells: c.cells()})
	}
	return tab, nil
}

func (c *cohort) cells() []string {
	medianDays := int(pyMedian(c.days))
	immature := medianDays < c.followUp
	running := strconv.FormatFloat(float64(medianDays)/30.4, 'f', 1, 64) + " months"
	if immature {
		running += " (immature)"
	}
	change := fmt.Sprintf("n too small (%d)", len(c.changes))
	grade := rules.Lending.GradeLabels["insufficient"]
	if len(c.changes) >= rules.Lending.MinN {
		change = fmt.Sprintf("%+.1f%% (%d loans)", pyMedian(c.changes), len(c.changes))
		grade = rules.Lending.GradeLabels["descriptive"]
	}
	return []string{
		fmt.Sprintf("%d · %s", c.year, c.purpose),
		fmt.Sprintf("%d · %d", c.loans, len(c.schools)),
		running,
		strconv.Itoa(c.due),
		fmt.Sprintf("%d / %d / %d / %d", c.positive, c.neutral, c.negative, c.insufficient),
		change,
		grade,
	}
}

func lendingPage(role Role, active string, counts lendingCounts, t lendingTab) *screensv1.GetPageResponse {
	header := &screensv1.PageHeader{Eyebrow: "Analysis & learning", Title: "Lending Evidence",
		Description: "Verify what school loans were used for and what they produced, then publish loan impact conclusions " +
			"that someone other than their preparer has checked."}
	blocks := workspaceStrip(role)
	total := 0
	for _, n := range counts.evidence {
		total += n
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Strip{Strip: &screensv1.PageStrip{
		Title: "Lending evidence at a glance", Metrics: []*screensv1.PageMetric{
			{Label: "Lending Evidence Awaiting IA Verification", Value: strconv.Itoa(total), Note: "loan use, enrolment, outputs and teacher completion"},
			{Label: "Loan Impact Conclusions to Prepare", Value: strconv.Itoa(counts.toPrepare), Note: "due, not yet prepared"},
			{Label: "Loan Impact Conclusions Awaiting Verification", Value: strconv.Itoa(counts.awaiting), Note: "verified by someone other than the preparer"},
			{Label: "Loan Impact Conclusions Returned", Value: strconv.Itoa(counts.returned), Note: "waiting for the preparer"},
		}}}})
	tabs := &screensv1.PageLinkTabs{Scrolls: true}
	for _, tb := range rules.Lending.Tabs {
		label := tb[1]
		if n := counts.evidence[tb[0]]; n > 0 {
			label += fmt.Sprintf(" (%d)", n)
		}
		tabs.Tabs = append(tabs.Tabs, &screensv1.PageLinkTab{Label: label, Href: LendingPath + "?" + url.Values{"tab": {tb[0]}}.Encode(),
			Active: tb[0] == active})
	}
	blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_LinkTabs{LinkTabs: tabs}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Items: []*screensv1.PagePanelItem{
			{Kind: &screensv1.PagePanelItem_Text{Text: t.description}}}}}})
	if t.filter != nil {
		blocks = append(blocks, &screensv1.PageBlock{Kind: &screensv1.PageBlock_Filters{Filters: &screensv1.PageFilters{
			Filters: []*screensv1.PageFilter{t.filter}, Hidden: t.hidden}}})
	}
	blocks = append(blocks,
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Panel{Panel: &screensv1.PagePanel{Title: t.title}}},
		&screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: t.table(active)}})
	return &screensv1.GetPageResponse{Header: header, Blocks: blocks, WebPath: LendingPath}
}

// table is partials/ia/evidence_table.html as the feed reads it: a cell's
// tone is data-tone, which the feed does not read.
func (t lendingTab) table(active string) *screensv1.PageTable {
	table := &screensv1.PageTable{}
	if len(t.rows) == 0 {
		table.EmptyMessage = t.emptyTitle
		table.Rows = []*screensv1.PageRow{{Cells: []*screensv1.PageCell{{Text: t.emptyTitle + " " + t.emptyBody}}}}
		return table
	}
	actions := false
	for _, r := range t.rows {
		actions = actions || r.action != ""
	}
	for _, h := range t.headings {
		table.Columns = append(table.Columns, &screensv1.PageColumn{Label: h})
	}
	if actions {
		table.Columns = append(table.Columns, &screensv1.PageColumn{})
	}
	label := "Verify"
	if active == tabConclusions {
		label = "Open"
	}
	for _, r := range t.rows {
		row := &screensv1.PageRow{}
		for _, c := range r.cells {
			row.Cells = append(row.Cells, &screensv1.PageCell{Text: c})
		}
		if actions {
			row.Cells = append(row.Cells, &screensv1.PageCell{Actions: []*screensv1.PageAction{{Key: "button", Label: label,
				Primary: true, Enabled: true, Href: r.action, Drawer: true}}})
		}
		table.Rows = append(table.Rows, row)
	}
	return table
}

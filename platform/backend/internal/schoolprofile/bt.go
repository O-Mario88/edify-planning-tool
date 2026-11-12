package schoolprofile

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/url"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/auth"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// A school's Business Transformation (business_transformation.services.
// school_profile_context, drawn by partials/schools/business_transformation.html)
// and the Overview's loans strip (profile_intelligence.finance), each as far
// as the reader may read the case register and the loan register.

// btReader is what deciding what a reader may read of the registers needs.
type btReader struct {
	p     auth.Principal
	scope schooldirectory.Scope
	doors doors
}

func (r btReader) role() string { return r.p.ActiveRole }

// mayReadCases is scoped_cases at one school.
func (r btReader) mayReadCases(sc school) bool {
	bt := rules.BT
	switch {
	case slices.Contains(bt.UgandaWideRoles, r.role()):
		return true
	case slices.Contains(bt.MFIRoles, r.role()):
		return false
	}
	return slices.Contains(r.scope.SchoolIDs, sc.ID)
}

// mayReadLoans is scoped_loans at one school: the programme's wide roles and
// an officer, over the schools scoped_school_queryset gives them.
func (s *Service) mayReadLoans(ctx context.Context, r btReader, sc school) (bool, error) {
	if !slices.Contains(rules.BT.UgandaWideRoles, r.role()) && r.role() != "CCEO" {
		return false, nil
	}
	sq := r.scope
	switch {
	case sq.CountryScope:
		if sq.Country == "" {
			return true, nil
		}
		return s.schoolInCountry(ctx, sc, sq.Country)
	case sq.RegionScope:
		return false, nil
	case sq.SummaryOnly:
		return true, nil
	}
	return slices.Contains(sq.SchoolIDs, sc.ID), nil
}

// mayReadImpactLoans is lending_impact.scoped_impact_loans at one school.
func (s *Service) mayReadImpactLoans(ctx context.Context, r btReader, sc school) (bool, error) {
	bt := rules.BT
	role := r.role()
	switch {
	case slices.Contains(bt.MFIRoles, role):
		return false, nil
	case slices.Contains(bt.ImpactCountryBoundRoles, role):
		if !r.scope.CountryScope || r.scope.Country == "" {
			return true, nil
		}
		var same bool
		err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM school s JOIN region r ON r.id = s.region_id WHERE s.id = $1 AND r.country = $2)`,
			sc.ID, r.scope.Country).Scan(&same)
		if err != nil {
			return false, fmt.Errorf("schoolprofile: reading the school's country: %w", err)
		}
		return same, nil
	case slices.Contains(bt.ImpactCountryRoles, role):
		return true, nil
	case role == "CCEO" || role == "Program Lead":
		return slices.Contains(r.scope.SchoolIDs, sc.ID), nil
	}
	return false, nil
}

// schoolInCountry is scoping.school_in_country_q for one school: placed by
// its region, or, unplaced, by its owner.
func (s *Service) schoolInCountry(ctx context.Context, sc school, country string) (bool, error) {
	var in bool
	err := s.db.QueryRow(ctx, `
SELECT EXISTS (SELECT 1 FROM school s WHERE s.id = $1 AND (
  EXISTS (SELECT 1 FROM region r WHERE r.id = s.region_id AND r.country = $2)
  OR (s.region_id IS NULL AND (
    s.account_owner_id IN (SELECT id FROM staff_profile WHERE country = $2 AND deleted_at IS NULL)
    OR s.account_owner_id IS NULL OR s.account_owner_id = ''
    OR s.account_owner_id IN (SELECT id FROM staff_profile WHERE (country IS NULL OR country = '') AND deleted_at IS NULL)))))`,
		sc.ID, country).Scan(&in)
	if err != nil {
		return false, fmt.Errorf("schoolprofile: reading the school's country: %w", err)
	}
	return in, nil
}

type btCase struct {
	id, status string
}

type btLoan struct {
	purpose, mfi, status, salesforce, impact string
	edtech                                   bool
	repayment                                *string
	requirement                              *string
	due                                      *time.Time
	reference, currency                      string
	disbursed, outstanding                   *float64
	term                                     *int32
}

// businessTransformation is the panel: the open case's status, the verified
// SSA signals, the case's response, the loans the reader may read (their
// figures only for a reader of the register's sensitive view), and the
// practice and compliance assessments.
func (s *Service) businessTransformation(ctx context.Context, r btReader, sc school) (*screensv1.PagePanel, error) {
	bt := rules.BT
	signals, err := s.ssaSignals(ctx, sc)
	if err != nil {
		return nil, err
	}
	active, err := s.activeCase(ctx, r, sc)
	if err != nil {
		return nil, err
	}
	loans, err := s.btLoans(ctx, r, sc)
	if err != nil {
		return nil, err
	}

	items := []*screensv1.PagePanelItem{}
	if active != nil {
		items = append(items, text(label(bt.CaseStatuses, active.status)))
	}
	if len(signals) > 0 {
		items = append(items, heading("Verified SSA signals"),
			&screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Rows{Rows: &screensv1.PageDataRows{Rows: signals[:min(4, len(signals))]}}})
	}
	if active != nil {
		response, err := s.caseResponse(ctx, active.id)
		if err != nil {
			return nil, err
		}
		items = append(items, heading("Current response"))
		items = append(items, response...)
	}
	switch {
	case len(loans) > 0:
		items = append(items, heading("Finance portfolio"))
		if !r.doors.BTSensitive {
			items = append(items, text("Summary view"))
		}
		for _, l := range loans {
			items = append(items, l.lines(r.doors, sc)...)
		}
	case active == nil:
		items = append(items, text("No active Business Transformation case or Edify-linked MFI loan is recorded for this school."))
	}
	practices, err := s.btPractices(ctx, sc)
	if err != nil {
		return nil, err
	}
	items = append(items, heading("Business Accounting & Finance"))
	items = append(items, practices...)
	compliance, err := s.btCompliance(ctx, sc)
	if err != nil {
		return nil, err
	}
	items = append(items, heading("Government Requirements"))
	items = append(items, compliance...)
	return &screensv1.PagePanel{
		Title:    "Business Transformation",
		Subtitle: "Uganda financial-health, compliance, and responsible-finance journey.",
		Badges:   []*screensv1.PageBadge{},
		Items:    pairedItems(items),
	}, nil
}

// activeCase is the first open case of the five newest the reader may read.
func (s *Service) activeCase(ctx context.Context, r btReader, sc school) (*btCase, error) {
	if !r.mayReadCases(sc) {
		return nil, nil
	}
	rows, err := s.db.Query(ctx, `
SELECT id, COALESCE(status, '') FROM bt_case WHERE school_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC LIMIT 5`, sc.ID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading cases: %w", err)
	}
	cases, err := pgx.CollectRows(rows, func(row pgx.CollectableRow) (btCase, error) {
		var c btCase
		return c, row.Scan(&c.id, &c.status)
	})
	if err != nil {
		return nil, err
	}
	for i := range cases {
		if slices.Contains(rules.BT.OpenCaseStatuses, cases[i].status) {
			return &cases[i], nil
		}
	}
	return nil, nil
}

// caseResponse is the open case's recommendations by kind, or that it
// awaits triage.
func (s *Service) caseResponse(ctx context.Context, caseID string) ([]*screensv1.PagePanelItem, error) {
	rows, err := s.db.Query(ctx, `SELECT COALESCE(kind, '') FROM bt_case_recommendation WHERE case_id = $1 ORDER BY created_at`, caseID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading the case's response: %w", err)
	}
	kinds, err := pgx.CollectRows(rows, pgx.RowTo[string])
	if err != nil {
		return nil, err
	}
	items := []*screensv1.PagePanelItem{}
	for _, k := range kinds {
		items = append(items, text(label(rules.BT.RecommendationKinds, k)))
	}
	if len(items) == 0 {
		items = append(items, text("Awaiting triage."))
	}
	return items, nil
}

// ssaSignals are school_profile_context's score rows, in its own query and
// order.
func (s *Service) ssaSignals(ctx context.Context, sc school) ([]*screensv1.PageDataRow, error) {
	rows, err := s.db.Query(ctx, `
SELECT ssa_score.intervention, ssa_score.score, ssa_record.fy, ssa_record.date_of_ssa
FROM ssa_score INNER JOIN ssa_record ON (ssa_score.ssa_record_id = ssa_record.id)
WHERE (ssa_score.intervention IN ('financial_health', 'government_requirement') AND ssa_record.deleted_at IS NULL
  AND ssa_record.school_id = $1 AND ssa_record.verification_status = 'confirmed')
ORDER BY ssa_record.date_of_ssa DESC LIMIT 12`, sc.ID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading SSA signals: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (*screensv1.PageDataRow, error) {
		var intervention, fy string
		var score float64
		var held time.Time
		if err := row.Scan(&intervention, &score, &fy, &held); err != nil {
			return nil, err
		}
		band, tone := schooldirectory.SSABand(score)
		return &screensv1.PageDataRow{
			Label: label(rules.SSAInterventions, intervention),
			Meta:  "FY" + fy + " · " + localJMY(held) + " · " + band,
			Value: floatformat(score, 1),
			Tone:  tone,
		}, nil
	})
}

// btLoans are the school's loans the reader may read: the register's own
// for a reader of its sensitive view, else its impact projection (a loan
// with a disbursement standing), at most twenty.
func (s *Service) btLoans(ctx context.Context, r btReader, sc school) ([]btLoan, error) {
	var may bool
	var err error
	impact := !r.doors.BTSensitive
	if impact {
		may, err = s.mayReadImpactLoans(ctx, r, sc)
	} else {
		may, err = s.mayReadLoans(ctx, r, sc)
	}
	if err != nil || !may {
		return nil, err
	}
	standing := "true"
	if impact {
		standing = `EXISTS (SELECT 1 FROM bt_loan_disbursement d WHERE d.loan_id = l.id
  AND NOT EXISTS (SELECT 1 FROM bt_loan_disbursement_reversal v WHERE v.disbursement_id = d.id))`
	}
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(p.label, ''), COALESCE(p.is_edtech, false), COALESCE(m.name, ''), COALESCE(l.status, ''),
  COALESCE(l.salesforce_status, ''), COALESCE(l.impact_status, ''),
  (SELECT r.status FROM bt_repayment_snapshot r WHERE r.loan_id = l.id ORDER BY r.as_of_date DESC, r.created_at DESC LIMIT 1),
  (SELECT r.outstanding_amount::float8 FROM bt_repayment_snapshot r WHERE r.loan_id = l.id ORDER BY r.as_of_date DESC, r.created_at DESC LIMIT 1),
  q.status, q.due_date, COALESCE(l.external_loan_reference, ''), COALESCE(l.currency, ''), l.disbursed_amount::float8, l.term_months
FROM bt_mfi_loan l
LEFT JOIN bt_loan_purpose p ON p.id = l.purpose_id
LEFT JOIN bt_mfi_organization m ON m.id = l.mfi_id
LEFT JOIN LATERAL (SELECT status, due_date FROM bt_loan_verification_requirement WHERE loan_id = l.id ORDER BY due_date LIMIT 1) q ON true
WHERE l.school_id = $1 AND l.deleted_at IS NULL AND `+standing+`
ORDER BY l.disbursement_date DESC, l.created_at DESC LIMIT 20`, sc.ID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading loans: %w", err)
	}
	return pgx.CollectRows(rows, func(row pgx.CollectableRow) (btLoan, error) {
		var l btLoan
		err := row.Scan(&l.purpose, &l.edtech, &l.mfi, &l.status, &l.salesforce, &l.impact, &l.repayment, &l.outstanding,
			&l.requirement, &l.due, &l.reference, &l.currency, &l.disbursed, &l.term)
		return l, err
	})
}

// lines are one loan's lines as the page reader reads them.
func (l btLoan) lines(d doors, sc school) []*screensv1.PagePanelItem {
	bt := rules.BT
	head := l.purpose
	if l.edtech {
		head += " · EdTech"
	}
	repayment := "No update"
	if l.repayment != nil && *l.repayment != "" {
		repayment = *l.repayment
	}
	verification, code := "Not due", ""
	if l.requirement != nil {
		code = *l.requirement
		verification = label(bt.RequirementStatuses, code)
		if l.due != nil {
			verification += " · due " + jMY(*l.due)
		}
	}
	items := []*screensv1.PagePanelItem{
		text(collapse(head)),
		text(collapse(l.mfi + " · " + label(bt.LoanStatuses, l.status))),
		text(collapse("Salesforce: " + label(bt.SalesforceStatuses, l.salesforce) + " · Impact: " + label(bt.ImpactStatuses, l.impact))),
		text(collapse(djangoTitle(strings.ReplaceAll(repayment, "_", " ")))),
		text(collapse(verification)),
	}
	if d.BTManage && (code == "needs_scheduling" || code == "overdue") {
		items = append(items, &screensv1.PagePanelItem{Kind: &screensv1.PagePanelItem_Links{Links: &screensv1.PageLinks{Links: []*screensv1.PageLink{
			{Text: "Plan verification", Href: "/planning?q=" + strings.ReplaceAll(url.PathEscape(sc.Name), "%2F", "/")}}}}})
	}
	if d.BTSensitive {
		if ref := collapse(l.reference); ref != "" {
			items = append(items, text("Reference"), text(ref))
		}
		term := "—"
		if l.term != nil && *l.term != 0 {
			term = strconv.Itoa(int(*l.term)) + " months"
		}
		items = append(items,
			text("Disbursed"), text(collapse(l.currency+" "+wholeComma(l.disbursed))),
			text("Outstanding"), text(collapse(l.currency+" "+wholeComma(l.outstanding))),
			text("Term"), text(term))
	}
	return items
}

// wholeComma is the project's |intcomma (frontend_filters): a whole number
// with thousands separators, and 0 for nothing.
func wholeComma(v *float64) string {
	if v == nil {
		return "0"
	}
	return intcomma(int(math.Trunc(*v)))
}

// btPractices is the latest financial-practice adoption assessment of the
// school's cases.
func (s *Service) btPractices(ctx context.Context, sc school) ([]*screensv1.PagePanelItem, error) {
	var assessed time.Time
	var status string
	var practices []byte
	err := s.db.QueryRow(ctx, `
SELECT a.assessed_on, COALESCE(a.verification_status, ''), a.practices FROM bt_financial_practice_assessment a
JOIN bt_case c ON c.id = a.case_id WHERE c.school_id = $1 ORDER BY a.assessed_on DESC LIMIT 1`, sc.ID).Scan(&assessed, &status, &practices)
	if errors.Is(err, pgx.ErrNoRows) {
		return []*screensv1.PagePanelItem{text("No financial-practice adoption assessment recorded.")}, nil
	}
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading practice assessments: %w", err)
	}
	return []*screensv1.PagePanelItem{
		text("Latest practice assessment · " + jMY(assessed)),
		text(label(rules.BT.ValidationStatuses, status) + " · " + strconv.Itoa(jsonLength(practices)) + " practices recorded"),
	}, nil
}

// jsonLength is |length of a stored JSON value.
func jsonLength(raw []byte) int {
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		return 0
	}
	switch t := v.(type) {
	case map[string]any:
		return len(t)
	case []any:
		return len(t)
	case string:
		return len([]rune(t))
	}
	return 0
}

// btCompliance are the school's government-requirement assessments.
func (s *Service) btCompliance(ctx context.Context, sc school) ([]*screensv1.PagePanelItem, error) {
	rows, err := s.db.Query(ctx, `
SELECT COALESCE(q.label, ''), COALESCE(a.status, '') FROM bt_school_compliance_assessment a
JOIN bt_compliance_requirement q ON q.id = a.requirement_id JOIN bt_case c ON c.id = a.case_id
WHERE c.school_id = $1 ORDER BY q.label LIMIT 20`, sc.ID)
	if err != nil {
		return nil, fmt.Errorf("schoolprofile: reading compliance assessments: %w", err)
	}
	items := []*screensv1.PagePanelItem{}
	for rows.Next() {
		var requirement, status string
		if err := rows.Scan(&requirement, &status); err != nil {
			rows.Close()
			return nil, err
		}
		if requirement = collapse(requirement); requirement != "" {
			items = append(items, text(requirement))
		}
		if st := collapse(label(rules.BT.ComplianceStatuses, status)); st != "" {
			items = append(items, text(st))
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(items) == 0 {
		items = append(items, text("Not assessed. No negative compliance conclusion is inferred."))
	}
	return items, nil
}

// btFinance is profile_intelligence.finance for one school: the loans the
// reader may read in the loan register, and every case at the school.
type btFinance struct {
	loans, loanSchools, fundedSchools, edtech int
	disbursed                                 float64
	cases, openCases, caseSchools             int
}

func (s *Service) financeOf(ctx context.Context, r btReader, sc school) (btFinance, error) {
	var f btFinance
	may, err := s.mayReadLoans(ctx, r, sc)
	if err != nil {
		return f, err
	}
	if may {
		if err := s.db.QueryRow(ctx, `
SELECT COUNT(l.id), COUNT(DISTINCT l.school_id), COUNT(DISTINCT l.school_id) FILTER (WHERE l.status = ANY($2)),
  COALESCE(SUM(l.disbursed_amount) FILTER (WHERE l.status = ANY($2)), 0)::float8,
  COUNT(l.id) FILTER (WHERE COALESCE(p.is_edtech, false))
FROM bt_mfi_loan l LEFT JOIN bt_loan_purpose p ON p.id = l.purpose_id
WHERE l.school_id = $1 AND l.deleted_at IS NULL AND l.status IS DISTINCT FROM 'canceled'`,
			sc.ID, rules.BT.FundedLoanStatuses).Scan(&f.loans, &f.loanSchools, &f.fundedSchools, &f.disbursed, &f.edtech); err != nil {
			return f, fmt.Errorf("schoolprofile: reading the school's loans: %w", err)
		}
	}
	if err := s.db.QueryRow(ctx, `
SELECT COUNT(id), COUNT(id) FILTER (WHERE status = ANY($2)), COUNT(DISTINCT school_id)
FROM bt_case WHERE school_id = $1 AND deleted_at IS NULL`, sc.ID, rules.BT.OpenCaseStatuses).Scan(&f.cases, &f.openCases, &f.caseSchools); err != nil {
		return f, fmt.Errorf("schoolprofile: reading the school's cases: %w", err)
	}
	return f, nil
}

// strip is the Overview's "Loans And Business Transformation" strip; the
// disbursed sum is |floatformat:0 then the project's |intcomma.
func (f btFinance) strip(records string) *screensv1.PageBlock {
	whole, err := strconv.ParseFloat(floatformat(f.disbursed, 0), 64)
	if err != nil {
		whole = 0
	}
	return strip("Loans And Business Transformation",
		kpi{label: "School Loans", value: intcomma(f.loans), link: records + "loans",
			helper: intcomma(f.loanSchools) + " school" + plural(f.loanSchools) + " · " + intcomma(f.edtech) + " for EdTech"},
		kpi{label: "Schools Funded", value: intcomma(f.fundedSchools), link: records + "loans", helper: "with a loan disbursed, active or repaid"},
		kpi{label: "Disbursed", value: "UGX " + intcomma(int(math.Trunc(whole))), link: records + "loans"},
		kpi{label: "Business Transformation Cases", value: intcomma(f.openCases), link: records + "cases",
			helper: "open, of " + intcomma(f.cases) + " in " + intcomma(f.caseSchools) + " school" + plural(f.caseSchools)},
	)
}

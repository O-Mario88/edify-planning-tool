// Package budgetpage builds Budget (/budget) for the people whose budget is
// their own or their team's: the planned activities' cost lines for a month,
// a quarter or a year, grouped by activity and item, with each team
// member's total for a Program Lead's team (apps.frontend.views.budget_views
// .budget_view, apps.budget.services.budget_workspace and
// pages/budgets/monthly.html).
//
// For a country reader it also builds the country's Budget: the national
// ledger, the district filter, Finance Health, and for a month the monthly
// approval workflow and its reconciliation (country.go).
//
// It reads; it never writes. It hands on to the existing application: a
// reader with a section strip above the page, a reader outside the country
// roles whose scope is the country, a deployment of several countries, any
// query but the year, the date, the period,
// the scope and the groups' page, a date or year that is not plainly one,
// more groups than one page holds, and a day rate that is not a whole
// number.
//
// The roles, names and sets are exported to rules.json by `manage.py
// export_budget_rules`; apps/budget/test_budget_rules_export.py fails when
// the two differ.
package budgetpage

import (
	_ "embed"
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode"
)

//go:embed rules.json
var rulesJSON []byte

type role struct {
	Page   bool `json:"page"`
	Export bool `json:"export"`
	// DataExport is budget_export_view's can_export (data.export).
	DataExport bool `json:"data_export"`
	Strip      bool `json:"strip"`
	Country    bool `json:"country"`
}

var rules = func() (r struct {
	Roles                  map[string]role   `json:"roles"`
	RoleLabels             map[string]string `json:"role_labels"`
	NonFundableStatuses    []string          `json:"non_fundable_statuses"`
	ActivityTypes          map[string]string `json:"activity_types"`
	ProgrammeActivityTypes map[string]string `json:"programme_activity_types"`
	TrainingTypes          []string          `json:"training_types"`
	MeetingTypes           []string          `json:"meeting_types"`
	ParticipantLineTypes   []string          `json:"participant_line_types"`
	ParticipantSettingKeys []string          `json:"participant_setting_keys"`
	DayRateKeys            []string          `json:"day_rate_keys"`
	Country                countryRules      `json:"country"`
	// ExportBook is the Budget workbook's other sheets' headings and words.
	ExportBook struct {
		ActivityHeaders  []string          `json:"activity_headers"`
		LineHeaders      []string          `json:"line_headers"`
		SummaryHeaders   []string          `json:"summary_headers"`
		Money            string            `json:"money"`
		StatusLabels     map[string]string `json:"status_labels"`
		KindLabels       map[string]string `json:"kind_labels"`
		PlanStatusLabels map[string]string `json:"plan_status_labels"`
		SchoolLists      []string          `json:"school_lists"`
	} `json:"export_book"`
	// CostPlanSheet is cost_plan_sheet's title, caption, money format, empty
	// line and each table kind's headings.
	CostPlanSheet struct {
		Title   string              `json:"title"`
		Caption string              `json:"caption"`
		Money   string              `json:"money"`
		Empty   string              `json:"empty"`
		Headers map[string][]string `json:"headers"`
	} `json:"cost_plan_sheet"`
	// CountryLedgerRoles read the country's ledger whatever their scope.
	CountryLedgerRoles []string `json:"country_ledger_roles"`
	// FundAllocationRoles open the Consolidated Fund Allocation.
	FundAllocationRoles []string `json:"fund_allocation_roles"`
}) {
	if err := json.Unmarshal(rulesJSON, &r); err != nil {
		panic(fmt.Sprintf("budgetpage: rules.json: %v", err))
	}
	if len(r.Roles) == 0 || len(r.NonFundableStatuses) == 0 || len(r.FundAllocationRoles) == 0 {
		panic("budgetpage: rules.json lacks its roles or statuses")
	}
	return r
}()

// Path is the page.
const Path = "/budget"

// groupsPageSize is TABLE_PAGE_SIZE: the groups one page of the ledger holds.
const groupsPageSize = 50

func in(list []string, s string) bool {
	for _, x := range list {
		if x == s {
			return true
		}
	}
	return false
}

// label is a choice field's display: its label, or the value itself.
func label(choices map[string]string, value string) string {
	if l, ok := choices[value]; ok {
		return l
	}
	return value
}

// pyTitle is Python's str.title().
func pyTitle(s string) string {
	out := []rune{}
	previousCased := false
	for _, r := range s {
		switch {
		case unicode.IsLetter(r) && !previousCased:
			out = append(out, unicode.ToTitle(r))
		case unicode.IsLetter(r):
			out = append(out, unicode.ToLower(r))
		default:
			out = append(out, r)
		}
		previousCased = unicode.IsLetter(r)
	}
	return string(out)
}

// ugx is the template's ugx filter over a whole number of shillings.
func ugx(n int64) string { return inCurrency("UGX", n) }

// inCurrency is the ugx filter for any currency: its ISO code, then the
// whole amount with thousands separators (docs/migration/80, §18).
func inCurrency(code string, n int64) string {
	s := fmt.Sprint(n)
	sign := ""
	if strings.HasPrefix(s, "-") {
		sign, s = "-", s[1:]
	}
	for i := len(s) - 3; i > 0; i -= 3 {
		s = s[:i] + "," + s[i:]
	}
	return code + " " + sign + s
}

// activities is "activity" or "activities", as pluralize:'y,ies' writes it.
func activities(n int) string {
	if n == 1 {
		return fmt.Sprintf("%d activity", n)
	}
	return fmt.Sprintf("%d activities", n)
}

// ugxCompact is apps.core.metrics.format_ugx_compact: UGX 1.2M, UGX 850K,
// UGX 640, to Python's float formatting.
func ugxCompact(n int64) string { return compactIn("UGX", n) }

// compactIn is format_ugx_compact for any currency.
func compactIn(code string, n int64) string {
	sign := ""
	if n < 0 {
		sign, n = "-", -n
	}
	var text string
	switch {
	case n >= 1_000_000_000:
		text = code + " " + strconv.FormatFloat(float64(n)/1e9, 'f', 1, 64) + "B"
	case n >= 1_000_000:
		text = code + " " + strconv.FormatFloat(float64(n)/1e6, 'f', 1, 64) + "M"
	case n >= 1_000:
		text = code + " " + strconv.FormatFloat(float64(n)/1e3, 'f', 0, 64) + "K"
	default:
		text = inCurrency(code, n)
	}
	return sign + text
}

// pyPercentage is apps.core.metrics.percentage: round(a / b * 100), a half
// to the even whole number, computed in that order.
func pyPercentage(a, b int64) int64 {
	return int64(math.RoundToEven(float64(a) / float64(b) * 100))
}

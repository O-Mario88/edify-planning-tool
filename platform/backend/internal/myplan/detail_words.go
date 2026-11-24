package myplan

import (
	"fmt"
	"strconv"
	"strings"
	"time"
	"unicode"

	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/costing/daypool"
)

// The words of an activity's detail drawer (/my-plan/<id>): its title and
// dates as the template renders them, and how apps.budget.breakdown says
// each cost line was worked out.

// apMonths are Django's "N" month abbreviations (Associated Press style).
var apMonths = [...]string{"Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."}

// detailTitle is {{ act.activity_type|title|replace_underscore }}: Django's
// title filter (str.title, then a letter after a digit lower-cased), then
// the underscores read as spaces.
func detailTitle(kind string) string {
	var b strings.Builder
	prevCased, prevDigit := false, false
	for _, r := range kind {
		switch {
		case unicode.IsLetter(r) && (prevCased || prevDigit):
			b.WriteRune(unicode.ToLower(r))
		case unicode.IsLetter(r):
			b.WriteRune(unicode.ToUpper(r))
		default:
			b.WriteRune(r)
		}
		prevCased, prevDigit = unicode.IsLetter(r), unicode.IsDigit(r)
	}
	return strings.ReplaceAll(b.String(), "_", " ")
}

// plannedWords is {{ act.planned_date|default:"Unscheduled" }}: a date in
// Django's default DATE_FORMAT, "N j, Y".
func plannedWords(day *time.Time) string {
	if day == nil {
		return "Unscheduled"
	}
	return fmt.Sprintf("%s %d, %d", apMonths[day.Month()-1], day.Day(), day.Year())
}

// andJoined is breakdown._joined: "transport", "transport and lunch",
// "transport, lunch and dinner".
func andJoined(words []string) string {
	if len(words) <= 1 {
		return strings.Join(words, "")
	}
	return strings.Join(words[:len(words)-1], ", ") + " and " + words[len(words)-1]
}

// grouped is Python's f"{n:,}".
func grouped(n int64) string {
	return strings.TrimPrefix(money(n), "UGX ")
}

// dayBasis is how the breakdown works out a share of a day's transport or
// meals: the day's rate in full, or divided between count activities.
func dayBasis(rate int64, count int, unit string) string {
	if count > 1 {
		return strings.ReplaceAll(fmt.Sprintf("%s %s ÷ %d activities", money(rate), unit, count), "  ", " ")
	}
	return strings.TrimSpace(fmt.Sprintf("1 × %s %s", money(rate), unit))
}

// quantityBasis is a line priced as so many of a rate.
func quantityBasis(quantity, unit int64, unitLabel string) string {
	return strings.TrimSpace(fmt.Sprintf("%s × %s %s", grouped(quantity), money(unit), unitLabel))
}

// dayRate is breakdown._day_rate: the day's full rate behind one
// activity's share, the first candidate that, divided between count
// activities, gives amount.
func dayRate(amount int64, count int, index *int64, candidates []*int64) *int64 {
	for _, rate := range candidates {
		if rate == nil {
			continue
		}
		shares := daypool.AllocateComponent(*rate, count)
		if index != nil && *index >= 0 && int(*index) < count {
			if shares[*index] == amount {
				return rate
			}
			continue
		}
		for _, s := range shares {
			if s == amount {
				return rate
			}
		}
	}
	return nil
}

// dayWhen is f"{visit_date:%A} {visit_date.day} {visit_date:%B %Y}".
func dayWhen(day time.Time) string {
	return day.Weekday().String() + " " + strconv.Itoa(day.Day()) + " " + day.Month().String() + " " + strconv.Itoa(day.Year())
}

// daySentence is what the breakdown says about the day a staff member's
// transport and meals were priced for.
func daySentence(who string, day time.Time, count int, labels []string) string {
	if who == "" {
		who = "The responsible officer"
	}
	what := andJoined(labels)
	several := strings.Contains(what, " and ")
	if count > 1 {
		verb := "is"
		if several {
			verb = "are"
		}
		return fmt.Sprintf("%s has %d activities on %s, so the day's %s %s paid once and divided equally between them.", who, count, dayWhen(day), what, verb)
	}
	pronoun := "it"
	if several {
		pronoun = "them"
	}
	return fmt.Sprintf("This is the only activity %s has on %s, so it carries the day's %s in full. Another activity planned on the same day would share %s.", who, dayWhen(day), what, pronoun)
}

// lineMoney is what ActivityScheduleCostLine.finance_status reads of one
// line: its newest advance, the request its first weekly line is on, and
// the activity's own state.
type lineMoney struct {
	advance, netsuite, weekly      string
	status, lineType               string
	scheduled, deleted, partner    bool
	partnerAdvance, partnerCleared bool
	vendorTransport, transportPaid bool
	vendorPaid, costMissing        bool
	amount                         int64
}

var advanceWords = map[string]string{
	"confirmed_for_advance":             "Ready for Disbursement",
	"self_funded_pending_reimbursement": "Execution Pending",
	"accountability_pl_pending":         "Awaiting PL Approval",
	"reimbursement_pl_pending":          "Awaiting PL Approval",
	"reimbursement_submitted":           "Reimbursement Pending",
	"returned":                          "Returned",
	"cancelled":                         "Rejected",
	"not_requested":                     "Not Requested",
	"submitted_to_accountant":           "Submitted to Accountant",
	"accountability_pending":            "Accountability Pending",
	"reimbursement_disbursed":           "Reimbursement Disbursed",
	"reimbursed":                        "Reimbursed",
}

var weeklyWords = map[string]string{
	"pending_responsible_confirmation": "Included in Weekly Request",
	"submitted_to_pl":                  "Submitted for Approval",
	"submitted_to_cd":                  "Submitted for Approval",
	"confirmed_for_advance":            "Ready for Disbursement",
	"disbursed":                        "Disbursed",
	"returned_by_pl":                   "Returned",
	"returned_by_cd":                   "Returned",
	"returned_by_accountant":           "Returned",
	"self_funded":                      "Self-funded",
	"not_requested":                    "Not Requested",
}

// financeStatus is ActivityScheduleCostLine.finance_status. ok is kept
// for a line Go cannot word.
func financeStatus(m lineMoney) (string, bool) {
	switch m.advance {
	case "":
	case "accounted":
		if m.netsuite != "" {
			return "Cleared", true
		}
		return "NetSuite ID Required", true
	case "disbursed":
		if m.status == "ia_verified" {
			return "Accountability Pending", true
		}
		return "Disbursed", true
	default:
		if words, ok := advanceWords[m.advance]; ok {
			return words, true
		}
	}
	if words, ok := weeklyWords[m.weekly]; ok {
		return words, true
	}
	d := rules.Detail
	switch {
	case m.deleted || in(d.NonFundableStatuses, m.status):
		return "Not Funded: " + statusDisplay(m.status), true
	case !m.scheduled:
		return "Not Funded: Not Scheduled", true
	case m.partner && m.partnerCleared:
		return "Paid on Partner Invoice", true
	case m.partner && m.partnerAdvance:
		return "Partner Invoice: 50% Paid", true
	case m.partner:
		return "Partner Invoice: Not Yet Paid", true
	case m.vendorTransport && m.transportPaid:
		return "Paid to Transport Company", true
	case m.vendorTransport:
		return "Transport Company: Awaiting Payment", true
	case m.lineType == "accommodation" && m.vendorPaid:
		return "Hotel Booked by Finance", true
	case m.costMissing:
		return "Not Requested: Cost Setup Required", true
	case m.amount == 0:
		return "No Cost: Rate Not Set", true
	case m.status == "completed":
		return "Evidence Submitted", true
	case m.status == "ia_verified":
		return statusDisplay(m.status), true
	}
	return "Draft Costed", true
}

// statusDisplay is get_status_display(): the status's label, or the value
// itself when it is not one of the choices.
func statusDisplay(status string) string {
	if label, ok := rules.Detail.StatusLabels[status]; ok {
		return label
	}
	return status
}

// budgetBreakdown is apps.budget.breakdown.activity_budget_breakdown's answer.
type budgetBreakdown struct {
	rows                []budgetRow
	total, minimumTotal int64
	showMinimum         bool
	day                 string
	notes               []string
	missingNote         string
	source, workedOut   string
	emptyNote           string
}

type budgetRow struct {
	label, basis, status string
	amount, minimum      int64
}

// footnote is what the feed reads under the table: the first note of the
// card's footer (page_blocks._footnote), in the order
// partials/my_plan/budget_breakdown.html prints them.
func (b budgetBreakdown) footnote() string {
	notes := []string{b.missingNote, b.day}
	notes = append(notes, b.notes...)
	if b.showMinimum {
		notes = append(notes, "Minimum viable is the same items at the Country Director's minimum rates; funding is requested at the amounts in the Amount column.")
	}
	if b.source != "" {
		source := b.source
		if b.workedOut != "" {
			source += " Worked out on " + b.workedOut + "."
		}
		notes = append(notes, source)
	}
	for _, n := range notes {
		if n != "" {
			return n
		}
	}
	return ""
}

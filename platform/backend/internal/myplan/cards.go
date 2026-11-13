package myplan

import (
	"context"
	"fmt"
	"strings"
	"time"

	screensv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/screens/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/closedschools"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/schooldirectory"
)

// The attention cards (partials/my_plan/attention.html) after the day-off
// card: Returned — Needs Correction, Waiting on Approval and Finance /
// Accountability Pending, over compute_next_action and the loop's urgency
// sections.

// advance is one advance request as compute_next_action reads it.
type advance struct {
	status             string
	receiptConfirmed   bool
	accountabilityDone bool
}

// nextAction is compute_next_action's answer.
type nextAction struct {
	text, action, url, description string
}

// readAdvances is money_chain's advances_by_line, flattened per activity
// as _advances_of reads it: the cost lines in their order, each line's
// advances newest first (AdvanceRequest.Meta.ordering).
func readAdvances(ctx context.Context, db schooldirectory.Querier, lines costLines) (map[string][]advance, error) {
	var ids []string
	for _, ls := range lines {
		ids = append(ids, ls...)
	}
	out := map[string][]advance{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := db.Query(ctx, `SELECT budget_line_id, COALESCE(status, ''), reimbursement_receipt_confirmed_at IS NOT NULL,
  COALESCE(accountability_netsuite_id, '') <> ''
FROM advance_request WHERE budget_line_id IN (SELECT unnest($1::varchar[])) ORDER BY created_at DESC`, ids)
	if err != nil {
		return nil, fmt.Errorf("myplan: reading the rows' advances: %w", err)
	}
	defer rows.Close()
	byLine := map[string][]advance{}
	for rows.Next() {
		var line string
		var adv advance
		if err := rows.Scan(&line, &adv.status, &adv.receiptConfirmed, &adv.accountabilityDone); err != nil {
			return nil, fmt.Errorf("myplan: reading the rows' advances: %w", err)
		}
		byLine[line] = append(byLine[line], adv)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("myplan: reading the rows' advances: %w", err)
	}
	for activityID, ls := range lines {
		for _, l := range ls {
			out[activityID] = append(out[activityID], byLine[l]...)
		}
	}
	return out, nil
}

func sameDay(t *time.Time, day time.Time) bool {
	d := date(t)
	return d != nil && d.Equal(day)
}

// computeNextAction is compute_next_action for staff work (the staff plan
// lists no partner delivery; the caller passes a partner's work on). ok is
// false where the answer depends on which of two advances the table
// returns first.
func computeNextAction(a *activity, x *extra, advs []advance, today time.Time) (nextAction, bool) {
	t := rules.Tables
	id := a.id
	evidence := str(x.evidence)
	switch {
	case a.status == "awaiting_owner_approval":
		return nextAction{"Waiting for owner approval", "await_owner", "/planning/visit-requests",
			"The school's owner has been asked to approve this visit"}, true
	case in(rules.Plan.ReturnedStatuses, a.status):
		return nextAction{"Fix and Resubmit", "fix", "/activities/" + id + "/complete", "Returned for correction"}, true
	case in([]string{"scheduled", "rescheduled", "partner_scheduled"}, a.status) && sameDay(a.plannedDate, today):
		return nextAction{"Start", "start", "/activities/" + id + "/start", "Due today"}, true
	case a.status == "in_progress":
		return nextAction{"Complete Activity", "complete", "/activities/" + id + "/complete", "In Progress"}, true
	case evidence == "none" && in(t.WorkedStatuses, a.status) && a.status != "completed":
		return nextAction{"Complete Activity", "complete", "/activities/" + id + "/complete",
			"Enter the Salesforce ID to complete"}, true
	}
	formStep := evidence == "uploaded" || evidence == "none"
	if in(t.WorkedStatuses, a.status) && formStep {
		if !isSet(a.salesforce) {
			return nextAction{"Enter Activity SF ID", "sf_id", "/activities/" + id + "/salesforce-id", "Salesforce ID missing"}, true
		}
		done := true
		if in(t.SubmitNeedsParticipantsTypes, a.activityType) {
			attended := 0
			if a.teachersAttended != nil {
				attended += *a.teachersAttended
			}
			if a.leadersAttended != nil {
				attended += *a.leadersAttended
			}
			done = attended > 0
		}
		if done {
			return nextAction{"Submit", "submit", "/activities/" + id + "/submit", "Ready for PL/IA review"}, true
		}
	}
	if in(t.SSAUploadTypes, a.activityType) && a.hasSchool && str(x.schoolSSAStatus) != "done" {
		return nextAction{"Upload SSA", "ssa", "/activities/" + id + "/complete", "SSA expected but not uploaded"}, true
	}
	view := func(text, description string) (nextAction, bool) {
		return nextAction{text, "view_status", "/my-plan/" + id, description}, true
	}
	ia := str(a.iaVerification)
	payment := str(x.payment)
	switch {
	case a.status == "awaiting_ia_verification" && ia == "pending":
		return view("View Status", "Waiting for verification")
	case a.status == "ia_verified" && ia == "confirmed" && in([]string{"none", "pending_ia", "ia_confirmed"}, payment):
		return view("View Accounts Status", "Accounts clearance pending")
	}
	for _, adv := range advs {
		if adv.status == "reimbursement_disbursed" && !adv.receiptConfirmed {
			return nextAction{"Confirm Reimbursement Receipt", "reimbursement_receipt", "/my-plan/" + id + "/confirm-reimbursement-receipt",
				"Reimbursement sent — confirm you received it"}, true
		}
	}
	for _, adv := range advs {
		if adv.status == "disbursed" && !adv.accountabilityDone {
			return nextAction{"Submit Accountability", "accountability", "/my-plan/" + id + "/accountability",
				"Disbursed — submit spend, receipts & NetSuite Code"}, true
		}
	}
	for _, adv := range advs {
		if adv.status == "accountability_pending" {
			return view("Awaiting Finance Clearance", "Accountability submitted — Accountant review pending")
		}
	}
	// The last loop answers by whichever of its three states comes first.
	last := map[string]nextAction{
		"accountability_pl_pending": {"Awaiting PL Accountability Approval", "view_status", "/my-plan/" + id,
			"Accountability submitted — Programme Lead approval pending"},
		"reimbursement_pl_pending": {"Awaiting PL Claim Approval", "view_status", "/my-plan/" + id,
			"Self-funded claim submitted — Programme Lead approval pending"},
		"reimbursement_submitted": {"Awaiting Reimbursement", "view_status", "/my-plan/" + id,
			"Claim approved — Accountant reimbursement pending"},
	}
	var found *nextAction
	for _, adv := range advs {
		n, ok := last[adv.status]
		if !ok {
			continue
		}
		if found != nil && *found != n {
			return nextAction{}, false
		}
		found = &n
	}
	if found != nil {
		return *found, true
	}
	return nextAction{"View Details", "view", "/my-plan/" + id, "Scheduled / Waiting"}, true
}

// awaitsApproval is awaits_approval.
func awaitsApproval(a *activity, x *extra, next nextAction, advs []advance) bool {
	if in(rules.Tables.HandedInStatuses, a.status) {
		return true
	}
	if next.action != "view_status" {
		return false
	}
	if !in(rules.Rows.ApprovedStatuses, a.status) {
		return true
	}
	if str(x.payment) != "none" {
		return true
	}
	for _, adv := range advs {
		if in(rules.Tables.MoneyAwaitingStatuses, adv.status) {
			return true
		}
	}
	return false
}

// onWaitingCard is the loop's urgency sections up to Waiting on Approval:
// sent back, a partner's, waiting on the reader, due today and this week
// come first and keep a row off it.
func onWaitingCard(a *activity, x *extra, next nextAction, advs []advance, today time.Time) bool {
	t := rules.Tables
	open := in(t.DatedAndOpen, a.status)
	switch {
	case in(rules.Plan.ReturnedStatuses, a.status), str(a.delivery) == "partner",
		in(t.WaitingOnMeActions, next.action), sameDay(a.plannedDate, today) && open:
		return false
	}
	if d := date(a.plannedDate); d != nil && d.After(today) && !d.After(today.AddDate(0, 0, 7)) && open {
		return false
	}
	return awaitsApproval(a, x, next, advs)
}

// budgetBadge is the loop's budget badge for the row's budget status.
func budgetBadge(status string) (string, string) {
	switch status {
	case "Cost Setup Required", "In Weekly Request", "Awaiting PL Approval", "Awaiting CD Approval":
		return status, "amber"
	case "Request Returned":
		return status, "red"
	case "Approved":
		return "Approved — Ready for Disbursement", "green"
	case "Disbursed":
		return status, "green"
	case "No Budget":
		return status, "slate"
	}
	return status, "blue"
}

// badges is the loop's badge list after the status pill: budget, evidence,
// approval, accounts.
func badges(r *planRow) [][2]string {
	a := r.a
	label, tone := budgetBadge(r.budgetStatus)
	out := [][2]string{{label, tone}}
	if a.status == "completed" {
		if str(r.x.evidence) == "uploaded" {
			out = append(out, [2]string{"Evidence complete", "green"})
		} else {
			out = append(out, [2]string{"Evidence pending", "amber"})
		}
	}
	if in([]string{"pending", "confirmed", "returned"}, str(a.iaVerification)) {
		out = append(out, [2]string{r.verification, verificationColour(r.verification)})
	}
	switch str(r.x.payment) {
	case "pending", "pending_ia":
		out = append(out, [2]string{"Accounts pending", "amber"})
	case "cleared", "accountant_cleared":
		out = append(out, [2]string{"Accounts complete", "green"})
	case "disbursed", "netsuite_accountability":
		out = append(out, [2]string{"Accountability Pending", "amber"})
	case "paid":
		out = append(out, [2]string{"Paid", "green"})
	}
	return out
}

// cardPlace is the cards' School / Cluster cell; empty is cluster_link's
// word for no name.
func cardPlace(r *planRow, empty string) *screensv1.PageCell {
	place := &screensv1.PageCell{}
	switch {
	case r.schoolName != "" && r.schoolName != "Unknown School":
		place.Text = r.schoolName
		if r.schoolID.truthy() {
			place.Href = "/schools/" + r.schoolID.value
		}
	case r.clusterID != "":
		place.Text, place.Href = r.clusterName, "/clusters/"+r.clusterID
	default:
		place.Text = orDefault(r.clusterName, empty)
	}
	return place
}

// cardCode is the cards' School ID cell: {% school_code %} is a token span
// the feed reads as nothing.
func cardCode(r *planRow) *screensv1.PageCell {
	if r.schoolID.truthy() {
		return &screensv1.PageCell{}
	}
	return &screensv1.PageCell{Text: dash}
}

func cardTable(title string, labels []string, numericLast bool, rows []*screensv1.PageRow) *screensv1.PageBlock {
	cols := columns(labels...)
	for _, c := range cols {
		c.Numeric = false
	}
	cols[len(cols)-1].Numeric = numericLast
	return &screensv1.PageBlock{Kind: &screensv1.PageBlock_Table{Table: &screensv1.PageTable{Title: title, Columns: cols, Rows: rows}}}
}

// returnedCard is "Returned — Needs Correction".
func returnedCard(rows []*planRow) *screensv1.PageBlock {
	var out []*screensv1.PageRow
	for _, r := range rows {
		fix := &screensv1.PageAction{Key: "button", Label: "Fix Now", Primary: true, Enabled: true, Href: r.next.url, Drawer: true}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cardCode(r), cardPlace(r, ""), {Text: str(r.activityTypeLabel)},
			{Text: rules.Tables.ReturnedBy[r.a.status]}, {Text: `"` + r.returnReason() + `"`},
			{Actions: []*screensv1.PageAction{fix}},
		}})
	}
	return cardTable("Returned — Needs Correction", []string{"School ID", "School / Cluster", "Type", "Returned By", "Reason", "Action"}, true, out)
}

// returnReason is return_notes.note_for, "Correction required" with none.
func (r *planRow) returnReason() string {
	if note := strings.TrimSpace(str(r.x.reviewNote)); note != "" {
		return closedschools.PyCollapse(note)
	}
	return "Correction required"
}

// cardDay is the cards' date:"M j, D".
func cardDay(t *time.Time) string { return t.Format("Jan 2, Mon") }

// waitingCard is "Waiting on Approval".
func waitingCard(rows []*planRow) *screensv1.PageBlock {
	var out []*screensv1.PageRow
	for _, r := range rows {
		when := "Unscheduled"
		switch {
		case r.plannedBefore != nil:
			when = cardDay(r.plannedBefore)
		case r.a.plannedDate != nil:
			when = cardDay(date(r.a.plannedDate))
		}
		done := dash
		if r.completedOn != nil {
			done = cardDay(r.completedOn)
		}
		sf := "Not in SF"
		if r.salesforceID != "" {
			sf = r.salesforceID
		}
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cardCode(r), cardPlace(r, ""), {Text: str(r.activityTypeLabel)},
			{Text: when}, {Text: done}, {Text: sf}, r.badgeStrip(),
		}})
	}
	return cardTable("Waiting on Approval", []string{"School ID", "School / Cluster", "Type", "Planned Date", "Completed Date", "Salesforce ID", "Status"}, false, out)
}

// badgeStrip is row_badges.html as the feed reads it: one pill is a
// badge of its tone, several are their words, a space between.
func (r *planRow) badgeStrip() *screensv1.PageCell {
	var pills [][2]string
	if r.statusLabel != "" {
		pills = append(pills, [2]string{r.statusLabel, orDefault(r.tone, "slate")})
	}
	pills = append(pills, badges(r)...)
	if len(pills) == 1 {
		return badge(pills[0][0], pills[0][1])
	}
	words := make([]string, len(pills))
	for i, p := range pills {
		words[i] = p[0]
	}
	return &screensv1.PageCell{Text: strings.Join(words, " ")}
}

// financeCard is "Finance / Accountability Pending".
func financeCard(rows []*planRow) *screensv1.PageBlock {
	var out []*screensv1.PageRow
	for _, r := range rows {
		payment := orDefault(str(r.x.payment), "none")
		out = append(out, &screensv1.PageRow{Cells: []*screensv1.PageCell{
			cardCode(r), cardPlace(r, ""), {Text: str(r.activityTypeLabel)},
			badge(payment, "primary"),
			{Text: r.financeNext()},
		}})
	}
	return cardTable("Finance / Accountability Pending", []string{"School ID", "School / Cluster", "Type", "Payment Status", "Next Action"}, true, out)
}

// financeNext is the Finance card's Next Action cell as the feed reads it:
// the button's words (another delivery's "Monitoring — partner-owned") and
// the description under them.
func (r *planRow) financeNext() string {
	what := r.next.text
	if str(r.a.delivery) != "staff" {
		what = "Monitoring — partner-owned"
	}
	return closedschools.PyCollapse(what + " " + r.next.description)
}

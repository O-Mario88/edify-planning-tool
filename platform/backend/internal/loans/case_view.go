package loans

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	loansv1 "github.com/O-Mario88/edify-planning-tool/platform/backend/gen/edify/loans/v1"
	"github.com/O-Mario88/edify-planning-tool/platform/backend/internal/loans/ledger"
)

// The case page is built here, from the case's records and its ledger
// position: what this viewer may see, and what they may do now.

func line(label, value string) *loansv1.CaseLine {
	return &loansv1.CaseLine{Label: label, Value: value}
}

func toned(label, value, tone string) *loansv1.CaseLine {
	return &loansv1.CaseLine{Label: label, Value: value, Tone: tone}
}

func section(key, title, note string, lines ...*loansv1.CaseLine) *loansv1.CaseSection {
	return &loansv1.CaseSection{Key: key, Title: title, Note: note, Lines: lines}
}

func table(columns ...string) *loansv1.CaseTable { return &loansv1.CaseTable{Columns: columns} }

func addRow(t *loansv1.CaseTable, tone, documentID string, cells ...string) {
	t.Rows = append(t.Rows, &loansv1.CaseTableRow{Cells: cells, Tone: tone, DocumentId: documentID})
}

func ugx(m ledger.Money) string { return ledger.FormatUGX(m) }

func day(t time.Time) string { return t.Format("2 Jan 2006") }

func optionalDay(t *time.Time) string {
	if t == nil {
		return "—"
	}
	return day(*t)
}

func labelOf(options []Option, value string) string {
	for _, o := range options {
		if o.Value == value {
			return o.Label
		}
	}
	if value == "" {
		return "—"
	}
	return value
}

var assessmentStatusLabels = map[string]string{
	"not_started": "Not started", "in_progress": "In progress", "information_required": "Additional information required",
	"submitted": "Submitted for review", "returned": "Returned for revision", "completed": "Completed",
}

var evidenceStatusLabels = map[string]string{
	"verification_pending": "Verification pending", "verified": "Verified", "rejected": "Rejected",
}

var installmentLabels = map[string]string{
	ledger.InstallmentUpcoming: "Upcoming", ledger.InstallmentDue: "Due", ledger.InstallmentPartiallyPaid: "Partially paid",
	ledger.InstallmentPaid: "Paid", ledger.InstallmentOverdue: "Overdue",
}

var installmentTones = map[string]string{
	ledger.InstallmentPaid: "good", ledger.InstallmentDue: "info", ledger.InstallmentPartiallyPaid: "caution",
	ledger.InstallmentOverdue: "alert",
}

func servicingTone(status string) string {
	switch status {
	case ledger.StatusOverdue:
		return "alert"
	case ledger.StatusPaymentDue, ledger.StatusPartiallyPaid:
		return "caution"
	case ledger.StatusSettled:
		return "good"
	}
	return "info"
}

// amounts are the four amounts a loan carries, kept apart.
func (c *caseData) amounts() (recommended, approved, disbursed string) {
	recommended, approved, disbursed = "—", "—", "—"
	if r := c.record.LatestRecommendation(); r != nil {
		recommended = ugx(r.Amount)
	}
	if d := c.record.LatestDecision(); d != nil && d.ApprovedAmount != nil {
		approved = ugx(*d.ApprovedAmount)
	} else if e := c.record.Existing; e != nil {
		approved = ugx(e.Approved)
	}
	if c.disbursed() {
		disbursed = ugx(c.position.NetDisbursed)
	}
	return recommended, approved, disbursed
}

func (l *Lending) view(ctx context.Context, c *caseData, v viewer) (*loansv1.CaseView, error) {
	r := c.record.Referral
	stage := c.stage()
	out := &loansv1.CaseView{ApplicationId: r.ID, Reference: r.Reference, Title: r.SchoolName,
		Subtitle: strings.Join(nonEmpty(r.District, r.LenderName), " · "), Stage: stage, StageLabel: StageLabels[stage]}
	if c.disbursed() {
		out.ServicingLabel = ledger.Label(c.position.Status)
	}
	summaryOnly := v.edify != nil && v.edify.summaryOnly
	out.Sections = append(out.Sections, c.summarySection(v))
	if s := c.existingLoanSection(); s != nil && !summaryOnly {
		out.Sections = append(out.Sections, s)
	}
	if !summaryOnly {
		out.Sections = append(out.Sections, c.schoolSection())
	}
	if c.disbursed() {
		out.Sections = append(out.Sections, c.balanceSection(), c.installmentSection(), c.statementSection())
	}
	if len(c.record.Evidence) > 0 {
		out.Sections = append(out.Sections, c.paymentSection())
	}
	if !summaryOnly {
		out.Sections = append(out.Sections, c.originationSections(v)...)
	}
	if len(c.record.Collateral) > 0 {
		out.Sections = append(out.Sections, c.collateralSection(summaryOnly))
	}
	if !summaryOnly && len(c.record.Requests) > 0 {
		out.Sections = append(out.Sections, c.requestSection())
	}
	if !summaryOnly && len(c.record.Documents) > 0 {
		out.Sections = append(out.Sections, c.documentSection())
	}
	timeline, err := l.timelineSection(ctx, c, v)
	if err != nil {
		return nil, err
	}
	out.Sections = append(out.Sections, timeline)
	for _, action := range l.actionsFor(c, v) {
		fields, err := action.fields(ctx, l, c, v)
		if err != nil {
			return nil, err
		}
		out.Actions = append(out.Actions, &loansv1.CaseAction{Key: action.key, Label: action.label,
			Description: action.description, IsPrimary: action.primary, IsDanger: action.danger, Fields: fields})
	}
	return out, nil
}

func nonEmpty(values ...string) []string {
	var out []string
	for _, v := range values {
		if strings.TrimSpace(v) != "" {
			out = append(out, v)
		}
	}
	return out
}

func (l *Lending) actionsFor(c *caseData, v viewer) []caseAction {
	var out []caseAction
	for _, action := range caseActions {
		if action.allowed(c, v) {
			out = append(out, action)
		}
	}
	return out
}

func (c *caseData) summarySection(v viewer) *loansv1.CaseSection {
	r := c.record.Referral
	recommended, approved, disbursed := c.amounts()
	officer := "Not assigned"
	if a := c.record.Assignment; a != nil {
		officer = a.OfficerName
	}
	s := section("summary", "Loan", "Requested, recommended, approved and disbursed amounts are recorded separately.",
		line("Reference", r.Reference),
		line("Lender", r.LenderName),
		line("Stage", StageLabels[c.stage()]),
		line("Loan officer", officer),
		line("Purpose", r.PurposeLabel),
		line("Requested", FormatUGX(r.Requested)),
		line("Recommended", recommended),
		line("Approved", approved),
		line("Disbursed", disbursed),
	)
	if c.disbursed() {
		s.Lines = append(s.Lines, toned("Servicing", ledger.Label(c.position.Status), servicingTone(c.position.Status)),
			line("Outstanding", ugx(c.position.TotalOutstanding)))
	}
	if c.record.ClosureStatus != "" {
		s.Lines = append(s.Lines, line("Closure", c.record.ClosureNote))
	}
	return s
}

func (c *caseData) schoolSection() *loansv1.CaseSection {
	r := c.record.Referral
	edifyID := r.EdifySchoolID
	if edifyID == "" {
		edifyID = "Not yet matched to the School Directory"
	}
	return section("school", "School", "",
		line("School", r.SchoolName),
		line("Edify School ID", edifyID),
		line("Location", strings.Join(nonEmpty(r.Village, r.Parish, r.SubCounty, r.District), ", ")),
		line("Director", r.DirectorName),
		line("Director's phone", r.DirectorPhone),
		line("Director's email", r.DirectorEmail),
		line("Enrollment", fmt.Sprintf("%d (%d boys, %d girls)", r.Total, r.Boys, r.Girls)),
		line("Fees collected per term (as stated)", FormatUGX(r.FeesCollected)),
	)
}

// balanceSection shows how the outstanding balance is worked out, step by
// step, from verified postings only.
func (c *caseData) balanceSection() *loansv1.CaseSection {
	p := c.position
	s := section("balance", "How the balance is calculated",
		"Only payments the lender has verified count. A receipt waiting for verification does not change the balance.",
		line("Principal disbursed", ugx(p.NetDisbursed)),
		line("Interest in the agreed schedule", "+ "+ugx(p.InterestScheduled)),
		line("Fees in the agreed schedule", "+ "+ugx(p.FeesScheduled)),
		line("Total to repay", "= "+ugx(p.TotalObligation)),
		line("Verified payments", "− "+ugx(p.TotalVerifiedRepayments)),
		toned("Outstanding balance", "= "+ugx(p.TotalOutstanding), "info"),
		owedTodayLine(p, "of which owed today", "of which paid ahead of the due dates"),
		line("of which interest and fees not yet due", ugx(p.FutureCharges)),
		line("Principal outstanding", ugx(p.OutstandingPrincipal)),
	)
	if p.AmountOverdue > 0 {
		s.Lines = append(s.Lines, toned("Overdue", fmt.Sprintf("%s, %d days past due", ugx(p.AmountOverdue), p.DaysPastDue), "alert"))
	}
	if p.NextDue != nil {
		s.Lines = append(s.Lines, line("Next installment", fmt.Sprintf("%s remaining, due %s", ugx(p.NextDue.Remaining), day(p.NextDue.DueDate))))
	}
	if p.LastPaymentDate != nil {
		s.Lines = append(s.Lines, line("Last verified payment", day(*p.LastPaymentDate)))
	}
	if c.penaltyPaid > 0 {
		s.Lines = append(s.Lines, line("Penalties paid (recorded in the ledger)", ugx(c.penaltyPaid)))
	}
	return s
}

// owedTodayLine: a school that paid interest or fees before their due dates
// owes nothing today and is ahead of its schedule, never "owes" a negative.
func owedTodayLine(p ledger.Position, owed, ahead string) *loansv1.CaseLine {
	if p.OwedToday < 0 {
		return line(ahead, ugx(-p.OwedToday))
	}
	return line(owed, ugx(p.OwedToday))
}

// balanceText words a running balance; below zero the school is ahead.
func balanceText(m ledger.Money) string {
	if m < 0 {
		return ugx(-m) + " paid ahead"
	}
	return ugx(m)
}

func (c *caseData) installmentSection() *loansv1.CaseSection {
	t := table("No.", "Due", "Principal", "Interest", "Fees", "Total", "Paid", "Remaining", "Status")
	for _, i := range c.position.Installments {
		addRow(t, installmentTones[i.Status], "", fmt.Sprint(i.Number), day(i.DueDate), ugx(i.Principal), ugx(i.Interest),
			ugx(i.Fee), ugx(i.Total()), ugx(i.Paid), ugx(i.Remaining), installmentLabels[i.Status])
	}
	s := section("installments", "Repayment schedule", "")
	if len(t.Rows) == 0 {
		s.Note = "The repayment schedule has not been posted yet."
	}
	s.Table = t
	return s
}

func (c *caseData) statementSection() *loansv1.CaseSection {
	t := table("Date", "Description", "Reference", "Charged", "Paid", "Balance")
	for _, entry := range c.book.Statement(c.today) {
		charged, paid := "", ""
		if entry.Debit > 0 {
			charged = ugx(entry.Debit)
		}
		if entry.Credit > 0 {
			paid = ugx(entry.Credit)
		}
		addRow(t, "", "", day(entry.Date), entry.Description, entry.Reference, charged, paid, balanceText(entry.Balance))
	}
	s := section("statement", "Statement", "Each line from the loan ledger. The last balance is what is owed today.")
	s.Table = t
	return s
}

func (c *caseData) paymentSection() *loansv1.CaseSection {
	t := table("Paid on", "Amount", "Method", "Reference", "Recorded by", "Status", "Applied", "Verified by")
	var pending ledger.Money
	reversed := c.book.ReversedBy(c.today)
	for _, e := range c.record.Evidence {
		applied, by := "—", e.VerifiedByName
		if e.Applied != nil {
			applied = ugx(*e.Applied)
			if e.Excess > 0 {
				applied += " (" + ugx(e.Excess) + " overpaid)"
			}
		}
		status := evidenceStatusLabels[e.Status]
		tone := map[string]string{"verified": "good", "rejected": "alert", "verification_pending": "caution"}[e.Status]
		if e.Status == "verified" && reversed[e.LedgerTransactionID] {
			status, tone = "Verified, then reversed", "alert"
		}
		if e.Status == "rejected" && e.RejectionReason != "" {
			status += ": " + e.RejectionReason
		}
		if e.Status == "verification_pending" {
			pending += e.Amount
		}
		addRow(t, tone, e.DocumentID, day(e.PaidOn), ugx(e.Amount), labelOf(paymentMethods, e.Method), e.Reference,
			e.SubmittedByName, status, applied, by)
	}
	note := "A payment reduces the balance only once it is verified."
	if pending > 0 {
		note = ugx(pending) + " is waiting for verification and is not yet in the balance."
	}
	s := section("payments", "Payments reported", note)
	s.Table = t
	return s
}

func (c *caseData) originationSections(v viewer) []*loansv1.CaseSection {
	var out []*loansv1.CaseSection
	if len(c.record.Assignments) > 0 {
		t := table("Officer", "Assigned", "By", "Ended", "Reason")
		for _, a := range c.record.Assignments {
			addRow(t, "", "", a.OfficerName, day(a.AssignedAt), a.AssignedByName, optionalDay(a.EndedAt), a.EndReason)
		}
		s := section("assignments", "Assignments", "")
		s.Table = t
		out = append(out, s)
	}
	if len(c.record.Contacts) > 0 {
		t := table("Date", "Officer", "Method", "Outcome", "Notes", "Next action")
		for _, contact := range c.record.Contacts {
			addRow(t, "", "", day(contact.ContactedOn), contact.OfficerName, labelOf(contactMethods, contact.Method),
				labelOf(contactOutcomes, contact.Outcome), contact.Notes, optionalDay(contact.NextActionOn))
		}
		s := section("contacts", "Contact attempts", "")
		s.Table = t
		out = append(out, s)
	}
	if a := c.record.Assessment; a != nil {
		s := section("assessment", "Assessment", "What the officer verified, kept apart from what the school stated.",
			line("Status", assessmentStatusLabels[a.Status]), line("Visit", optionalDay(a.VisitOn)))
		for _, fact := range assessmentFacts {
			value := a.Facts[fact.key]
			if value == "" {
				continue
			}
			if fact.kind == "money" {
				if m, err := ledger.ParseMoney(value); err == nil {
					value = ugx(m)
				}
			}
			s.Lines = append(s.Lines, line(fact.label, value))
		}
		s.Lines = append(s.Lines, line("Observations", a.Observations), line("Strengths", a.Strengths),
			line("Risks", a.Risks), line("Documents reviewed", a.DocumentsReviewed),
			line("Outcome", labelOf(assessmentOutcomes, a.Outcome)))
		out = append(out, s)
	}
	if r := c.record.LatestRecommendation(); r != nil {
		out = append(out, recommendationSection(*r))
	}
	if len(c.record.Agreements) > 0 {
		t := table("Version", "Principal", "Total to repay", "Issued", "By", "Status", "Responded")
		for _, a := range c.record.Agreements {
			principal, _ := ledger.ParseMoney(a.Terms.Principal)
			total, _ := ledger.ParseMoney(a.Terms.TotalRepayable)
			addRow(t, map[string]string{"accepted": "good", "declined": "alert"}[a.Status], "", fmt.Sprint(a.Version),
				ugx(principal), ugx(total), day(a.IssuedAt), a.IssuedByName, agreementStatusLabel(a.Status), optionalDay(a.RespondedAt))
		}
		s := section("agreements", "School agreement", "The school sees the exact terms and schedule, and responds after a one-time code.")
		if latest := c.record.LatestAgreement(); latest.ResponseNote != "" {
			s.Lines = append(s.Lines, line("School's note", latest.ResponseNote))
		}
		s.Table = t
		out = append(out, s)
	}
	if len(c.record.Decisions) > 0 {
		t := table("Decision", "Approved amount", "By", "On", "Rationale")
		for _, d := range c.record.Decisions {
			amount := "—"
			if d.ApprovedAmount != nil {
				amount = ugx(*d.ApprovedAmount)
			}
			addRow(t, map[string]string{"approved": "good", "declined": "alert"}[d.Decision], "",
				map[string]string{"approved": "Approved", "declined": "Declined", "returned": "Returned"}[d.Decision],
				amount, d.DecidedByName, day(d.DecidedAt), d.Rationale)
		}
		s := section("decisions", "Credit decisions", "")
		s.Table = t
		out = append(out, s)
	}
	return out
}

func agreementStatusLabel(status string) string {
	return map[string]string{"issued": "Awaiting the school", "accepted": "Accepted", "declined": "Declined",
		"clarification_requested": "Clarification requested", "superseded": "Replaced by a newer version"}[status]
}

func recommendationSection(r Recommendation) *loansv1.CaseSection {
	money := func(key string) string {
		m, err := ledger.ParseMoney(r.Affordability[key])
		if err != nil {
			return "—"
		}
		return ugx(m)
	}
	s := section("recommendation", fmt.Sprintf("Credit recommendation (version %d)", r.Version),
		"The affordability worksheet is indicative. The credit decision is the lender's own.",
		line("Recommended amount", ugx(r.Amount)),
		line("Interest", r.RatePercent+"% per term, "+ledger.MethodLabel(ledger.Method(r.Method))),
		line("Fee per installment", ugx(r.Fee)),
		line("Verified collections per term", money("collections")),
		line("Necessary expenses per term", "− "+money("expenses")),
		line("Existing debt repayments per term", "− "+money("debt_service")),
		line("Available", "= "+money("available")),
		line("Cushion for variability", r.Affordability["cushion_percent"]+"%"),
		line("Indicative repayment capacity per term", money("capacity")),
		line("Largest installment", money("largest_installment")+" ("+r.Affordability["installment_share_percent"]+"% of capacity)"),
		line("Collateral proposed", r.CollateralSummary),
		line("Rationale", r.Rationale),
		line("Prepared by", r.SubmittedByName),
	)
	if terms, err := r.Terms(); err == nil {
		if schedule, err := ledger.BuildSchedule(terms); err == nil {
			t := table("No.", "Due", "Principal", "Interest", "Fees", "Total")
			for _, i := range schedule {
				addRow(t, "", "", fmt.Sprint(i.Number), day(i.DueDate), ugx(i.Principal), ugx(i.Interest), ugx(i.Fee), ugx(i.Total()))
			}
			s.Table = t
		}
	}
	return s
}

func (c *caseData) collateralSection(summaryOnly bool) *loansv1.CaseSection {
	t := table("Type", "Description", "Value", "Custodian", "Status", "Released to")
	for _, item := range c.record.Collateral {
		value := "—"
		if item.EstimatedValue != nil {
			value = ugx(*item.EstimatedValue)
		}
		description := item.Description
		if summaryOnly {
			description = ""
		}
		tone := map[string]string{"accepted": "good", "released": "good", "release_pending": "caution", "disputed": "alert"}[item.Status]
		addRow(t, tone, "", labelOf(collateralTypes, item.ItemType), description, value, item.Custodian,
			collateralLabels[item.Status], item.ReleasedTo)
	}
	note := ""
	if c.stage() == StageSettledPending {
		note = "The loan is fully settled. Release the collateral and record the evidence to close the loan."
	}
	s := section("collateral", "Collateral", note)
	s.Table = t
	return s
}

func (c *caseData) requestSection() *loansv1.CaseSection {
	kinds := map[string]string{"discrepancy": "Payment discrepancy", "statement_update": "Statement update",
		"contact": "Contact request", "clarification": "Clarification"}
	t := table("Received", "Kind", "Message", "Status", "Answer")
	for _, r := range c.record.Requests {
		tone := ""
		if r.Status == "open" {
			tone = "caution"
		}
		addRow(t, tone, "", day(r.CreatedAt), kinds[r.Kind], r.Message, map[string]string{"open": "Open", "answered": "Answered"}[r.Status], r.Answer)
	}
	s := section("requests", "Requests from the school", "")
	s.Table = t
	return s
}

func (c *caseData) documentSection() *loansv1.CaseSection {
	t := table("Document", "Kind", "Uploaded", "By")
	for _, d := range c.record.Documents {
		by := map[string]string{"lender": "Lender", "school": "School"}[d.UploadedByKind]
		addRow(t, "", d.ID, d.FileName, strings.ReplaceAll(d.Kind, "_", " "), day(d.CreatedAt), by)
	}
	s := section("documents", "Documents", "")
	s.Table = t
	return s
}

type timelineEntry struct {
	at          time.Time
	what, by, n string
}

func (l *Lending) timelineSection(ctx context.Context, c *caseData, v viewer) (*loansv1.CaseSection, error) {
	events, err := l.store.Timeline(ctx, c.record.Referral.ID, v.isLender())
	if err != nil {
		return nil, err
	}
	var entries []timelineEntry
	for _, e := range events {
		entries = append(entries, timelineEntry{e.At, caseEventLabel(e.Kind), e.ActorName, e.Note})
	}
	for _, contact := range c.record.Contacts {
		entries = append(entries, timelineEntry{contact.CreatedAt, "Contact: " + labelOf(contactOutcomes, contact.Outcome), contact.OfficerName, ""})
	}
	for _, item := range c.record.Collateral {
		for _, e := range item.Events {
			entries = append(entries, timelineEntry{e.At, "Collateral " + strings.ToLower(collateralLabels[e.ToStatus]), e.ActorName, e.Note})
		}
	}
	for _, e := range c.record.Evidence {
		entries = append(entries, timelineEntry{e.SubmittedAt, "Payment recorded: " + ugx(e.Amount), e.SubmittedByName, ""})
		if e.VerifiedAt != nil {
			entries = append(entries, timelineEntry{*e.VerifiedAt, "Payment " + strings.ToLower(evidenceStatusLabels[e.Status]),
				e.VerifiedByName, e.RejectionReason})
		}
	}
	sort.SliceStable(entries, func(i, j int) bool { return entries[i].at.After(entries[j].at) })
	t := table("When", "What", "By", "Note")
	summaryOnly := v.edify != nil && v.edify.summaryOnly
	for _, e := range entries {
		if summaryOnly {
			e.n = "" // the summary view carries no case notes
		}
		addRow(t, "", "", longMoment(e.at), e.what, e.by, e.n)
	}
	s := section("timeline", "History", "Every step is kept; nothing is overwritten.")
	s.Table = t
	return s, nil
}

var caseEventLabels = map[string]string{
	"assigned": "Officer assigned", "agreement_issued": "Terms sent to the school", "agreement_accepted": "School accepted the terms",
	"agreement_declined": "School declined the terms", "agreement_clarification_requested": "School asked for clarification",
	"credit_approved": "Credit approved", "credit_declined": "Credit declined", "credit_returned": "Returned to the officer",
	"recommendation_submitted": "Recommendation submitted", "ledger_referral": "Referred in the loan ledger",
	"loan_closed": "Loan closed", "loan_written_off": "Loan written off", "school_request": "Request from the school",
	"payment_reported": "Payment reported by the school (awaiting verification)", "notification": "Notification to the school",
	"follow_up": "Edify follow-up", "existing_terms": "Existing loan terms recorded", "loan_linked": "Registered in the loan ledger",
}

func caseEventLabel(kind string) string {
	if label, ok := caseEventLabels[kind]; ok {
		return label
	}
	return eventLabel(kind)
}

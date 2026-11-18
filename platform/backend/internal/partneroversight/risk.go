package partneroversight

import (
	"time"
)

// risksOf is partner_risk_service.risks_for: the keys of the risks the work
// carries on today (the page counts them; it draws none of their words).
func risksOf(i *item, today time.Time) []string {
	r := rules.Work.Risk
	w := rules.Work
	days := func(n int) time.Duration { return time.Duration(n) * 24 * time.Hour }
	out := []string{}
	add := func(key string, ok bool) {
		if ok {
			out = append(out, key)
		}
	}
	if i.stage == stageAwaiting {
		deadline := today
		if i.assignmentDate != nil {
			deadline = *i.assignmentDate
		}
		deadline = deadline.Add(days(r.ScheduleGraceDays))
		add("partner_schedule_overdue", today.After(deadline))
		add("partner_schedule_approaching", !deadline.Before(today) && !deadline.After(today.Add(days(r.ApproachingDays))))
	}
	add("assignment_returned", i.stage == stageReturned)
	noEvidence := i.evidenceStatus == "" || i.evidenceStatus == "none"
	if i.isScheduled() && i.scheduledDate != nil {
		d := *i.scheduledDate
		add("partner_delivery_overdue", d.Before(today) && !in(w.Complete, i.activityStatus) && noEvidence)
	}
	add("partner_rate_missing", i.isScheduled() && (i.plannedCost == nil || *i.plannedCost == 0))
	if i.isScheduled() && i.scheduledDate != nil {
		d := *i.scheduledDate
		add("partner_evidence_overdue", noEvidence && in(w.InProgress, i.activityStatus) &&
			d.Add(days(r.EvidenceGraceDays)).Before(today))
	}
	if i.evidenceStatus == "uploaded" && i.scheduledDate != nil {
		add("evidence_submission_stalled", i.scheduledDate.Add(days(r.ReviewGraceDays)).Before(today))
	}
	add("salesforce_overdue", i.activityStatus == "salesforce_id_required" && !i.salesforceRecorded)
	if i.submittedToIA != nil && i.iaStatus != "confirmed" && i.iaStatus != "returned" && i.iaStatus != "flagged" {
		add("ia_verification_overdue", today.After(i.submittedToIA.Add(days(r.IAVerificationGraceDays))))
	}
	if (i.activityStatus == "ia_verified" || i.activityStatus == "accountant_confirmed") &&
		(i.paymentStatus == "" || i.paymentStatus == "none" || i.paymentStatus == "pending") && i.scheduledDate != nil {
		add("partner_payment_overdue", i.scheduledDate.Add(days(r.PaymentGraceDays)).Before(today))
	}
	return out
}

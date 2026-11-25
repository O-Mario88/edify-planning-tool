package partneroversight

import (
	"fmt"
	"slices"
	"time"
)

// partnerRisk is partner_risk_service.PartnerRisk: one risk with who must
// move, what to do and by when.
type partnerRisk struct {
	key, severity, reason, responsible, action string
	route                                      string
	due                                        *time.Time
	role                                       string // a role queue's
}

func severityRank(s string) int {
	switch s {
	case "critical":
		return 0
	case "high":
		return 1
	case "warning":
		return 2
	}
	return 9
}

// risksWithWords is partner_risk_service.risks_for: the risks risksOf names,
// each worded as the existing detector words it, worst first.
func risksWithWords(i *item, today time.Time) []partnerRisk {
	r := rules.Work.Risk
	w := rules.Work
	days := func(n int) time.Duration { return time.Duration(n) * 24 * time.Hour }
	partner := first(i.partnerName, "Partner")
	thePartner := first(i.partnerName, "The partner")
	cceo := first(i.cceoName, "CCEO")
	at := func(t time.Time) *time.Time { return &t }
	out := []partnerRisk{}
	if i.stage == stageAwaiting {
		deadline := today
		if i.assignmentDate != nil {
			deadline = *i.assignmentDate
		}
		deadline = deadline.Add(days(r.ScheduleGraceDays))
		if today.After(deadline) {
			n := int(today.Sub(deadline).Hours() / 24)
			severity := "warning"
			if n > r.ScheduleGraceDays {
				severity = "high"
			}
			out = append(out, partnerRisk{key: "partner_schedule_overdue", route: "/partner-oversight/", severity: severity,
				reason:      fmt.Sprintf("%s has not scheduled this, %d day(s) past due.", thePartner, n),
				responsible: partner, action: "Remind the partner, or take the work back", due: at(deadline)})
		}
		if !deadline.Before(today) && !deadline.After(today.Add(days(r.ApproachingDays))) {
			out = append(out, partnerRisk{key: "partner_schedule_approaching", route: "/partner-oversight/", severity: "warning",
				reason:      fmt.Sprintf("Schedule-by date is %s and no date has been set.", deadline.Format("2 Jan")),
				responsible: partner, action: "Remind the partner", due: at(deadline)})
		}
	}
	if i.stage == stageReturned {
		reason := thePartner + " returned this."
		if i.returnReason != "" {
			reason = thePartner + " returned this: " + i.returnReason
		}
		out = append(out, partnerRisk{key: "assignment_returned", route: "/planning", severity: "high", reason: reason, responsible: cceo,
			action: "Reassign, schedule as staff work, or cancel"})
	}
	noEvidence := i.evidenceStatus == "" || i.evidenceStatus == "none"
	if i.isScheduled() && i.scheduledDate != nil {
		d := *i.scheduledDate
		if d.Before(today) && !in(w.Complete, i.activityStatus) && noEvidence {
			n := int(today.Sub(d).Hours() / 24)
			severity := "high"
			if n > 14 {
				severity = "critical"
			}
			out = append(out, partnerRisk{key: "partner_delivery_overdue", route: "/partner-oversight/", severity: severity,
				reason:      fmt.Sprintf("Scheduled for %s with no evidence yet (%d days).", d.Format("2 Jan"), n),
				responsible: partner, action: "Ask the partner to deliver or reschedule", due: at(d)})
		}
	}
	if i.isScheduled() && (i.plannedCost == nil || *i.plannedCost == 0) {
		out = append(out, partnerRisk{key: "partner_rate_missing", route: "/cost-settings", severity: "critical",
			reason: "Scheduled, but no partner rate was found in the cost catalogue.", responsible: "Country Director",
			action: "Add the partner rate to the Cost Catalogue"})
	}
	if i.isScheduled() && i.scheduledDate != nil {
		d := *i.scheduledDate
		if noEvidence && in(w.InProgress, i.activityStatus) && d.Add(days(r.EvidenceGraceDays)).Before(today) {
			out = append(out, partnerRisk{key: "partner_evidence_overdue", route: "/partner-oversight/", severity: "high",
				reason: "Delivery began but no evidence has been uploaded.", responsible: partner,
				action: "Ask the partner to upload the evidence pack", due: at(d.Add(days(r.EvidenceGraceDays)))})
		}
	}
	if i.evidenceStatus == "uploaded" && i.scheduledDate != nil && i.scheduledDate.Add(days(r.ReviewGraceDays)).Before(today) {
		out = append(out, partnerRisk{key: "evidence_submission_stalled", route: "/partner-oversight/", severity: "high",
			reason: "Evidence was captured but never submitted to IA.", responsible: partner,
			action: "Chase the partner to submit the evidence to IA", due: at(i.scheduledDate.Add(days(r.ReviewGraceDays)))})
	}
	if i.activityStatus == "salesforce_id_required" && !i.salesforceRecorded {
		out = append(out, partnerRisk{key: "salesforce_overdue", route: "/my-plan", severity: "warning",
			reason: "Evidence is accepted but no Salesforce Activity ID has been entered.", responsible: cceo,
			action: "Enter the Salesforce Activity ID"})
	}
	if i.submittedToIA != nil && i.iaStatus != "confirmed" && i.iaStatus != "returned" && i.iaStatus != "flagged" {
		due := i.submittedToIA.Add(days(r.IAVerificationGraceDays))
		if today.After(due) {
			waiting := int(today.Sub(*i.submittedToIA).Hours() / 24)
			severity := "warning"
			if waiting > 2*r.IAVerificationGraceDays {
				severity = "high"
			}
			out = append(out, partnerRisk{key: "ia_verification_overdue", route: "/ia/verification/", severity: severity,
				reason:      fmt.Sprintf("Submitted for verification %d day(s) ago. The partner cannot be paid until it is verified.", waiting),
				responsible: "Impact Assessment", action: "Verify the partner's submission", due: at(due), role: "ImpactAssessment"})
		}
	}
	if (i.activityStatus == "ia_verified" || i.activityStatus == "accountant_confirmed") &&
		(i.paymentStatus == "" || i.paymentStatus == "none" || i.paymentStatus == "pending") && i.scheduledDate != nil {
		due := i.scheduledDate.Add(days(r.PaymentGraceDays))
		if due.Before(today) {
			out = append(out, partnerRisk{key: "partner_payment_overdue", route: "/accounts/partner-payments", severity: "high",
				reason: "Verified by Impact Assessment and still unpaid.", responsible: "Accountant", action: "Pay the partner",
				due: at(due), role: "Accountant"})
		}
	}
	slices.SortStableFunc(out, func(a, b partnerRisk) int { return severityRank(a.severity) - severityRank(b.severity) })
	return out
}

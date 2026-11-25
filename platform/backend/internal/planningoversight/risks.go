package planningoversight

import (
	"fmt"
	"slices"
	"time"
)

// risk is one risk_service.PlanningRisk on a staff item: what to do, why,
// who is answerable and by when.
type risk struct {
	key, severity, reason, action, owner string
	due                                  *time.Time
	role                                 string // a role queue's, not a person's
}

// severityRank is risk_service._SEVERITY_ORDER.
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

// roleLabels is risk_service.ROLE_LABELS.
var roleLabels = map[string]string{"ImpactAssessment": "Impact Assessment", "Accountant": "Accountant"}

// risksFor is risk_service.risks_for on a staff item (the Partner's own
// detector never fires on one): each detector in order, worst first. Its
// conditions are hasRisk's.
func risksFor(it *item, today time.Time) []risk {
	r := rules.TeamPlan.Items.Risk
	a := it.a
	in := slices.Contains[[]string]
	days := func(t *time.Time, n int) time.Time { return t.AddDate(0, 0, n) }
	staff := func(key, severity, reason, action string, due *time.Time) risk {
		return risk{key: key, severity: severity, reason: reason, action: action, owner: it.ownerName, due: due}
	}
	out := []risk{}
	if a.costMissing || !(it.costOnVisit || it.plannedCost > 0) {
		severity := "high"
		if a.costMissing {
			severity = "critical"
		}
		out = append(out, staff("scheduled_without_cost", severity,
			"This activity is scheduled but has no cost line, so it cannot enter a fund request or a monthly budget.",
			"Add the missing Cost Catalogue configuration", it.plannedDate))
	}
	if p := it.plannedDate; p != nil {
		if p.Before(today) && !it.completed() && !in(r.PostFieldStatuses, it.status) && it.submittedToIA == nil {
			n := int(today.Sub(*p).Hours() / 24)
			severity := "high"
			if n > 14 {
				severity = "critical"
			}
			out = append(out, staff("activity_overdue", severity,
				fmt.Sprintf("Planned for %s and still not completed (%d days).", p.Format("2 Jan"), n),
				"Complete the activity or reschedule it", p))
		}
		if (a.evidence == "" || a.evidence == "none") && days(p, r.EvidenceGraceDays).Before(today) &&
			in(r.EvidenceExpectedStatuses, it.status) {
			due := days(p, r.EvidenceGraceDays)
			out = append(out, staff("evidence_outstanding", "high",
				"The activity was started but has not been completed with its Salesforce ID.",
				"Complete it with the Salesforce ID", &due))
		}
	}
	if a.salesforce == "" && in(r.SalesforceExpectedStatuses, it.status) {
		out = append(out, staff("salesforce_missing", "warning",
			"The activity is complete but has no Salesforce Activity ID.", "Enter the Salesforce Activity ID", nil))
	}
	if it.status == "returned_by_ia" || a.ia == "returned" {
		out = append(out, staff("ia_returned", "critical",
			"Impact Assessment returned this activity and it has not been resubmitted.", "Resolve the IA return and resubmit", nil))
	}
	if a.reschedules > int64(r.RescheduleLimit) {
		out = append(out, staff("repeated_reschedule", "warning",
			fmt.Sprintf("This activity has been rescheduled %d times.", a.reschedules), "Review whether the plan is realistic", nil))
	}
	if sub := utcDay(it.submittedToIA); sub != nil && !in(r.IASettledStatuses, first(a.ia, "pending")) &&
		today.After(days(sub, r.IAVerificationGraceDays)) {
		due := days(sub, r.IAVerificationGraceDays)
		waiting := int(today.Sub(*sub).Hours() / 24)
		severity := "warning"
		if waiting > 2*r.IAVerificationGraceDays {
			severity = "high"
		}
		out = append(out, risk{key: "ia_verification_overdue", severity: severity,
			reason: fmt.Sprintf("Submitted for verification %d day(s) ago and still unverified, so the work earns no credit and cannot be paid.", waiting),
			action: "Verify the submission", owner: roleLabels["ImpactAssessment"], due: &due, role: "ImpactAssessment"})
	}
	if a.ia == "confirmed" && !in(r.PaymentSettledStatuses, first(a.payment, "none")) && it.plannedDate != nil &&
		today.After(days(it.plannedDate, r.PaymentGraceDays)) {
		due := days(it.plannedDate, r.PaymentGraceDays)
		out = append(out, risk{key: "payment_overdue", severity: "high",
			reason: fmt.Sprintf("Verified by Impact Assessment and unpaid %d day(s) past the settlement window.", int(today.Sub(due).Hours()/24)),
			action: "Settle the payment", owner: roleLabels["Accountant"], due: &due, role: "Accountant"})
	}
	slices.SortStableFunc(out, func(x, y risk) int { return severityRank(x.severity) - severityRank(y.severity) })
	return out
}

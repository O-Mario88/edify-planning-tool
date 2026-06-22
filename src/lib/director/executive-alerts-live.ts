// Live executive alerts for the Country Director — derived from backend fund
// requests, leadership summary, and people rosters. No school-directory links;
// the CD monitors through analytics, finance, and ticket assignment to PLs.

import type { BeFundRequest, BeLeadershipSummary, BePartner, BeRosterRow } from "@/lib/api/surfaces";
import type { ExecutiveAlert, ExecutiveAlertInputs } from "./executive-alerts";

const fmtUgx = (n: number) =>
  n >= 1_000_000_000 ? `UGX ${(n / 1_000_000_000).toFixed(2)}B`
  : n >= 1_000_000 ? `UGX ${(n / 1_000_000).toFixed(1)}M`
  : `UGX ${n.toLocaleString()}`;

export type LiveExecutiveAlertInputs = ExecutiveAlertInputs & {
  fundRequests?: BeFundRequest[];
  leadership?: BeLeadershipSummary | null;
  staff?: BeRosterRow[];
  partners?: BePartner[];
};

export function buildExecutiveAlertsLive(inputs: LiveExecutiveAlertInputs = {}): ExecutiveAlert[] {
  const alerts: ExecutiveAlert[] = [];
  const fr = inputs.fundRequests ?? [];

  const pendingReview = fr.filter((r) => r.status === "submitted" && r.canReview);
  if (pendingReview.length > 0) {
    const total = pendingReview.reduce((s, r) => s + r.totalAmount, 0);
    const activities = pendingReview.reduce((s, r) => s + r.activityCount, 0);
    alerts.push({
      id: "fund-requests-pending",
      severity: "urgent",
      issue: `${pendingReview.length} fund request${pendingReview.length > 1 ? "s" : ""} need your approval`,
      why: `${fmtUgx(total)} across ${activities} planned activities — field execution is blocked until you approve or return.`,
      scope: pendingReview.map((r) => r.scope || r.periodKey).join(", ") || "Country-wide",
      recommendedAction: "Review each request against the team plan and cost catalogue, then approve or return with a reason.",
      actionLabel: "Open Fund Approvals",
      actionHref: "/approvals",
    });
  }

  const accountReview = fr.filter((r) => r.canAccountReview);
  if (accountReview.length > 0) {
    alerts.push({
      id: "accountability-review",
      severity: "warning",
      issue: `${accountReview.length} disbursement${accountReview.length > 1 ? "s" : ""} await accountability sign-off`,
      why: "Funds were released — accountability must be verified before the next disbursement cycle closes.",
      scope: "Country-wide",
      recommendedAction: "Review submitted accountability receipts and NetSuite references; approve or return to the submitter.",
      actionLabel: "Review Accountability",
      actionHref: "/approvals",
    });
  }

  const disbursedOpen = fr.filter((r) => r.status === "disbursed" && (r.accountabilityStatus === "none" || !r.accountabilityStatus));
  if (disbursedOpen.length > 0) {
    alerts.push({
      id: "accountability-missing",
      severity: "watch",
      issue: `${disbursedOpen.length} disbursed request${disbursedOpen.length > 1 ? "s" : ""} without accountability filed`,
      why: "Open accountability gaps weaken financial control and donor confidence.",
      scope: "Country-wide",
      recommendedAction: "Follow up with Program Leads — assign a ticket if accountability is overdue.",
      actionLabel: "Open Disbursements",
      actionHref: "/disbursements",
    });
  }

  const ls = inputs.leadership;
  if (ls && ls.fundRequests > 0 && pendingReview.length === 0) {
    alerts.push({
      id: "fund-pipeline-active",
      severity: "watch",
      issue: `${ls.fundRequests} fund request${ls.fundRequests > 1 ? "s" : ""} in the country pipeline`,
      why: `${fmtUgx(ls.disbursedTotalUgx)} disbursed to date — monitor that spending tracks verified activity.`,
      scope: "Country-wide",
      recommendedAction: "Open the finance snapshot and confirm disbursements match completed work.",
      actionLabel: "Weekly Funds",
      actionHref: "/weekly-funds",
    });
  }

  const fieldStaff = (inputs.staff ?? []).filter((s) => s.role === "CCEO" || s.role === "CountryProgramLead");
  const inactive = fieldStaff.filter((s) => !s.active);
  if (inactive.length > 0) {
    alerts.push({
      id: "staff-inactive",
      severity: "watch",
      issue: `${inactive.length} field staff account${inactive.length > 1 ? "s" : ""} inactive on the roster`,
      why: "Inactive owners block planning handoffs and distort performance reporting.",
      scope: "HR / PL oversight",
      recommendedAction: "Confirm with HR whether accounts should be reactivated or reassigned.",
      actionLabel: "Staff Performance",
      actionHref: "/staff",
    });
  }

  const partners = inputs.partners ?? [];
  const uncertified = partners.filter((p) => !p.isCertified && p.certificationStatus !== "Certified");
  if (uncertified.length > 0) {
    alerts.push({
      id: "partner-cert-gap",
      severity: "warning",
      issue: `${uncertified.length} active partner${uncertified.length > 1 ? "s" : ""} not yet certified`,
      why: "Uncertified partners should not carry new assignments — delivery quality and fund controls depend on certification.",
      scope: "Country-wide",
      recommendedAction: "Review partner onboarding status and pause new assignments where certification is pending.",
      actionLabel: "Partner Performance",
      actionHref: "/partners",
    });
  }

  if ((inputs.unclusteredSchools ?? 0) > 0) {
    alerts.push({
      id: "unclustered-schools",
      severity: "watch",
      issue: `${inputs.unclusteredSchools} schools have no cluster assignment`,
      why: "Clustering gates team planning — flag Program Leads to clear the queue (you do not plan directly).",
      scope: "Country-wide",
      recommendedAction: "Create a ticket for the relevant Program Lead to clear cluster assignments.",
      actionLabel: "Open Analytics",
      actionHref: "/analytics",
    });
  }

  if (ls && ls.pipeline) {
    const awaitingIa = ls.pipeline.awaitingIa ?? 0;
    if (awaitingIa > 5) {
      alerts.push({
        id: "ia-backlog",
        severity: "warning",
        issue: `${awaitingIa} activities awaiting IA verification`,
        why: "The verification backlog delays accountability and fund close-out.",
        scope: "Country-wide",
        recommendedAction: "Confirm IA capacity with the Impact Assessment lead.",
        actionLabel: "Analytics Pipeline",
        actionHref: "/analytics",
      });
    }
  }

  return alerts.sort((a, b) => {
    const rank = { urgent: 0, warning: 1, watch: 2 };
    return rank[a.severity] - rank[b.severity];
  });
}

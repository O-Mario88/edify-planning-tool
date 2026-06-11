// Adapter: live WeeklyFundRequest store → FundApprovalItem rows the
// /approvals queue renders. The queue card was originally wired to the
// static `fundApprovalQueue` mock; this adapter keeps the row shape
// identical so the UI doesn't move, but pulls from the live store
// the server actions actually mutate (submitFundRequest /
// approveFundRequest / markReadyToDisburse / disburseFundRequest).
//
// PL view scope: SUBMITTED requests assigned to this PL.
// Accountant view scope: APPROVED + READY_TO_DISBURSE across all PLs.

import "server-only";

import { fundRequests as fundRequestsStore } from "@/lib/actions/store";
import type { WeeklyFundRequest, WeeklyFundRequestStatus } from "@/lib/funds/weekly-fund-types";
import type { FundApprovalItem } from "@/lib/fund-approvals-mock";

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

function fmtUgx(amount: number): string {
  if (amount >= 1_000_000) return `UGX ${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `UGX ${(amount / 1_000).toFixed(0)}K`;
  return `UGX ${amount.toLocaleString()}`;
}

const STATUS_LABEL: Partial<Record<WeeklyFundRequestStatus, FundApprovalItem["status"]>> = {
  SUBMITTED:               "Awaiting Approval",
  APPROVED:                "Ready",
  READY_TO_DISBURSE:       "Ready",
  RETURNED_TO_STAFF:       "Returned",
  ACCOUNTABILITY_SUBMITTED:"Needs Review",
  ACCOUNTABILITY_RETURNED: "Returned",
};

type CountsKey = "SchoolVisit" | "PartnerSchoolVisit" | "Cluster" | "TeacherTraining";

function countsFor(req: WeeklyFundRequest) {
  const counts = { visits: 0, partners: 0, clusters: 0, trainings: 0 };
  for (const a of req.activities) {
    const kind = a.kind as CountsKey;
    if (kind === "PartnerSchoolVisit") counts.partners++;
    else if (kind === "Cluster") counts.clusters++;
    else if (kind === "TeacherTraining") counts.trainings++;
    else counts.visits++;
  }
  return counts;
}

function adapt(req: WeeklyFundRequest): FundApprovalItem {
  const status = STATUS_LABEL[req.status] ?? "Awaiting Approval";
  return {
    id:          req.id,
    cceoName:    req.staffName,
    initials:    initialsOf(req.staffName),
    district:    req.district,
    region:      req.countryId ?? "—",
    description: `Week ${req.period.weekOfMonth} · ${req.period.monthLabel}`,
    amount:      fmtUgx(req.requestedAmount.amount),
    status,
    counts:      countsFor(req),
  };
}

// PL queue: requests submitted by CCEOs supervised by this PL plus
// returned-for-review accountability rows the PL needs to clear.
export function liveApprovalsForPl(programLeadId: string): FundApprovalItem[] {
  const rows = fundRequestsStore().filter(
    (r) =>
      r.programLeadId === programLeadId &&
      (r.status === "SUBMITTED" ||
        r.status === "RETURNED_TO_STAFF" ||
        r.status === "ACCOUNTABILITY_SUBMITTED" ||
        r.status === "ACCOUNTABILITY_RETURNED"),
  );
  return rows.map(adapt);
}

// Accountant queue: PL-approved requests waiting on disbursement.
export function liveApprovalsForAccountant(): FundApprovalItem[] {
  const rows = fundRequestsStore().filter(
    (r) =>
      r.status === "APPROVED" ||
      r.status === "READY_TO_DISBURSE" ||
      r.status === "HOLD_NO_FUNDS_AVAILABLE" ||
      r.status === "BLOCKED_PRIOR_OUTSTANDING",
  );
  return rows.map(adapt);
}

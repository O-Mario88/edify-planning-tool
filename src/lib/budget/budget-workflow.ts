// Budget & fund approval workflow — canonical stages for the budget dashboard.
// Field fund requests (live): CCEO → PL via supervision chain, then accountant
// disbursement. Country rollup (CD admin cost → RVP final) is the monthly
// governance path — UI marks live vs upcoming per stage.

import type { EdifyRole } from "@/lib/auth-public";
import type { BeFundRequest } from "@/lib/api/surfaces";

export type WorkflowStageStatus = "complete" | "current" | "pending" | "waiting";

export type BudgetWorkflowStage = {
  id: string;
  label: string;
  detail: string;
  /** Who acts at this stage */
  actorRoles: EdifyRole[];
  /** Whether backend supports this stage today */
  live: boolean;
  status: WorkflowStageStatus;
  /** 0–100 for progress bar */
  progressPct: number;
  statusLabel: string;
  pendingCount?: number;
  actionHref?: string;
  actionLabel?: string;
};

const COUNTRY_ROLES: EdifyRole[] = ["CountryDirector", "RVP", "ProgramAccountant", "ImpactAssessment"];

function isPlanner(role: EdifyRole) {
  return ["CCEO", "CountryProgramLead", "ImpactAssessment", "ProgramAccountant"].includes(role);
}

function countBy(filter: (r: BeFundRequest) => boolean, rows: BeFundRequest[]) {
  return rows.filter(filter).length;
}

/** Build role-aware workflow stages with live fund-request counts. */
export function buildBudgetWorkflow(
  role: EdifyRole,
  opts: {
    activityCount: number;
    costMissingCount: number;
    fundRequests: BeFundRequest[];
  },
): BudgetWorkflowStage[] {
  const { activityCount, costMissingCount, fundRequests: fr } = opts;

  const plQueue = fr.filter(
    (r) => r.status === "submitted" && r.submittedByRole === "CCEO" && r.canReview,
  );
  const plPendingAll = countBy(
    (r) => r.status === "submitted" && r.submittedByRole === "CCEO",
    fr,
  );
  const ownSubmitted = fr.filter((r) => r.isOwn && r.status === "submitted");
  const ownReturned = fr.filter((r) => r.isOwn && r.status === "returned");
  const staffSubmitted = fr.filter(
    (r) =>
      r.status === "submitted" &&
      ["CountryProgramLead", "ImpactAssessment", "ProgramAccountant"].includes(r.submittedByRole as EdifyRole),
  );
  const approvedAwaitingDisburse = fr.filter((r) => r.status === "approved");
  const disbursed = fr.filter((r) => r.status === "disbursed");
  const accountReview = fr.filter((r) => r.canAccountReview);

  const planReady = activityCount > 0 && costMissingCount === 0;
  const planStarted = activityCount > 0;

  // ── Stage 1: Plan & cost ──
  const planStatus: WorkflowStageStatus = !planStarted
    ? role === "CountryDirector" || role === "RVP"
      ? "waiting"
      : "current"
    : costMissingCount > 0
      ? "current"
      : "complete";
  const planPct = !planStarted ? 0 : costMissingCount > 0 ? 45 : 100;

  // ── Stage 2: CCEO → PL ──
  let plStatus: WorkflowStageStatus = "pending";
  if (plPendingAll === 0 && planReady) plStatus = "complete";
  else if (role === "CountryProgramLead" && plQueue.length > 0) plStatus = "current";
  else if (role === "CCEO" && (ownSubmitted.length > 0 || ownReturned.length > 0)) plStatus = "current";
  else if (plPendingAll > 0) plStatus = "waiting";

  // ── Stage 3: PL / IA / Accountant → CD ──
  let cdIntakeStatus: WorkflowStageStatus = "pending";
  if (staffSubmitted.length > 0) cdIntakeStatus = role === "CountryDirector" ? "current" : "waiting";
  else if (plPendingAll === 0 && planReady) cdIntakeStatus = "waiting";

  // ── Stage 4: CD approval + admin ──
  let cdStatus: WorkflowStageStatus = role === "CountryDirector" ? "waiting" : "pending";
  if (role === "CountryDirector" && plPendingAll === 0 && planReady) cdStatus = "current";

  // ── Stage 5: RVP final ──
  let rvpStatus: WorkflowStageStatus = role === "RVP" ? "waiting" : "pending";
  if (role === "RVP") rvpStatus = "current";

  // ── Stage 6: Disbursement ──
  let disbStatus: WorkflowStageStatus = "pending";
  if (approvedAwaitingDisburse.length > 0) {
    disbStatus = role === "ProgramAccountant" ? "current" : "waiting";
  } else if (disbursed.length > 0) {
    disbStatus = "complete";
  }

  const stages: BudgetWorkflowStage[] = [
    {
      id: "plan",
      label: "Plan & cost from catalogue",
      detail: "Staff schedule activities; each line auto-costed from the Country Cost Register.",
      actorRoles: ["CCEO", "CountryProgramLead", "ImpactAssessment", "ProgramAccountant", "Admin"],
      live: true,
      status: planStatus,
      progressPct: planPct,
      statusLabel:
        costMissingCount > 0
          ? `${costMissingCount} activit${costMissingCount === 1 ? "y" : "ies"} missing rates`
          : planReady
            ? "Plan costed and ready"
            : planStarted
              ? "Scheduling in progress"
              : "Schedule activities to begin",
      actionHref: isPlanner(role) ? (role === "CCEO" ? "/my-plan" : "/planning") : "/cost-catalogue",
      actionLabel: costMissingCount > 0 ? "Fix cost gaps" : "Open planning",
    },
    {
      id: "cceo-pl",
      label: "CCEO → Program Lead",
      detail: "CCEO monthly/weekly fund requests route to their supervising Program Lead.",
      actorRoles: ["CCEO", "CountryProgramLead"],
      live: true,
      status: plStatus,
      progressPct: plPendingAll === 0 && planReady ? 100 : plQueue.length > 0 ? 55 : plPendingAll > 0 ? 30 : 0,
      statusLabel:
        plQueue.length > 0
          ? `${plQueue.length} awaiting your review`
          : plPendingAll > 0
            ? `${plPendingAll} with PL queue`
            : ownSubmitted.length > 0
              ? "Submitted — awaiting PL"
              : "No open CCEO requests",
      pendingCount: plPendingAll,
      actionHref: role === "CCEO" ? "/weekly-funds" : "/approvals",
      actionLabel: role === "CountryProgramLead" ? "Review team requests" : "Fund requests",
    },
    {
      id: "staff-cd",
      label: "PL / IA / Accountant → CD",
      detail: "Plans and budgets made by PL, IA, or Accountant consolidate to the Country Director.",
      actorRoles: ["CountryProgramLead", "ImpactAssessment", "ProgramAccountant", "CountryDirector"],
      live: false,
      status: cdIntakeStatus,
      progressPct: staffSubmitted.length > 0 ? 40 : 0,
      statusLabel:
        staffSubmitted.length > 0
          ? `${staffSubmitted.length} staff request(s) pending CD intake`
          : "Routes on country monthly submission (coming)",
      pendingCount: staffSubmitted.length,
      actionHref: "/approvals",
      actionLabel: "Country queue",
    },
    {
      id: "cd-admin",
      label: "CD approval + admin cost",
      detail: "CD approves the country plan & budget and adds administrative costs before RVP review.",
      actorRoles: ["CountryDirector"],
      live: false,
      status: cdStatus,
      progressPct: role === "CountryDirector" ? 50 : 0,
      statusLabel:
        role === "CountryDirector"
          ? "Consolidate teams, add admin lines, submit to RVP"
          : "Awaiting CD country rollup",
      actionHref: "/budget/intelligence",
      actionLabel: "Budget intelligence",
    },
    {
      id: "rvp-final",
      label: "RVP final approval",
      detail: "Regional VP gives final sign-off on the consolidated country budget.",
      actorRoles: ["RVP"],
      live: false,
      status: rvpStatus,
      progressPct: role === "RVP" ? 55 : 0,
      statusLabel: role === "RVP" ? "Review country summary & approve" : "After CD submission",
      actionHref: "/budget/approvals/rvp-queue",
      actionLabel: "RVP queue",
    },
    {
      id: "disburse",
      label: "Accountant disbursement",
      detail: "Program Accountant disburses PL-approved field requests; owner accounts with NetSuite ID.",
      actorRoles: ["ProgramAccountant", "CountryProgramLead", "CCEO"],
      live: true,
      status: disbStatus,
      progressPct: approvedAwaitingDisburse.length > 0 ? 60 : disbursed.length > 0 ? 100 : 0,
      statusLabel:
        approvedAwaitingDisburse.length > 0
          ? `${approvedAwaitingDisburse.length} approved — ready to disburse`
          : accountReview.length > 0
            ? `${accountReview.length} accountability to review`
            : disbursed.length > 0
              ? `${disbursed.length} disbursed this period`
              : "No approved requests waiting",
      pendingCount: approvedAwaitingDisburse.length,
      actionHref: role === "ProgramAccountant" ? "/approvals" : "/weekly-funds",
      actionLabel: role === "ProgramAccountant" ? "Disburse funds" : "Accountability",
    },
  ];

  // Country oversight roles: highlight summary stages, not field planning.
  if (COUNTRY_ROLES.includes(role) && role !== "ImpactAssessment") {
    const plan = stages.find((s) => s.id === "plan")!;
    if (plan.status === "current" && activityCount > 0) plan.status = "complete";
  }

  return stages;
}

/** Map to ApprovalWorkflowStepper shape. */
export function workflowAsStepper(stages: BudgetWorkflowStage[]) {
  return stages.map((s) => ({
    label: s.label,
    status: (s.status === "complete" ? "done" : s.status === "current" ? "current" : "pending") as
      | "done"
      | "current"
      | "pending",
    statusLabel: s.statusLabel,
  }));
}

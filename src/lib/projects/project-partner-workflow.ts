// Project activity execution→payment state machine.
//
// A partner-assigned project activity follows the SAME verified path as any
// partner activity — Assigned → Scheduled → Evidence → Staff Accept →
// Salesforce ID → IA Verify → Accountant Pay — while staying linked to the
// project + school + intervention. Mirrors src/lib/partner/partner-workflow.ts
// conventions (status enum + transition + ROLE_NEXT_STEP) but project-scoped.
//
// Payment is hard-gated: an activity can only be Paid from IAVerified.

export type ProjectWorkflowStatus =
  | "AssignedToPartner"
  | "PartnerScheduled"
  | "AwaitingStaffReview"
  | "SalesforceIdRequired"
  | "SubmittedToIA"
  | "IAVerified"
  | "Paid"
  // branches
  | "ReturnedForCorrection"
  | "Rejected"
  | "ReturnedByIA"
  | "OnHold";

export type ProjectWorkflowAction =
  | "schedule"
  | "submitEvidence"
  | "acceptEvidence"
  | "returnEvidence"
  | "rejectWork"
  | "resubmitEvidence"
  | "enterSalesforceId"
  | "iaVerify"
  | "iaReturn"
  | "clearPayment";

type Transition = { from: ProjectWorkflowStatus[]; to: ProjectWorkflowStatus };

const TRANSITIONS: Record<ProjectWorkflowAction, Transition> = {
  schedule:          { from: ["AssignedToPartner"], to: "PartnerScheduled" },
  submitEvidence:    { from: ["PartnerScheduled"], to: "AwaitingStaffReview" },
  resubmitEvidence:  { from: ["ReturnedForCorrection"], to: "AwaitingStaffReview" },
  acceptEvidence:    { from: ["AwaitingStaffReview"], to: "SalesforceIdRequired" },
  returnEvidence:    { from: ["AwaitingStaffReview"], to: "ReturnedForCorrection" },
  rejectWork:        { from: ["AwaitingStaffReview"], to: "Rejected" },
  enterSalesforceId: { from: ["SalesforceIdRequired", "ReturnedByIA"], to: "SubmittedToIA" },
  iaVerify:          { from: ["SubmittedToIA"], to: "IAVerified" },
  iaReturn:          { from: ["SubmittedToIA"], to: "ReturnedByIA" },
  clearPayment:      { from: ["IAVerified"], to: "Paid" },
};

/** Apply an action. Returns the next status, or null if illegal from `current`. */
export function transition(
  current: ProjectWorkflowStatus,
  action: ProjectWorkflowAction,
): ProjectWorkflowStatus | null {
  const t = TRANSITIONS[action];
  return t && t.from.includes(current) ? t.to : null;
}

// ── Who acts on each status ──

export type ActorKind = "partner" | "staff" | "ia" | "accountant";

const ROLE_KIND: Record<string, ActorKind> = {
  PartnerAdmin: "partner",
  PartnerFieldOfficer: "partner",
  CCEO: "staff",
  CountryProgramLead: "staff",
  ProjectCoordinator: "staff",
  CountryDirector: "staff",
  ImpactAssessment: "ia",
  ProgramAccountant: "accountant",
};

/** Which actor kind owns the next step at each status. */
export const NEXT_ACTOR: Partial<Record<ProjectWorkflowStatus, ActorKind>> = {
  AssignedToPartner: "partner",
  PartnerScheduled: "partner",
  ReturnedForCorrection: "partner",
  AwaitingStaffReview: "staff",
  SalesforceIdRequired: "staff",
  ReturnedByIA: "staff",
  SubmittedToIA: "ia",
  IAVerified: "accountant",
};

const ACTION_KIND: Record<ProjectWorkflowAction, ActorKind> = {
  schedule: "partner",
  submitEvidence: "partner",
  resubmitEvidence: "partner",
  acceptEvidence: "staff",
  returnEvidence: "staff",
  rejectWork: "staff",
  enterSalesforceId: "staff",
  iaVerify: "ia",
  iaReturn: "ia",
  clearPayment: "accountant",
};

/** Can a role (Admin always yes) perform an action? */
export function canPerform(role: string, action: ProjectWorkflowAction): boolean {
  if (role === "Admin") return true;
  return ROLE_KIND[role] === ACTION_KIND[action];
}

/** Actions available to a role at a given status (drives the row buttons). */
export function availableActions(
  status: ProjectWorkflowStatus,
  role: string,
): ProjectWorkflowAction[] {
  return (Object.keys(TRANSITIONS) as ProjectWorkflowAction[]).filter(
    (a) => TRANSITIONS[a].from.includes(status) && canPerform(role, a),
  );
}

// ── Display ──

export const STATUS_LABEL: Record<ProjectWorkflowStatus, string> = {
  AssignedToPartner: "Assigned to partner",
  PartnerScheduled: "Partner scheduled",
  AwaitingStaffReview: "Awaiting staff review",
  SalesforceIdRequired: "Salesforce ID required",
  SubmittedToIA: "Submitted to IA",
  IAVerified: "IA verified — ready for payment",
  Paid: "Paid",
  ReturnedForCorrection: "Returned for correction",
  Rejected: "Rejected",
  ReturnedByIA: "Returned by IA",
  OnHold: "On hold",
};

export const ACTION_LABEL: Record<ProjectWorkflowAction, string> = {
  schedule: "Schedule",
  submitEvidence: "Submit evidence",
  resubmitEvidence: "Resubmit evidence",
  acceptEvidence: "Accept evidence",
  returnEvidence: "Return for correction",
  rejectWork: "Reject work",
  enterSalesforceId: "Enter Salesforce ID",
  iaVerify: "Verify (IA)",
  iaReturn: "Return to staff",
  clearPayment: "Clear payment",
};

export const STATUS_TONE: Record<ProjectWorkflowStatus, "green" | "amber" | "red" | "blue" | "grey"> = {
  AssignedToPartner: "blue",
  PartnerScheduled: "blue",
  AwaitingStaffReview: "amber",
  SalesforceIdRequired: "amber",
  SubmittedToIA: "amber",
  IAVerified: "blue",
  Paid: "green",
  ReturnedForCorrection: "red",
  Rejected: "red",
  ReturnedByIA: "red",
  OnHold: "grey",
};

/** Ordered stages for grouping the pipeline board. */
export const PIPELINE_STAGES: ProjectWorkflowStatus[] = [
  "AssignedToPartner",
  "PartnerScheduled",
  "AwaitingStaffReview",
  "SalesforceIdRequired",
  "SubmittedToIA",
  "IAVerified",
  "Paid",
];

// Unified Activity Record (spec layer #6) — the keystone projection.
//
// The app has THREE working activity stores, each with its own lifecycle:
//   • PlannedActivityRecord  (src/lib/actions/store.ts — server-only)   W3/W5/W6
//   • ClusterMeeting         (src/lib/cluster/cluster-core.ts)          cluster lifecycle
//   • ProjectActivity        (src/lib/projects/project-activities.ts)   special projects
//
// Rather than a risky destructive merge of the proven write paths, this module
// defines ONE read shape — `UnifiedActivity` — plus pure mappers that project
// each store into it. Every downstream layer (next-best-action, workflow health,
// timeline, data-quality, demo readiness) reads UnifiedActivity, so it sees one
// model with one lifecycle while the underlying writes stay exactly as they are.
//
// Pure + client-safe: imports are TYPE-ONLY, so importing this never pulls the
// `server-only` runtime guard from store.ts. The aggregator that actually reads
// the stores lives in `unified-activity-source.ts` (server-only).

import type { PlannedActivityRecord, ActivityKind } from "@/lib/actions/store";
import type { ClusterMeeting } from "@/lib/cluster/cluster-core";
import type { ProjectActivity } from "@/lib/projects/project-activities";

// ── Canonical shape ────────────────────────────────────────────────

export type UnifiedActivitySource = "planned" | "cluster_meeting" | "project";

/** The activity taxonomy the spec calls for — one `type` field across sources. */
export type UnifiedActivityType =
  | "School Visit"
  | "Coaching Visit"
  | "Follow-Up Visit"
  | "Training"
  | "Cluster Meeting"
  | "Cluster Training"
  | "SIT"
  | "SSA Collection"
  | "Core Visit"
  | "Core Training"
  | "Partner Visit"
  | "Partner Training"
  | "Project Visit"
  | "Project Training"
  | "Other";

export type DeliveryMode = "staff" | "partner";

export type IaStatus = "none" | "submitted" | "confirmed" | "returned";
export type PaymentStatus = "none" | "pending" | "cleared";

/**
 * The single canonical lifecycle every activity is projected onto. This is the
 * spine of the Next-Best-Action engine and the Workflow Health Monitor: each
 * stage implies exactly one next action and one "stuck" condition.
 */
export type UnifiedActivityStage =
  | "planned" // scheduled, not yet delivered
  | "in_progress"
  | "evidence_pending" // delivered, evidence not uploaded
  | "salesforce_pending" // evidence ok, Salesforce ID missing
  | "ia_pending" // submitted to IA, awaiting confirmation
  | "ia_returned" // IA bounced it back
  | "payment_pending" // IA confirmed, payment/accountability not cleared
  | "closed" // paid / accountability closed → completed log
  | "cancelled"
  | "deferred";

export type UnifiedActivity = {
  id: string;
  source: UnifiedActivitySource;
  type: UnifiedActivityType;
  title: string;

  // Anchors — at least one of these is set.
  schoolId?: string;
  schoolName?: string;
  clusterId?: string;
  projectId?: string;

  // Provenance.
  recommendationSource?: string; // why this activity exists (SSA area, cluster cycle…)
  intervention?: string;

  // Ownership / delivery.
  assignedToId?: string;
  assignedToName?: string;
  deliveryMode: DeliveryMode;
  partnerName?: string;

  // Schedule — an exact date when known, else a period label (week/month).
  scheduledDate?: string;
  schedulePeriod?: string;

  // Money.
  costCents?: number;
  hasCost: boolean;
  budgetLineId?: string;

  // Evidence + verification + payment.
  hasEvidence: boolean;
  salesforceId?: string;
  iaStatus: IaStatus;
  paymentStatus: PaymentStatus;
  netsuiteExpenseId?: string;

  // Canonical lifecycle + raw status for display.
  stage: UnifiedActivityStage;
  finalStatus: string;

  createdAt?: string;
  updatedAt?: string;
};

export const STAGE_LABEL: Record<UnifiedActivityStage, string> = {
  planned: "Planned",
  in_progress: "In progress",
  evidence_pending: "Evidence required",
  salesforce_pending: "Salesforce ID required",
  ia_pending: "Awaiting IA verification",
  ia_returned: "Returned by IA",
  payment_pending: "Payment / accountability pending",
  closed: "Completed & closed",
  cancelled: "Cancelled",
  deferred: "Deferred",
};

/** Lifecycle progression order (cancelled/deferred sit outside the happy path). */
export const STAGE_ORDER: UnifiedActivityStage[] = [
  "planned",
  "in_progress",
  "evidence_pending",
  "salesforce_pending",
  "ia_pending",
  "ia_returned",
  "payment_pending",
  "closed",
];

/** Open = still needs someone to act (everything before closed, minus dead ends). */
export function isOpenActivity(a: UnifiedActivity): boolean {
  return a.stage !== "closed" && a.stage !== "cancelled" && a.stage !== "deferred";
}

// ── PlannedActivity → Unified ──────────────────────────────────────

const PLANNED_TYPE: Record<ActivityKind, UnifiedActivityType> = {
  CLUSTER_TRAINING: "Training",
  IN_SCHOOL_COACHING: "Coaching Visit",
  SCHOOL_VISIT: "School Visit",
  SSA_FOLLOW_UP: "Follow-Up Visit",
  HANDOVER_MEETING: "School Visit",
  LESSON_OBSERVATION: "School Visit",
  PARTNER_FOLLOW_UP: "Partner Visit",
  TRAINING_FOLLOW_UP: "Follow-Up Visit",
  DATA_COLLECTION: "SSA Collection",
  COURTESY_VISIT: "School Visit",
};

export function fromPlannedActivity(
  a: PlannedActivityRecord,
  opts: { hasEvidence?: boolean } = {},
): UnifiedActivity {
  const hasEvidence = opts.hasEvidence ?? false;
  let stage: UnifiedActivityStage;
  let iaStatus: IaStatus = "none";
  let paymentStatus: PaymentStatus = "none";

  switch (a.status) {
    case "Planned":
    case "Draft":
      stage = "planned";
      break;
    case "SalesforceIdPending":
      stage = "salesforce_pending";
      break;
    case "Completed":
      // Evidence → Salesforce ID → IA. Use the available signals to place it.
      if (!hasEvidence) stage = "evidence_pending";
      else if (!a.salesforceId) stage = "salesforce_pending";
      else stage = "ia_pending";
      break;
    case "SubmittedForVerification":
      stage = "ia_pending";
      iaStatus = "submitted";
      break;
    case "Verified":
      stage = "payment_pending";
      iaStatus = "confirmed";
      paymentStatus = "pending";
      break;
    case "AccountabilityClosed":
      stage = "closed";
      iaStatus = "confirmed";
      paymentStatus = "cleared";
      break;
    case "Returned":
      stage = "ia_returned";
      iaStatus = "returned";
      break;
    case "Cancelled":
      stage = "cancelled";
      break;
    case "Deferred":
      stage = "deferred";
      break;
    default:
      stage = "planned";
  }

  return {
    id: a.id,
    source: "planned",
    type: PLANNED_TYPE[a.kind] ?? "Other",
    title: a.title,
    schoolId: a.schoolId,
    schoolName: a.schoolName,
    recommendationSource: a.interventionArea ? `SSA: ${a.interventionArea}` : undefined,
    intervention: a.interventionArea,
    assignedToId: a.assigneeId,
    deliveryMode: a.deliveryType ?? "staff",
    partnerName: a.partnerName,
    scheduledDate: a.scheduledDate,
    schedulePeriod: a.scheduledDate ? undefined : `Week ${a.weekOfMonth}`,
    costCents: a.estCostCents,
    hasCost: (a.estCostCents ?? 0) > 0,
    budgetLineId: a.planId,
    hasEvidence,
    salesforceId: a.salesforceId,
    iaStatus,
    paymentStatus,
    netsuiteExpenseId: a.netsuiteExpenseId,
    stage,
    finalStatus: a.status,
    createdAt: a.createdAt,
    updatedAt: a.updatedAt,
  };
}

// ── ClusterMeeting → Unified ───────────────────────────────────────

const CLUSTER_TYPE: Record<ClusterMeeting["kind"], UnifiedActivityType> = {
  first_meeting: "Cluster Meeting",
  second_meeting: "Cluster Meeting",
  third_meeting: "Cluster Meeting",
  follow_up: "Cluster Meeting",
  sit: "SIT",
  training: "Cluster Training",
};

export function fromClusterMeeting(m: ClusterMeeting): UnifiedActivity {
  let stage: UnifiedActivityStage;
  let iaStatus: IaStatus = "none";
  let paymentStatus: PaymentStatus = "none";

  switch (m.status) {
    case "Scheduled":
      stage = "planned";
      break;
    case "Awaiting IA":
      stage = "ia_pending";
      iaStatus = "submitted";
      break;
    case "IA Confirmed":
      stage = "payment_pending";
      iaStatus = "confirmed";
      paymentStatus = "pending";
      break;
    case "Paid":
    case "Closed":
      stage = "closed";
      iaStatus = "confirmed";
      paymentStatus = "cleared";
      break;
    case "Returned":
      stage = "ia_returned";
      iaStatus = "returned";
      break;
    default:
      stage = "planned";
  }

  return {
    id: m.id,
    source: "cluster_meeting",
    type: CLUSTER_TYPE[m.kind] ?? "Cluster Meeting",
    title: `${CLUSTER_TYPE[m.kind] === "SIT" ? "School Improvement Training" : "Cluster activity"} — ${m.clusterId}`,
    clusterId: m.clusterId,
    recommendationSource: "Cluster cycle",
    assignedToId: m.scheduledBy,
    assignedToName: m.scheduledBy,
    deliveryMode: m.organizer === "partner" ? "partner" : "staff",
    scheduledDate: m.actualDate ?? m.date,
    costCents: undefined,
    hasCost: false, // cluster meetings are not costed line-items in the engine
    hasEvidence: !!(m.evidenceUploaded || m.minutesText || m.attendanceFileName),
    salesforceId: m.salesforceTrainingId,
    iaStatus,
    paymentStatus,
    netsuiteExpenseId: m.netsuiteExpenseId,
    stage,
    finalStatus: m.status,
    createdAt: m.createdAt,
    updatedAt: m.completedAt ?? m.createdAt,
  };
}

// ── ProjectActivity → Unified ──────────────────────────────────────

export function fromProjectActivity(a: ProjectActivity): UnifiedActivity {
  const isTraining =
    a.activityType === "Project Training" || a.activityType === "Project Cluster Session";

  let stage: UnifiedActivityStage;
  let iaStatus: IaStatus = "none";
  let paymentStatus: PaymentStatus = "none";

  if (a.status === "Cancelled") {
    stage = "cancelled";
  } else if (a.workflowStatus === "Paid" || a.paymentRef) {
    stage = "closed";
    iaStatus = "confirmed";
    paymentStatus = "cleared";
  } else if (a.iaVerificationStatus === "Confirmed") {
    stage = "payment_pending";
    iaStatus = "confirmed";
    paymentStatus = "pending";
  } else if (a.iaVerificationStatus === "Submitted") {
    stage = "ia_pending";
    iaStatus = "submitted";
  } else if (a.iaVerificationStatus === "Returned") {
    stage = "ia_returned";
    iaStatus = "returned";
  } else if (a.status === "Completed") {
    if (a.evidenceStatus === "Pending" || a.evidenceStatus === "Not Required") {
      stage = "evidence_pending";
    } else if (!a.salesforceActivityId) {
      stage = "salesforce_pending";
    } else {
      stage = "ia_pending";
    }
  } else if (a.status === "In Progress") {
    stage = "in_progress";
  } else {
    stage = "planned";
  }

  return {
    id: a.id,
    source: "project",
    type: isTraining ? "Project Training" : "Project Visit",
    title: `${a.activityType} — ${a.schoolId ?? a.clusterId ?? a.projectId}`,
    schoolId: a.schoolId,
    clusterId: a.clusterId,
    projectId: a.projectId,
    recommendationSource: a.interventionId ? `Project: ${a.interventionId}` : "Special project",
    intervention: a.interventionId,
    assignedToId: a.staffId ?? a.partnerId,
    assignedToName: a.staffName ?? a.partnerName,
    deliveryMode: a.deliveryType,
    partnerName: a.partnerName,
    scheduledDate: a.scheduledDate,
    schedulePeriod: a.scheduledDate ? undefined : (a.plannedWeek ?? a.plannedMonth),
    costCents: a.paymentAmount,
    hasCost: a.paymentAmount != null && a.paymentAmount > 0,
    budgetLineId: a.paymentRequestId,
    hasEvidence: a.evidenceStatus === "Submitted" || a.evidenceStatus === "Verified",
    salesforceId: a.salesforceActivityId,
    iaStatus,
    paymentStatus,
    stage,
    finalStatus: a.status,
    createdAt: a.createdAt,
    updatedAt: a.updatedAt,
  };
}

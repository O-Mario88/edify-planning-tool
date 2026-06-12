// Next-Best-Action engine (spec layer #1).
//
// "Every record has one clear next action. A user should never ask: what do I do
// now?" The school gate (cluster → SSA → plan) already exists in
// planning/school-next-action.ts; this module extends the SAME idea across the
// FULL pipeline by reading the Unified Activity stage (layer #6), and unifies the
// answer for any record type — activity, school, cluster, partner — so every
// surface (dashboard, notifications, planning, school/cluster profile, partner
// page, My Plan) shows the same single next step.
//
// Pure + client-safe. The canonical pipeline:
//   no cluster → Assign to Cluster
//   no SSA     → Schedule SSA / SIT
//   has SSA    → Plan recommended visit/training
//   scheduled  → Start Activity
//   completed  → Upload Evidence
//   partner ev → Staff Review
//   confirmed  → Enter Salesforce ID
//   SF ID      → Send to IA
//   IA ok      → Accountant Clear Payment
//   paid       → Completed Log

import {
  isOpenActivity,
  type UnifiedActivity,
  type UnifiedActivityStage,
} from "@/lib/activity/unified-activity";
import {
  resolveSchoolNextAction,
  schoolActionHref,
  type SchoolStatusInput,
} from "@/lib/planning/school-next-action";

/** Who is on the hook for the next step. Drives "is this MY action?" filtering. */
export type NextActionActor =
  | "owner" // the staff/partner who delivers the activity
  | "reviewer" // staff confirms partner evidence
  | "ia" // Impact Assessment verifies
  | "accountant" // clears payment / records accountability
  | "none";

export type NextAction = {
  key: string;
  label: string;
  actor: NextActionActor;
  reason: string;
  href?: string;
  /** Higher = more pressing. Used to pick THE one action from a set. */
  urgency: number;
  /** True once the record is in the completed log / dead-ended. */
  done?: boolean;
};

// ── Per-activity next action ───────────────────────────────────────

const STAGE_URGENCY: Record<UnifiedActivityStage, number> = {
  ia_returned: 100, // bounced back — unblock first
  payment_pending: 80,
  ia_pending: 70,
  salesforce_pending: 60,
  evidence_pending: 50,
  in_progress: 40,
  planned: 30,
  deferred: 5,
  cancelled: 1,
  closed: 0,
};

/** The single next step for one activity, anywhere in the pipeline. */
export function activityNextAction(a: UnifiedActivity): NextAction {
  const urgency = STAGE_URGENCY[a.stage];
  switch (a.stage) {
    case "planned":
      return {
        key: "start_activity",
        label: "Start activity",
        actor: "owner",
        reason: "Scheduled — deliver it, then capture evidence.",
        href: "/my-plan",
        urgency,
      };
    case "in_progress":
      return {
        key: "complete_activity",
        label: "Mark complete",
        actor: "owner",
        reason: "In progress — close it out and upload evidence.",
        href: "/my-plan",
        urgency,
      };
    case "evidence_pending":
      return a.deliveryMode === "partner"
        ? {
            key: "partner_upload_evidence",
            label: "Upload evidence",
            actor: "owner",
            reason: "Delivered by partner — attendance/evidence still needed.",
            href: "/evidence",
            urgency,
          }
        : {
            key: "upload_evidence",
            label: "Upload evidence",
            actor: "owner",
            reason: "Completed — upload the attendance/visit evidence.",
            href: "/evidence",
            urgency,
          };
    case "salesforce_pending":
      return {
        key: "enter_salesforce_id",
        label: "Enter Salesforce ID",
        actor: a.deliveryMode === "partner" ? "reviewer" : "owner",
        reason:
          a.deliveryMode === "partner"
            ? "Evidence in — review it and enter the Salesforce ID."
            : "Evidence in — enter the exact Salesforce activity ID.",
        href: "/evidence",
        urgency,
      };
    case "ia_pending":
      return {
        key: "ia_verify",
        label: "IA verify",
        actor: "ia",
        reason: "Salesforce ID entered — awaiting IA confirmation.",
        href: "/data-verification",
        urgency,
      };
    case "ia_returned":
      return {
        key: "fix_resubmit",
        label: "Fix & resubmit",
        actor: "owner",
        reason: "IA returned it — correct the issue and resubmit.",
        href: "/evidence",
        urgency,
      };
    case "payment_pending":
      return {
        key: "clear_payment",
        label: a.deliveryMode === "partner" ? "Clear payment" : "Record accountability",
        actor: "accountant",
        reason:
          a.deliveryMode === "partner"
            ? "IA confirmed — clear the partner payment."
            : "IA confirmed — record NetSuite accountability.",
        href: a.deliveryMode === "partner" ? "/disbursements" : "/dashboards/accountant",
        urgency,
      };
    case "deferred":
      return {
        key: "deferred",
        label: "Deferred",
        actor: "none",
        reason: "Deferred — not happening this period.",
        urgency,
        done: true,
      };
    case "cancelled":
      return {
        key: "cancelled",
        label: "Cancelled",
        actor: "none",
        reason: "Cancelled.",
        urgency,
        done: true,
      };
    case "closed":
    default:
      return {
        key: "closed",
        label: "In completed log",
        actor: "none",
        reason: "Verified and paid — in the completed log.",
        urgency,
        done: true,
      };
  }
}

/** Pick the single most pressing next action across a set of activities. */
export function topActivityNextAction(list: UnifiedActivity[]): NextAction | null {
  const open = list.filter(isOpenActivity);
  if (open.length === 0) return null;
  return open
    .map(activityNextAction)
    .sort((a, b) => b.urgency - a.urgency)[0];
}

// ── Per-school next action (gate → activity pipeline) ──────────────

export type SchoolNextActionResult = NextAction & {
  /** When the school is still gated (cluster/SSA), the blocking reason. */
  gated: boolean;
};

/**
 * The one next action for a school: the planning gate (cluster → SSA → plan) if
 * it isn't planning-ready, otherwise the most pressing step among its in-flight
 * activities, otherwise "plan recommended support".
 */
export function nextActionForSchool(
  school: SchoolStatusInput & { schoolId: string },
  activities: UnifiedActivity[],
): SchoolNextActionResult {
  const gate = resolveSchoolNextAction(school);
  if (gate.blockingGate) {
    return {
      key: gate.actionType,
      label: gate.label,
      actor: "owner",
      reason: gate.reason,
      href: schoolActionHref(school.schoolId, gate.view),
      urgency: 90,
      gated: true,
    };
  }
  const top = topActivityNextAction(activities);
  if (top) return { ...top, gated: false };
  // Planning-ready, nothing in flight → plan the recommended support.
  return {
    key: gate.actionType,
    label: gate.label,
    actor: "owner",
    reason: gate.reason,
    href: schoolActionHref(school.schoolId, gate.view),
    urgency: 30,
    gated: false,
  };
}

// ── Per-cluster next action ────────────────────────────────────────

export function nextActionForCluster(
  opts: { hasSchools: boolean; hasScheduledCycle: boolean },
  activities: UnifiedActivity[],
): NextAction {
  if (!opts.hasSchools) {
    return {
      key: "cluster_add_schools",
      label: "Add schools",
      actor: "owner",
      reason: "Cluster has no member schools yet.",
      href: "/clusters",
      urgency: 85,
    };
  }
  const top = topActivityNextAction(activities);
  if (top) return top;
  if (!opts.hasScheduledCycle) {
    return {
      key: "cluster_schedule_meeting",
      label: "Schedule meeting",
      actor: "owner",
      reason: "No cluster meeting scheduled — start the cycle.",
      href: "/clusters",
      urgency: 55,
    };
  }
  return {
    key: "cluster_idle",
    label: "Up to date",
    actor: "none",
    reason: "All cluster activities are closed.",
    urgency: 0,
    done: true,
  };
}

// ── Per-partner next action ────────────────────────────────────────

/** The partner's most pressing step: deliver/upload evidence on assigned work. */
export function nextActionForPartner(activities: UnifiedActivity[]): NextAction {
  const top = topActivityNextAction(
    activities.filter((a) => a.deliveryMode === "partner"),
  );
  return (
    top ?? {
      key: "partner_idle",
      label: "No pending work",
      actor: "none",
      reason: "No partner-delivered activities awaiting action.",
      urgency: 0,
      done: true,
    }
  );
}

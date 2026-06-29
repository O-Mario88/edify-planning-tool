// My Plan sections — the spec §10 derivation engine for the CCEO's /my-plan.
//
// Pure functions: normalize an activity (backend BeActivity OR in-memory
// store PlannedActivityRecord) into a MyPlanItem, then bucket the items into
// the six sections:
//
//   Due Today · Planned This Week · Planned This Month · Planned This Quarter ·
//   Waiting on Me · Rescheduled / Needs Attention
//
// Precedence (first match wins):
//   1. Waiting on Me        — blocked on the CCEO: Salesforce ID entry,
//                             evidence upload, returned items.
//   2. Rescheduled / Needs Attention — any rescheduled item (the slip-limit
//                             engine flags ≥ RESCHEDULE_SLIP_LIMIT moves) and
//                             deferred items that need a decision.
//   3. Due Today            — scheduled today or already overdue.
//   4. Planned This Week    — scheduled in the remainder of the current week.
//   5. Planned This Month   — scheduled later this calendar month (or visits
//                             whose week-of-month falls after the current one).
//   6. Planned This Quarter — scheduled after this month but within the next
//                             three calendar months (rest of the current FY
//                             quarter). Anything further out also lands here
//                             rather than disappearing, so no scheduled work
//                             is ever silently dropped.
//
// Completed/closed/cancelled work NEVER appears here — it lives in the
// Completed Activities Log (/completed-activities).

import type { BeActivity } from "@/lib/api/surfaces";
import type { PlannedActivityRecord } from "@/lib/actions/store";
import type { WeeklyFundRequest } from "@/lib/funds/weekly-fund-types";
import { RESCHEDULE_SLIP_LIMIT, classifyActivityKind } from "@/lib/planning/planning-capacity";
import type { ClusterMeeting } from "@/lib/cluster/cluster-core";
import { clusterById, CLUSTER_MEETING_LABEL } from "@/lib/cluster/cluster-core";

// ── Types ────────────────────────────────────────────────────────────

export type MyPlanFunding = "Not Requested" | "Requested" | "Approved" | "Disbursed" | "Accounted" | "Returned";
export type MyPlanWaiting = "salesforceId" | "evidence" | "returned";
export type MyPlanNextAction = "complete" | "reschedule" | "uploadEvidence" | "enterSalesforceId";
export type MyPlanSectionKey = "dueToday" | "thisWeek" | "thisMonth" | "thisQuarter" | "waitingOnMe" | "needsAttention";

export type MyPlanItem = {
  id: string;
  /** Which write path the row action must use. */
  source: "backend" | "store";
  /** "Cluster training", "School visit", … */
  typeLabel: string;
  /** School / cluster / project the activity belongs to. */
  entityName: string;
  /** Trainings & cluster meetings carry an exact date; visits show week/month. */
  exactDate: boolean;
  dateIso?: string;
  weekOfMonth?: number;
  plannedMonth?: number;
  costCents?: number;
  funding?: MyPlanFunding;
  statusLabel: string;
  waitingOn?: MyPlanWaiting;
  rescheduleCount: number;
  atSlipLimit: boolean;
  lastReason?: string;
  /** The ONE next-action button for the card. */
  nextAction: MyPlanNextAction;
  /** Raw backend status — drives the two-step Complete workflow. */
  backendStatus?: string;
  activityPurposeText?: string;
  purposeType?: string;
  focusIntervention?: string;
  secondaryFocusInterventions?: string[];
  expectedOutcome?: string;
};

export type MyPlanSection = {
  key: MyPlanSectionKey;
  title: string;
  /** One-line empty state copy. */
  emptyCopy: string;
  items: MyPlanItem[];
};

// ── Activity-type labels ─────────────────────────────────────────────

// Backend ActivityType → display label.
const BE_TITLE: Record<string, string> = {
  school_visit: "School visit", follow_up_visit: "Follow-up visit", coaching_visit: "Coaching visit",
  in_school_support: "In-school support", training: "Training", school_improvement_training: "Improvement training",
  cluster_meeting: "Cluster meeting", cluster_training: "Cluster training", ssa_activity: "SSA activity",
  project_activity: "Project activity", core_visit: "Core visit", core_training: "Core training",
};

// Store ActivityKind → display label.
const STORE_TITLE: Record<string, string> = {
  SCHOOL_VISIT: "School visit", IN_SCHOOL_COACHING: "In-school coaching",
  SSA_FOLLOW_UP: "SSA follow-up visit", COURTESY_VISIT: "Courtesy visit",
  CLUSTER_TRAINING: "Cluster training", TRAINING_FOLLOW_UP: "Training follow-up",
  HANDOVER_MEETING: "Cluster meeting", LESSON_OBSERVATION: "Lesson observation",
  PARTNER_FOLLOW_UP: "Partner follow-up", DATA_COLLECTION: "Data collection",
};

// Trainings + cluster meetings are date-exact; visits are week/month-grained.
const BE_EXACT_DATE = new Set([
  "training", "school_improvement_training", "cluster_training", "cluster_meeting", "core_training",
]);

// ── Status vocabulary ────────────────────────────────────────────────

// Backend statuses that mean "done / out of My Plan" (they render in the
// Completed Activities Log instead).
const BE_HIDDEN = new Set([
  "completed", "awaiting_ia_verification", "ia_verified", "evidence_accepted",
  "accountant_confirmed", "cancelled", "submitted_to_pl",
]);

// Store statuses that are terminal for My Plan. SubmittedForVerification is
// waiting on the IA — not on the CCEO — so it leaves the plan too.
const STORE_HIDDEN = new Set([
  "Completed", "SubmittedForVerification", "Verified", "AccountabilityClosed", "Cancelled",
]);

const titleCase = (s: string) => s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

// ── Funding derivation ───────────────────────────────────────────────

// WeeklyFundRequestStatus → the three-stage funding pill.
function fundingFromWfrStatus(s: WeeklyFundRequest["status"]): MyPlanFunding | undefined {
  switch (s) {
    case "AUTO_GENERATED": case "DRAFT": case "SUBMITTED": case "RETURNED_TO_STAFF":
      return "Requested";
    case "APPROVED": case "HOLD_NO_FUNDS_AVAILABLE": case "BLOCKED_PRIOR_OUTSTANDING": case "READY_TO_DISBURSE":
      return "Approved";
    case "DISBURSED": case "RECEIVED": case "IN_USE":
    case "ACCOUNTABILITY_SUBMITTED": case "ACCOUNTABILITY_RETURNED": case "ACCOUNTABILITY_APPROVED":
    case "CLOSED": case "ARCHIVED":
      return "Disbursed";
    default:
      return undefined; // CANCELLED — no live funding
  }
}

/** activityId → funding stage, from the weekly-fund pipeline. The generator
 *  sets `originPlanLineId` (and the line id) to the source activity id. */
export function buildFundingByActivity(reqs: WeeklyFundRequest[]): Map<string, MyPlanFunding> {
  const map = new Map<string, MyPlanFunding>();
  for (const req of reqs) {
    const funding = fundingFromWfrStatus(req.status);
    if (!funding) continue;
    for (const line of req.activities) {
      if (line.status === "Cancelled") continue;
      map.set(line.originPlanLineId, funding);
      map.set(line.id, funding);
    }
  }
  return map;
}

// Backend PaymentStatus enum → funding pill. The old mapping used keys that
// don't exist on the enum (requested/pending/approved/cleared/disbursed), so the
// pill NEVER populated in backend mode. Mapped to the real values here.
function fundingFromPaymentStatus(s?: string): MyPlanFunding | undefined {
  switch ((s ?? "").toLowerCase()) {
    case "pending_ia": case "ia_confirmed": case "pl_approval_required": return "Requested";
    case "pl_approved": return "Approved";
    case "accountant_cleared": case "paid": return "Disbursed";
    case "netsuite_accountability": case "closed": return "Accounted";
    case "rejected": return "Returned";
    default: return undefined; // 'none' = not yet in the fund pipeline
  }
}

// Fund-request status → the PRE-execution funding pill (before any payment).
function fundingFromRequestStatus(s: string): MyPlanFunding | undefined {
  switch (s) {
    case "submitted": return "Requested";
    case "approved": return "Approved";
    case "disbursed": return "Disbursed";
    case "returned": case "rejected": return "Returned";
    default: return undefined;
  }
}

/** periodKey ("FY-M3") → funding pill, from the caller's fund requests, so a
 *  PLANNED activity shows whether its month's funds are requested / approved /
 *  disbursed (the pre-execution money signal that the payment status can't give
 *  until after IA verification). Furthest-along status wins per period. */
export function buildFundingByPeriod(requests: { periodKey: string; status: string }[]): Map<string, MyPlanFunding> {
  const rank: Record<string, number> = { Returned: 0, Requested: 1, Approved: 2, Disbursed: 3 };
  const map = new Map<string, MyPlanFunding>();
  for (const r of requests) {
    const f = fundingFromRequestStatus(r.status);
    if (!f) continue;
    const cur = map.get(r.periodKey);
    if (!cur || (rank[f] ?? 0) > (rank[cur] ?? 0)) map.set(r.periodKey, f);
  }
  return map;
}

// ── Next-action resolution (the ONE button per card) ────────────────

function resolveNextAction(i: Pick<MyPlanItem, "waitingOn" | "atSlipLimit" | "dateIso" | "statusLabel">, todayIso: string): MyPlanNextAction {
  if (i.waitingOn === "salesforceId") return "enterSalesforceId";
  if (i.waitingOn === "evidence") return "uploadEvidence";
  if (i.waitingOn === "returned") return "complete"; // fix + resubmit
  if (i.atSlipLimit) return "complete"; // no more moves — deliver it
  if (i.statusLabel === "Deferred") return "reschedule"; // a reschedule revives a deferred item
  if (i.dateIso && i.dateIso.slice(0, 10) <= todayIso) return "complete"; // due/overdue
  return "reschedule"; // future-dated: the date move is the live action
}

// ── Normalizers ──────────────────────────────────────────────────────

export function fromBeActivity(a: BeActivity, todayIso: string, fundingByPeriod?: Map<string, MyPlanFunding>): MyPlanItem | null {
  if (BE_HIDDEN.has(a.status)) return null;
  const ev = (a.evidenceStatus ?? "").toLowerCase();
  const waitingOn: MyPlanWaiting | undefined =
    a.status === "completion_started" || a.status === "in_progress" ? "evidence"
    : a.status === "salesforce_id_required" ? "salesforceId"
    : a.status === "returned_by_pl" || a.status === "returned" ? "returned"
    : ev === "required" || ev === "missing" || ev === "rejected" ? "evidence"
    : (a.status === "evidence_uploaded" || a.status === "evidence_accepted") && !a.salesforceActivityId ? "salesforceId"
    : undefined;
  const rescheduleCount = a.rescheduleCount ?? 0;
  // Resolve the activity's calendar month (1-12) for the funding lookup: an exact
  // scheduledDate wins, else the week/month-grained planned month (visits carry
  // plannedMonth, not a date). Keep getMonth (local) to match the fund-request
  // periodKey built from the same source on the page caller.
  const periodMonth = a.scheduledDate
    ? new Date(a.scheduledDate).getMonth() + 1
    : (a.plannedMonth ?? a.month ?? undefined);
  const item: MyPlanItem = {
    id: a.id,
    source: "backend",
    typeLabel: BE_TITLE[a.activityType] ?? titleCase(a.activityType),
    entityName: a.school?.name ?? (a as any).schoolName ?? a.cluster?.name ?? (a as any).clusterName ?? "—",
    exactDate: BE_EXACT_DATE.has(a.activityType),
    dateIso: a.scheduledDate ?? undefined,
    weekOfMonth: a.plannedWeek ?? a.week ?? undefined,
    plannedMonth: periodMonth,
    costCents: a.estCostCents ?? undefined,
    // Funding pill: the post-execution PAYMENT status if present, else the
    // PRE-execution fund-request status for the activity's month (date OR
    // planned-month), else "Not Requested" so the planner sees un-funded
    // planned work. Month-grained visits now resolve their period too.
    funding:
      fundingFromPaymentStatus(a.paymentStatus) ??
      (periodMonth && a.fy ? fundingByPeriod?.get(`${a.fy}-M${periodMonth}`) : undefined) ??
      (periodMonth ? "Not Requested" : undefined),
    statusLabel: titleCase(a.status),
    waitingOn,
    rescheduleCount,
    atSlipLimit: rescheduleCount >= RESCHEDULE_SLIP_LIMIT,
    lastReason: a.lastReason ?? undefined,
    nextAction: "reschedule",
    backendStatus: a.status,
    activityPurposeText: a.activityPurposeText ?? undefined,
    purposeType: a.purposeType ?? undefined,
    focusIntervention: a.focusIntervention ?? undefined,
    secondaryFocusInterventions: a.secondaryFocusInterventions ?? undefined,
    expectedOutcome: a.expectedOutcome ?? undefined,
  };
  item.nextAction = resolveNextAction(item, todayIso);
  return item;
}


/** In-memory store row → MyPlanItem. Returns null for completed/closed rows. */
export function fromStoreActivity(
  a: PlannedActivityRecord,
  fundingByActivity: Map<string, MyPlanFunding>,
  todayIso: string,
): MyPlanItem | null {
  if (STORE_HIDDEN.has(a.status)) return null;
  const waitingOn: MyPlanWaiting | undefined =
    a.status === "SalesforceIdPending" ? "salesforceId"
    : a.status === "Returned" ? "returned"
    : undefined;
  const rescheduleCount = a.rescheduleCount ?? 0;
  const item: MyPlanItem = {
    id: a.id,
    source: "store",
    typeLabel: STORE_TITLE[a.kind] ?? "Activity",
    entityName: a.schoolName ?? a.title,
    exactDate: classifyActivityKind(a.kind) === "training",
    dateIso: a.scheduledDate,
    weekOfMonth: a.weekOfMonth,
    costCents: a.estCostCents || undefined,
    funding: fundingByActivity.get(a.id),
    statusLabel: a.status,
    waitingOn,
    rescheduleCount,
    atSlipLimit: rescheduleCount >= RESCHEDULE_SLIP_LIMIT,
    lastReason: a.lastReason,
    nextAction: "reschedule",
  };
  item.nextAction = resolveNextAction(item, todayIso);
  return item;
}

/** Cluster meeting → MyPlanItem for My Plan inclusion. */
export function fromClusterMeeting(m: ClusterMeeting, todayIso: string): MyPlanItem | null {
  const cluster = clusterById(m.clusterId);
  if (!cluster) return null;
  const waitingOn: MyPlanWaiting | undefined =
    m.status === "Returned" ? "returned" : undefined;
  const item: MyPlanItem = {
    id: m.id,
    source: "store",
    typeLabel: CLUSTER_MEETING_LABEL[m.kind] ?? "Cluster activity",
    entityName: cluster.name,
    exactDate: true, // cluster meetings always have an exact date
    dateIso: m.date,
    costCents: undefined,
    funding: undefined,
    statusLabel: m.status,
    waitingOn,
    rescheduleCount: 0,
    atSlipLimit: false,
    lastReason: m.returnedReason,
    nextAction: "reschedule",
  };
  item.nextAction = resolveNextAction(item, todayIso);
  return item;
}

// ── Sectioning ───────────────────────────────────────────────────────

const isoDay = (d: Date) => {
  try {
    return d.toISOString().slice(0, 10);
  } catch {
    return new Date().toISOString().slice(0, 10);
  }
};

/** Monday-start week bounds around `today`, as ISO yyyy-mm-dd strings. */
function weekEndIso(today: Date): string {
  const d = new Date(today);
  const dow = (d.getUTCDay() + 6) % 7; // Mon=0 … Sun=6
  d.setUTCDate(d.getUTCDate() + (6 - dow));
  return isoDay(d);
}

export function sectionMyPlan(items: MyPlanItem[], today: Date = new Date()): MyPlanSection[] {
  const todayIso = isoDay(today);
  const weekEnd = weekEndIso(today);

  // Last day of current month
  const lastDay = new Date(today.getFullYear(), today.getMonth() + 1, 0);
  const monthEnd = isoDay(lastDay);

  const buckets: Record<MyPlanSectionKey, MyPlanItem[]> = {
    dueToday: [], thisWeek: [], thisMonth: [], thisQuarter: [], waitingOnMe: [], needsAttention: [],
  };

  const todayDate = today.getDate();
  const currentWeekOfMonth = Math.min(4, Math.ceil(todayDate / 7));
  const currentMonth = today.getMonth() + 1;

  for (const i of items) {
    const date = i.dateIso?.slice(0, 10);
    if (i.waitingOn) {
      buckets.waitingOnMe.push(i);
    } else if (i.rescheduleCount > 0 || i.statusLabel === "Deferred" || i.statusLabel === "Rescheduled") {
      buckets.needsAttention.push(i);
    } else if (i.exactDate && date && date <= todayIso) {
      buckets.dueToday.push(i);
    } else if (i.weekOfMonth !== undefined) {
      const pMonth = i.plannedMonth ?? currentMonth;
      if (pMonth === currentMonth) {
        if (i.weekOfMonth === currentWeekOfMonth) buckets.thisWeek.push(i);
        else buckets.thisMonth.push(i);
      } else if (pMonth > currentMonth) {
        buckets.thisQuarter.push(i);
      } else {
        buckets.dueToday.push(i);
      }
    } else if (date && date <= weekEnd) {
      buckets.thisWeek.push(i);
    } else if (date && date <= monthEnd) {
      buckets.thisMonth.push(i);
    } else if (date && date > monthEnd) {
      buckets.thisQuarter.push(i);
    } else {
      buckets.thisMonth.push(i);
    }
  }

  const byDate = (a: MyPlanItem, b: MyPlanItem) => (a.dateIso ?? "9999").localeCompare(b.dateIso ?? "9999");
  // Slip-limit breaches first in the attention section, then by date.
  const byAttention = (a: MyPlanItem, b: MyPlanItem) =>
    Number(b.atSlipLimit) - Number(a.atSlipLimit) || byDate(a, b);
  buckets.dueToday.sort(byDate);
  buckets.thisWeek.sort(byDate);
  buckets.thisMonth.sort(byDate);
  buckets.thisQuarter.sort(byDate);
  buckets.waitingOnMe.sort(byDate);
  buckets.needsAttention.sort(byAttention);

  const monthLabel = today.toLocaleDateString("en-UG", { month: "long", timeZone: "UTC" });
  return [
    { key: "dueToday", title: "Due Today", emptyCopy: "Nothing due today — you're clear.", items: buckets.dueToday },
    { key: "thisWeek", title: "Planned This Week", emptyCopy: "Nothing else scheduled this week.", items: buckets.thisWeek },
    { key: "thisMonth", title: "Planned This Month", emptyCopy: `Nothing further planned in ${monthLabel}.`, items: buckets.thisMonth },
    { key: "thisQuarter", title: "Planned This Quarter", emptyCopy: "Nothing scheduled later this quarter.", items: buckets.thisQuarter },
    { key: "waitingOnMe", title: "Waiting on Me", emptyCopy: "Nothing is blocked on you — no Salesforce IDs, evidence, or returned items pending.", items: buckets.waitingOnMe },
    { key: "needsAttention", title: "Rescheduled / Needs Attention", emptyCopy: "No rescheduled or deferred activities.", items: buckets.needsAttention },
  ];
}

/** Week/month display for visit-type items ("Week 2 · June"). */
export function weekMonthLabel(i: MyPlanItem): string | null {
  if (i.dateIso) {
    const d = new Date(i.dateIso);
    if (!Number.isNaN(d.getTime())) {
      const week = Math.min(5, Math.max(1, Math.ceil(d.getUTCDate() / 7)));
      return `Week ${week} · ${d.toLocaleDateString("en-UG", { month: "long", timeZone: "UTC" })}`;
    }
  }
  if (i.weekOfMonth) return `Week ${i.weekOfMonth} this month`;
  return null;
}

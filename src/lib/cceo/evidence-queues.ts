// Evidence & Salesforce guided queues (spec §16) — the CCEO's personal
// "what is blocking my completed work" derivation.
//
// Every completed activity must walk the chain
//   Completed → evidence → Salesforce ID → IA verify → accountability.
// This module reads the live action store and answers, for ONE signed-in
// CCEO (scoped by `assigneeId === user.staffId`), which of their items
// are stuck at each gate:
//
//   1. Evidence Required      — Completed, no evidence captured yet
//                               (no confirmed-completion record and, for
//                               trainings, no participant rows).
//   2. Salesforce ID Required — evidence exists but no SVE-/TS- ID on
//                               the record (incl. SalesforceIdPending).
//   3. IA Returned            — bounced by IA; the return reason is read
//                               from the `activity.returned` audit event
//                               (fallback: the record's lastReason).
//   4. Accountability Pending — weekly fund requests already disbursed
//                               to this staff whose accountability is
//                               not yet approved/closed.
//
// Server-only so the page, the dashboard card, and a future
// /api/cceo/evidence-queues route all share one derivation.

import "server-only";

import {
  activities,
  trainingParticipants,
  type ActivityKind,
  type PlannedActivityRecord,
} from "@/lib/actions/store";
import { completionFor } from "@/lib/execution/completion-overlay";
import { readAuditLog } from "@/lib/actions/audit";
import {
  SF_PREFIX,
  salesforceKindFor,
  type SalesforceActivityKind,
} from "@/lib/salesforce-id";
import { findRequestsForStaff } from "@/lib/funds/weekly-fund-mock";
import { formatMoney } from "@/lib/funds/weekly-fund-engine";
import type { WeeklyFundRequestStatus } from "@/lib/funds/weekly-fund-types";

// ────────── Types ──────────

export type EvidenceQueueItem = {
  id: string;
  /** Human activity-type label, e.g. "Cluster Training". */
  activityType: string;
  schoolOrCluster: string;
  /** Short display date — scheduled date if set, else last update. */
  dateLabel: string;
  /** Why the item is stuck at this gate. */
  blockedReason: string;
  /** Days since the item entered (proxy: last update) — drives due-ness. */
  daysWaiting: number;
  sfKind: SalesforceActivityKind;
  /** Expected Salesforce ID prefix: "SVE-" (visits) or "TS-" (trainings). */
  expectedPrefix: string;
  schoolId?: string;
  planId: string;
  /** Where the row's action navigates (plan detail / weekly funds). */
  href: string;
};

export type AccountabilityQueueItem = {
  id: string;
  weekLabel: string;       // "Week 3 · May 2026"
  amountLabel: string;     // formatted disbursed amount
  statusLabel: string;
  blockedReason: string;
  daysWaiting: number;
  href: string;
};

export type EvidenceQueueCounts = {
  evidence: number;
  salesforce: number;
  returned: number;
  accountability: number;
  total: number;
};

export type EvidenceQueues = {
  evidenceRequired: EvidenceQueueItem[];
  sfIdRequired: EvidenceQueueItem[];
  iaReturned: EvidenceQueueItem[];
  accountabilityPending: AccountabilityQueueItem[];
  counts: EvidenceQueueCounts;
};

// ────────── Labels ──────────

// Human labels per ActivityKind — these feed `salesforceKindFor`, which
// matches on the canonical label set ("Cluster Training" → TS-, visits →
// SVE-). Keep in sync with the union in lib/actions/store.ts.
const KIND_LABEL: Record<ActivityKind, string> = {
  CLUSTER_TRAINING:   "Cluster Training",
  IN_SCHOOL_COACHING: "In-School Coaching",
  SCHOOL_VISIT:       "School Visit",
  SSA_FOLLOW_UP:      "SSA Follow-Up",
  HANDOVER_MEETING:   "Handover Meeting",
  LESSON_OBSERVATION: "Lesson Observation",
  PARTNER_FOLLOW_UP:  "Partner Follow-Up",
  TRAINING_FOLLOW_UP: "Training Follow-Up",
  DATA_COLLECTION:    "Data Collection",
  COURTESY_VISIT:     "Courtesy Visit",
};

const ACCOUNTABILITY_REASON: Partial<Record<WeeklyFundRequestStatus, string>> = {
  DISBURSED:                "Funds disbursed — confirm receipt to unlock accountability.",
  RECEIVED:                 "Funds received — accountability opens once the week's activities run.",
  IN_USE:                   "Week in use — submit accountability (NetSuite Expense ID) at week close.",
  ACCOUNTABILITY_SUBMITTED: "Accountability submitted — awaiting Program Lead confirmation.",
  ACCOUNTABILITY_RETURNED:  "Accountability returned — fix the receipts and resubmit.",
};

const ACCOUNTABILITY_STATUS_LABEL: Partial<Record<WeeklyFundRequestStatus, string>> = {
  DISBURSED:                "Disbursed",
  RECEIVED:                 "Received",
  IN_USE:                   "In use",
  ACCOUNTABILITY_SUBMITTED: "Submitted",
  ACCOUNTABILITY_RETURNED:  "Returned",
};

/** Disbursed-but-not-closed statuses the CCEO still owes paperwork on. */
const ACCOUNTABILITY_OPEN_STATUSES = new Set<WeeklyFundRequestStatus>([
  "DISBURSED",
  "RECEIVED",
  "IN_USE",
  "ACCOUNTABILITY_SUBMITTED",
  "ACCOUNTABILITY_RETURNED",
]);

// ────────── Helpers ──────────

function daysSince(iso: string | undefined, now: Date): number {
  if (!iso) return 0;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return 0;
  return Math.max(0, Math.floor((now.getTime() - then) / 86_400_000));
}

function shortDate(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

function schoolLabel(a: PlannedActivityRecord): string {
  if (a.schoolName) return a.schoolName;
  // Titles in the store carry "Activity — School" — salvage the school half.
  const dashed = a.title.split("—")[1]?.trim();
  if (dashed) return dashed;
  return a.schoolId ? `School ${a.schoolId}` : "—";
}

/** Evidence exists when the Salesforce Completion Gate ran (confirmed-
 *  completion overlay record) or participant evidence was captured. */
function hasEvidence(a: PlannedActivityRecord): boolean {
  if (completionFor(a.id)) return true;
  return trainingParticipants().some((p) => p.activityId === a.id);
}

function salesforceIdFor(a: PlannedActivityRecord): string | undefined {
  return a.salesforceId ?? completionFor(a.id)?.salesforceId;
}

/** The IA's return reason — audit event first (set by returnActivity),
 *  then the record's lastReason (seed rows), then an honest fallback. */
function returnReasonFor(a: PlannedActivityRecord): string {
  const event = readAuditLog({ subjectKind: "PlannedActivity", subjectId: a.id })
    .find((e) => e.action === "activity.returned");
  const reason = event?.payload?.reason;
  if (typeof reason === "string" && reason.trim()) return reason.trim();
  if (a.lastReason?.trim()) return a.lastReason.trim();
  return "Returned by IA for correction — see your notifications for details.";
}

function toQueueItem(
  a: PlannedActivityRecord,
  blockedReason: string,
  now: Date,
): EvidenceQueueItem {
  const label = KIND_LABEL[a.kind];
  const sfKind = salesforceKindFor(label);
  return {
    id: a.id,
    activityType: label,
    schoolOrCluster: schoolLabel(a),
    dateLabel: shortDate(a.scheduledDate ?? a.updatedAt),
    blockedReason,
    daysWaiting: daysSince(a.updatedAt, now),
    sfKind,
    expectedPrefix: SF_PREFIX[sfKind],
    schoolId: a.schoolId,
    planId: a.planId,
    href: `/plans/${a.planId}`,
  };
}

// ────────── Derivation ──────────

export function buildEvidenceQueues(
  user: { staffId: string },
  now: Date = new Date(),
): EvidenceQueues {
  const own = activities().filter(
    (a) => a.assigneeId === user.staffId && a.status !== "Cancelled",
  );

  const evidenceRequired: EvidenceQueueItem[] = [];
  const sfIdRequired: EvidenceQueueItem[] = [];
  const iaReturned: EvidenceQueueItem[] = [];

  for (const a of own) {
    if (a.status === "Returned") {
      iaReturned.push(toQueueItem(a, returnReasonFor(a), now));
      continue;
    }
    const completedAtGate = a.status === "Completed" || a.status === "SalesforceIdPending";
    if (!completedAtGate) continue;

    if (!hasEvidence(a)) {
      const isTraining = salesforceKindFor(KIND_LABEL[a.kind]) === "training";
      evidenceRequired.push(toQueueItem(
        a,
        isTraining
          ? "Completed without evidence — capture the participant breakdown and attendance."
          : "Completed without evidence — confirm the visit record (sign-in, notes).",
        now,
      ));
    } else if (!salesforceIdFor(a)) {
      sfIdRequired.push(toQueueItem(
        a,
        "Evidence captured — enter the Salesforce Activity ID to submit for verification.",
        now,
      ));
    }
  }

  // Oldest-first inside each queue so the most overdue item leads.
  const byWaiting = (x: { daysWaiting: number }, y: { daysWaiting: number }) =>
    y.daysWaiting - x.daysWaiting;
  evidenceRequired.sort(byWaiting);
  sfIdRequired.sort(byWaiting);
  iaReturned.sort(byWaiting);

  const accountabilityPending: AccountabilityQueueItem[] = findRequestsForStaff(user.staffId)
    .filter((r) => ACCOUNTABILITY_OPEN_STATUSES.has(r.status))
    .map((r) => ({
      id: r.id,
      weekLabel: `Week ${r.period.weekOfMonth} · ${r.period.monthLabel}`,
      amountLabel: formatMoney(r.disbursedAmount ?? r.requestedAmount),
      statusLabel: ACCOUNTABILITY_STATUS_LABEL[r.status] ?? r.status,
      blockedReason: ACCOUNTABILITY_REASON[r.status] ?? "Accountability open.",
      daysWaiting: daysSince(r.disbursedAt ?? r.period.weekEndIso, now),
      href: "/weekly-funds",
    }))
    .sort(byWaiting);

  const counts: EvidenceQueueCounts = {
    evidence: evidenceRequired.length,
    salesforce: sfIdRequired.length,
    returned: iaReturned.length,
    accountability: accountabilityPending.length,
    total:
      evidenceRequired.length +
      sfIdRequired.length +
      iaReturned.length +
      accountabilityPending.length,
  };

  return { evidenceRequired, sfIdRequired, iaReturned, accountabilityPending, counts };
}

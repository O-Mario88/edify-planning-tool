// CCEO partner-work monitoring (spec §15) — buildPartnerWork(user).
//
// Thin derivation layer over partner-monitoring-types (the typed,
// empty-by-default seed; live rows arrive once PartnerService exposes
// the SQL view). This wrapper groups raw monitor rows into the six
// CCEO monitor buckets and ranks the most urgent rows, so the
// dashboard card, the /partners monitor section, and the
// /api/cceo/partner-work route all read the exact same shape.
//
// Scope: the monitor rows are authored as "every partner activity this
// staff member assigned" (their schools/clusters), so for the CCEO the
// engine is an identity-scoped read. Non-CCEO roles get empty buckets —
// PL/CD partner oversight has its own surfaces.

import type { EdifyRole } from "@/lib/auth-public";
import {
  staffMonitorRows,
  delayAlerts,
  monitorEvidenceLink,
  type StaffMonitorRow,
} from "@/lib/partner/partner-monitoring-types";
import {
  STATUS_LABEL,
  type PartnerWorkflowStatus,
} from "@/lib/partner/partner-workflow";
import { evidenceSummaries } from "@/lib/partner/partner-evidence-mock";

// Minimal user shape — structurally satisfied by DemoUser (server) and
// by the {role, name} props pages already pass to client components.
export type PartnerWorkUser = {
  name: string;
  role: EdifyRole;
  staffId?: string;
};

// ────────── Bucket taxonomy ──────────

export type PartnerWorkBucketKey =
  | "notScheduled"       // assigned but the partner hasn't scheduled (incl. SLA-breached)
  | "dueScheduled"       // scheduled / delivery in motion
  | "awaitingMyReview"   // partner evidence waiting on the CCEO
  | "returnedToPartner"  // evidence the CCEO returned for correction
  | "readyForSalesforce" // confirmed — needs the Salesforce completion ID
  | "paymentPipeline";   // payment moving through PL → IA → accountant

export type PartnerWorkBucket = {
  key: PartnerWorkBucketKey;
  label: string;
  /** One-line meaning, shown as tooltip/caption. */
  description: string;
  count: number;
  rows: StaffMonitorRow[];
  /** Where the CCEO acts on this bucket. */
  actionHref: string;
  actionLabel: string;
  /** "alert" when the bucket is waiting on someone and count > 0. */
  tone: "default" | "alert" | "good";
};

export type UrgentPartnerRow = {
  id: string;
  school: string;
  district: string;
  partner: string;
  reason: string;
  due: string;
  actionHref: string;
  actionLabel: string;
};

export type PartnerPaymentStage = {
  status: PartnerWorkflowStatus;
  label: string;
  count: number;
  amountUgx: number;
};

export type PartnerPaymentSummary = {
  count: number;
  totalUgx: number;
  stages: PartnerPaymentStage[];
};

export type PartnerWork = {
  buckets: PartnerWorkBucket[];
  urgent: UrgentPartnerRow[];
  payment: PartnerPaymentSummary;
  /** Everything not yet Paid/Closed — the "open partner work" headline. */
  totalOpen: number;
};

// The LIVE CCEO evidence-review flow is StaffPartnerMonitoring
// (Confirm / Return / Reject row actions), mounted on /my-targets.
// (src/components/partner-review/PartnerReviewActions is orphaned —
// see the live-vs-orphaned map.)
export const PARTNER_REVIEW_HREF = "/my-targets";
// Salesforce completion queue (CceoSalesforceQueueCard "View All").
export const SALESFORCE_QUEUE_HREF = "/queue";

// ────────── Status → bucket mapping ──────────

const BUCKET_STATUSES: Record<PartnerWorkBucketKey, ReadonlyArray<PartnerWorkflowStatus>> = {
  // Delayed in the mock = pre-delivery SLA breach (not scheduled, or
  // scheduled date passed with no delivery) — still the partner's move.
  notScheduled:       ["AssignedToPartner", "Delayed", "Reassigned"],
  dueScheduled:       ["ScheduledByPartner", "Delivered"],
  awaitingMyReview:   ["EvidenceSubmitted", "AwaitingCceoConfirmation", "ReturnedToCceo"],
  returnedToPartner:  ["ReturnedToPartner"],
  readyForSalesforce: ["ConfirmedByCceo"],
  paymentPipeline:    ["AwaitingPlApproval", "ApprovedByPl", "AwaitingIaVerification", "IaVerified", "SentToAccountant", "OnHold"],
};

const PAYMENT_STAGE_ORDER: ReadonlyArray<PartnerWorkflowStatus> = [
  "AwaitingPlApproval", "ApprovedByPl", "AwaitingIaVerification",
  "IaVerified", "SentToAccountant", "OnHold",
];

// Rows whose linked evidence summary was returned for correction count
// as "returned" even while the workflow row still reads
// AwaitingCceoConfirmation (the mock has no ReturnedToPartner row — the
// returned state lives on the evidence record, EVA-003).
function returnedEvidenceRowIds(): Set<string> {
  const ids = new Set<string>();
  for (const [rowId, evidenceId] of Object.entries(monitorEvidenceLink)) {
    const ev = evidenceSummaries.find((e) => e.activityId === evidenceId);
    if (ev?.status === "returned_for_correction") ids.add(rowId);
  }
  return ids;
}

function fmtDue(iso?: string): string | undefined {
  if (!iso) return undefined;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return undefined;
  return `Due ${d.toLocaleDateString("en-UG", { month: "short", day: "numeric" })}`;
}

// ────────── The engine ──────────

export function buildPartnerWork(user: PartnerWorkUser): PartnerWork {
  // Partner-work monitoring is the CCEO's view of the work *they*
  // assigned. Admin sees it too (system fallback); everyone else empty.
  const scoped = user.role === "CCEO" || user.role === "Admin";
  const rows = scoped ? staffMonitorRows : [];
  const returnedIds = scoped ? returnedEvidenceRowIds() : new Set<string>();

  function rowsFor(key: PartnerWorkBucketKey): StaffMonitorRow[] {
    const statuses = BUCKET_STATUSES[key];
    return rows.filter((r) => {
      const returned = returnedIds.has(r.id) || r.status === "ReturnedToPartner";
      if (key === "returnedToPartner") return returned;
      // A returned row must not double-count under "awaiting my review".
      if (key === "awaitingMyReview" && returned) return false;
      return statuses.includes(r.status);
    });
  }

  const bucketDefs: PartnerWorkBucket[] = [
    {
      key: "notScheduled",
      label: "Not Yet Scheduled",
      description: "Assignments the partner hasn't placed in a delivery week — or where the SLA already slipped.",
      rows: rowsFor("notScheduled"),
      actionHref: PARTNER_REVIEW_HREF,
      actionLabel: "Nudge / reassign",
      tone: "alert",
      count: 0,
    },
    {
      key: "dueScheduled",
      label: "Due / Scheduled",
      description: "Partner work scheduled or in delivery this week.",
      rows: rowsFor("dueScheduled"),
      actionHref: PARTNER_REVIEW_HREF,
      actionLabel: "Track delivery",
      tone: "default",
      count: 0,
    },
    {
      key: "awaitingMyReview",
      label: "Awaiting My Review",
      description: "Partner evidence submitted — your Confirm / Return decision gates payment.",
      rows: rowsFor("awaitingMyReview"),
      actionHref: PARTNER_REVIEW_HREF,
      actionLabel: "Review evidence",
      tone: "alert",
      count: 0,
    },
    {
      key: "returnedToPartner",
      label: "Returned to Partner",
      description: "Evidence you returned for correction — waiting on the partner's resubmission.",
      rows: rowsFor("returnedToPartner"),
      actionHref: PARTNER_REVIEW_HREF,
      actionLabel: "View correction",
      tone: "alert",
      count: 0,
    },
    {
      key: "readyForSalesforce",
      label: "Ready for Salesforce ID",
      description: "Confirmed work that needs its Salesforce completion ID before IA verification.",
      rows: rowsFor("readyForSalesforce"),
      actionHref: SALESFORCE_QUEUE_HREF,
      actionLabel: "Enter Salesforce ID",
      tone: "default",
      count: 0,
    },
    {
      key: "paymentPipeline",
      label: "Payment Pipeline",
      description: "Partner payments moving through PL approval → IA verification → accountant.",
      rows: rowsFor("paymentPipeline"),
      actionHref: PARTNER_REVIEW_HREF,
      actionLabel: "Track payments",
      tone: "default",
      count: 0,
    },
  ];
  const buckets: PartnerWorkBucket[] = bucketDefs.map((b) => ({
    ...b,
    count: b.rows.length,
    tone: b.tone === "alert" && b.rows.length === 0 ? "default" : b.tone,
  }));

  // ── Payment summary (per approver stage, with amounts) ──
  const paymentRows = buckets.find((b) => b.key === "paymentPipeline")!.rows;
  const stages: PartnerPaymentStage[] = PAYMENT_STAGE_ORDER
    .map((status) => {
      const stageRows = paymentRows.filter((r) => r.status === status);
      return {
        status,
        label: STATUS_LABEL[status],
        count: stageRows.length,
        amountUgx: stageRows.reduce((s, r) => s + (r.amountUgx ?? 0), 0),
      };
    })
    .filter((s) => s.count > 0);
  const payment: PartnerPaymentSummary = {
    count: paymentRows.length,
    totalUgx: stages.reduce((s, st) => s + st.amountUgx, 0),
    stages,
  };

  // ── Urgency ranking — top rows the CCEO should touch today ──
  // Delayed work outranks everything (the school is waiting), then the
  // CCEO's own review queue (it gates partner payment), then returns.
  const urgent: UrgentPartnerRow[] = rows
    .map((r) => {
      const returned = returnedIds.has(r.id) || r.status === "ReturnedToPartner";
      const ev = monitorEvidenceLink[r.id]
        ? evidenceSummaries.find((e) => e.activityId === monitorEvidenceLink[r.id])
        : undefined;
      let score = 0;
      let reason = STATUS_LABEL[r.status];
      let actionLabel = "Open";
      if (r.status === "Delayed") {
        score = 100 + (r.delayDays ?? 0);
        const alert = delayAlerts.find((a) => a.message.toLowerCase().includes(r.school.split(" ")[0].toLowerCase()));
        reason = alert?.message ?? `${r.delayDays ?? "?"} days delayed — not yet delivered`;
        actionLabel = "Nudge / reassign";
      } else if (returned) {
        score = 80;
        reason = ev?.reviewerComment ?? "Returned to partner for correction";
        actionLabel = "View correction";
      } else if (r.status === "AwaitingCceoConfirmation" || r.status === "EvidenceSubmitted") {
        score = 60 + (ev && ev.criticalMissingCount > 0 ? 10 : 0);
        reason = ev
          ? `Evidence ${ev.completenessScore}% complete — awaiting your review`
          : "Evidence submitted — awaiting your review";
        actionLabel = "Review evidence";
      }
      const due = fmtDue(ev?.dueDateIso)
        ?? (r.scheduledWeek ? r.scheduledWeek : undefined)
        ?? (r.delayDays != null ? `${r.delayDays}d overdue` : "—");
      return { row: r, score, reason, due, actionLabel };
    })
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, 3)
    .map(({ row, reason, due, actionLabel }) => ({
      id: row.id,
      school: row.school,
      district: row.district,
      partner: row.partner,
      reason,
      due,
      actionHref: PARTNER_REVIEW_HREF,
      actionLabel,
    }));

  const totalOpen = rows.filter((r) => r.status !== "Paid" && r.status !== "Closed").length;

  return { buckets, urgent, payment, totalOpen };
}

/** Compact UGX formatter shared by the card + /partners section. */
export function fmtUgx(amount: number): string {
  if (amount >= 1_000_000) return `UGX ${(amount / 1_000_000).toFixed(1)}M`;
  if (amount >= 1_000) return `UGX ${(amount / 1_000).toFixed(0)}K`;
  return `UGX ${amount}`;
}

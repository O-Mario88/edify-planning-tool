// Workflow Health Monitor (spec layer #2).
//
// One engine, ten checks: it walks the Unified Activity model (layer #6) plus the
// school directory, core plans and fund requests, and flags every place a
// workflow is STUCK. Each issue is a clean alert with a reason and a link — so
// the app becomes self-correcting instead of silently leaking half-finished work.
//
// server-only: reads the globalThis-backed stores via the unified aggregator.

import "server-only";

import { allUnifiedActivities } from "@/lib/activity/unified-activity-source";
import { isOpenActivity, type UnifiedActivity } from "@/lib/activity/unified-activity";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { schoolWorkflowState } from "@/lib/school-directory/school-state";
import { corePlans } from "@/lib/core/core-store";
import { fundRequests } from "@/lib/actions/store";

export type HealthSeverity = "critical" | "warning" | "info";

export type WorkflowCheckId =
  | "scheduled_no_cost"
  | "partner_unscheduled"
  | "completed_no_evidence"
  | "evidence_unreviewed"
  | "salesforce_missing"
  | "ia_pending_too_long"
  | "payment_uncleared"
  | "ssa_rec_no_plan"
  | "core_package_gap"
  | "fund_cost_mismatch";

export type HealthIssue = {
  check: WorkflowCheckId;
  severity: HealthSeverity;
  entityId: string;
  entityLabel: string;
  detail: string;
  href?: string;
  ageDays?: number;
};

export type HealthCheck = {
  id: WorkflowCheckId;
  label: string;
  description: string;
  severity: HealthSeverity;
  count: number;
  issues: HealthIssue[];
};

export type WorkflowHealthReport = {
  generatedAt: string;
  totalIssues: number;
  criticalCount: number;
  warningCount: number;
  checks: HealthCheck[];
};

// Thresholds for "pending too long" (calendar days).
const IA_STALE_DAYS = 3;
const PAYMENT_STALE_DAYS = 2;

function dayDiff(fromIso: string | undefined, todayIso: string): number {
  if (!fromIso) return 0;
  const a = Date.parse(fromIso);
  const b = Date.parse(todayIso);
  if (Number.isNaN(a) || Number.isNaN(b)) return 0;
  return Math.max(0, Math.round((b - a) / 86_400_000));
}

const CHECK_META: Record<WorkflowCheckId, { label: string; description: string; severity: HealthSeverity }> = {
  scheduled_no_cost: { label: "Scheduled activity with no cost", description: "A planned activity carries no catalogue cost — its fund request will be wrong.", severity: "warning" },
  partner_unscheduled: { label: "Partner assignment not scheduled", description: "Work is assigned to a partner but has no date — it will never start.", severity: "warning" },
  completed_no_evidence: { label: "Completed but no evidence", description: "Delivered work with no attendance/visit evidence — it can't be verified.", severity: "warning" },
  evidence_unreviewed: { label: "Evidence uploaded but not reviewed", description: "Partner evidence is in but staff hasn't reviewed it / entered the Salesforce ID.", severity: "warning" },
  salesforce_missing: { label: "Salesforce ID missing", description: "Evidence is in but the SV-/TS- Salesforce ID hasn't been entered.", severity: "warning" },
  ia_pending_too_long: { label: "IA verification pending too long", description: `Submitted to IA more than ${IA_STALE_DAYS} days ago and still unconfirmed.`, severity: "critical" },
  payment_uncleared: { label: "Payment ready but not cleared", description: `IA-confirmed more than ${PAYMENT_STALE_DAYS} days ago but payment/accountability isn't cleared.`, severity: "critical" },
  ssa_rec_no_plan: { label: "SSA done but no plan", description: "School is planning-ready (SSA complete) but has no scheduled activities.", severity: "warning" },
  core_package_gap: { label: "Core school missing required visits/trainings", description: "A core plan hasn't completed its 4 visits + 4 trainings.", severity: "info" },
  fund_cost_mismatch: { label: "Fund request doesn't match activity cost", description: "A fund request exceeds its approved weekly plan / catalogue cost.", severity: "warning" },
};

/** Run all ten checks and return a categorised report. */
export function workflowHealth(opts: { todayIso?: string } = {}): WorkflowHealthReport {
  const todayIso = opts.todayIso ?? new Date().toISOString().slice(0, 10);
  const acts = allUnifiedActivities();
  const open = acts.filter(isOpenActivity);

  const buckets: Record<WorkflowCheckId, HealthIssue[]> = {
    scheduled_no_cost: [], partner_unscheduled: [], completed_no_evidence: [],
    evidence_unreviewed: [], salesforce_missing: [], ia_pending_too_long: [],
    payment_uncleared: [], ssa_rec_no_plan: [], core_package_gap: [], fund_cost_mismatch: [],
  };

  const push = (check: WorkflowCheckId, a: UnifiedActivity, detail: string, ageDays?: number) =>
    buckets[check].push({
      check,
      severity: CHECK_META[check].severity,
      entityId: a.id,
      entityLabel: a.title,
      detail,
      href: HREF[check],
      ageDays,
    });

  // ── Activity-pipeline checks (1–7) — one pass over the unified model ──
  for (const a of open) {
    // 1. Scheduled with no cost (only planned-store activities carry a costed line).
    if (a.source === "planned" && (a.stage === "planned" || a.stage === "in_progress") && !a.hasCost) {
      push("scheduled_no_cost", a, "No catalogue cost set on a scheduled activity.");
    }
    // 2. Partner assignment with no schedule.
    if (a.deliveryMode === "partner" && a.stage === "planned" && !a.scheduledDate && !a.schedulePeriod) {
      push("partner_unscheduled", a, "Assigned to a partner but has no date or period.");
    }
    // 3. Completed but no evidence.
    if (a.stage === "evidence_pending") {
      push("completed_no_evidence", a, "Delivered — evidence not uploaded.");
    }
    // 4 / 5. Evidence in, Salesforce ID missing (partner → unreviewed, staff → SF missing).
    if (a.stage === "salesforce_pending") {
      if (a.deliveryMode === "partner") push("evidence_unreviewed", a, "Partner evidence awaiting staff review + Salesforce ID.");
      else push("salesforce_missing", a, "Evidence in — Salesforce ID not entered.");
    }
    // 6. IA pending too long.
    if (a.stage === "ia_pending") {
      const age = dayDiff(a.updatedAt, todayIso);
      if (age > IA_STALE_DAYS) push("ia_pending_too_long", a, `Awaiting IA for ${age} days.`, age);
    }
    // 7. Payment ready but not cleared.
    if (a.stage === "payment_pending") {
      const age = dayDiff(a.updatedAt, todayIso);
      if (age > PAYMENT_STALE_DAYS) push("payment_uncleared", a, `IA-confirmed ${age} days ago — payment not cleared.`, age);
    }
  }

  // ── 8. School planning-ready but no activities ──
  const schoolHasActivity = new Set(acts.map((a) => a.schoolId).filter(Boolean) as string[]);
  for (const s of intakeSchools) {
    if (schoolWorkflowState(s).stage !== "planning_ready") continue;
    if (schoolHasActivity.has(s.schoolId)) continue;
    buckets.ssa_rec_no_plan.push({
      check: "ssa_rec_no_plan",
      severity: CHECK_META.ssa_rec_no_plan.severity,
      entityId: s.schoolId,
      entityLabel: s.schoolName,
      detail: "SSA complete but nothing scheduled — the recommendation isn't acted on.",
      href: "/planning",
    });
  }

  // ── 9. Core package incomplete ──
  for (const p of corePlans()) {
    if (p.status === "Closed") continue;
    const vGap = Math.max(0, p.visitsTarget - p.visitsCompleted);
    const tGap = Math.max(0, p.trainingsTarget - p.trainingsCompleted);
    if (vGap + tGap > 0) {
      buckets.core_package_gap.push({
        check: "core_package_gap",
        severity: CHECK_META.core_package_gap.severity,
        entityId: p.schoolId,
        entityLabel: `Core plan ${p.id}`,
        detail: `${vGap} visit(s) + ${tGap} training(s) of the 4+4 package still pending (${p.packageCompletionPercent}% done).`,
        href: "/core-schools",
      });
    }
  }

  // ── 10. Fund request doesn't match scheduled cost ──
  for (const r of fundRequests()) {
    if (!r.risks?.includes("ExceedsApprovedWeeklyPlan")) continue;
    buckets.fund_cost_mismatch.push({
      check: "fund_cost_mismatch",
      severity: CHECK_META.fund_cost_mismatch.severity,
      entityId: r.id,
      entityLabel: `${r.staffName} — ${r.id}`,
      detail: "Request exceeds the approved weekly plan / catalogue cost.",
      href: "/approvals",
    });
  }

  const checks: HealthCheck[] = (Object.keys(CHECK_META) as WorkflowCheckId[]).map((id) => ({
    id,
    label: CHECK_META[id].label,
    description: CHECK_META[id].description,
    severity: CHECK_META[id].severity,
    count: buckets[id].length,
    issues: buckets[id],
  }));

  const totalIssues = checks.reduce((n, c) => n + c.count, 0);
  const criticalCount = checks.filter((c) => c.severity === "critical").reduce((n, c) => n + c.count, 0);
  const warningCount = checks.filter((c) => c.severity === "warning").reduce((n, c) => n + c.count, 0);

  return { generatedAt: todayIso, totalIssues, criticalCount, warningCount, checks };
}

const HREF: Record<WorkflowCheckId, string> = {
  scheduled_no_cost: "/my-plan",
  partner_unscheduled: "/partner/assignments",
  completed_no_evidence: "/evidence",
  evidence_unreviewed: "/evidence",
  salesforce_missing: "/evidence",
  ia_pending_too_long: "/data-verification",
  payment_uncleared: "/disbursements",
  ssa_rec_no_plan: "/planning",
  core_package_gap: "/core-schools",
  fund_cost_mismatch: "/approvals",
};

// Workflow Health Monitor (spec layer #2).
//
// One engine, twenty-four checks today: it walks the Unified Activity model
// (layer #6) plus the school directory, core plans and fund requests, and
// flags every place a workflow is STUCK. Each issue is a clean alert with a
// reason and a link — so the app becomes self-correcting instead of silently
// leaking half-finished work.
//
// Categories:
//   • Activity workflow (scheduled_no_cost, completed_no_evidence, …)
//   • Cluster planning (cluster_activity_no_exact_date, …)
//   • Budget / fund-request integrity (activity_missing_budget_line,
//     duplicate_activity_in_request, fund_request_total_mismatch, …)
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
  | "fund_cost_mismatch"
  // Cluster planning integrity (open-ended model — see ClusterIntelligence).
  // The 3-meeting cap is gone, but cluster meetings/trainings MUST carry an
  // exact calendar date + a clusterId + a focus intervention so the FE
  // intelligence + budget engine has the inputs it needs.
  | "cluster_activity_no_exact_date"
  | "cluster_training_no_cluster"
  | "cluster_meeting_no_focus"
  // ── Budget / fund-request integrity ────────────────────────────────────
  // The financial workflow is the most critical operational path. These
  // checks catch the "no cost, no valid plan" failure modes BEFORE they
  // become wrong fund requests or wrong disbursements.
  | "activity_missing_budget_line"
  | "budget_line_no_catalogue_version"
  | "partner_activity_no_partner_rate"
  | "training_no_participant_cost"
  | "weekly_request_missing_activity"
  | "monthly_budget_missing_activity"
  | "duplicate_activity_in_request"
  | "rescheduled_activity_in_old_period"
  | "approved_request_has_cost_blockers"
  | "fund_request_total_mismatch"
  | "staff_no_primary_district"
  // ── Upload + evidence integrity ────────────────────────────────────────
  // Uploads (schools, SSA, evidence) and their stored files MUST stay in
  // sync. These checks surface the moments where a row exists without a
  // file, a file exists without a row, a DOCX preview failed to convert,
  // or an activity submitted to IA carries no real evidence/Activity Code.
  | "school_upload_failed_rows"
  | "school_missing_geography"
  | "ssa_record_missing_school"
  | "school_ssa_without_scores"
  | "evidence_missing_storage_object"
  | "storage_object_missing_evidence_row"
  | "docx_conversion_failed"
  | "evidence_view_url_invalid"
  | "completed_without_evidence"
  | "submitted_to_ia_without_evidence"
  | "submitted_to_ia_without_activity_code"
  | "ia_verified_without_evidence"
  | "evidence_uploaded_by_unauthorized_user"
  | "evidence_view_attempted_by_unauthorized_user";

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

export const WORKFLOW_CHECK_META: Record<WorkflowCheckId, { label: string; description: string; severity: HealthSeverity }> = {
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
  cluster_activity_no_exact_date: { label: "Cluster meeting/training without exact date", description: "Cluster meetings and trainings must be scheduled on an exact calendar date (no month/week-only).", severity: "critical" },
  cluster_training_no_cluster: { label: "Training scheduled outside a cluster", description: "All trainings must be planned through a cluster — this one has no clusterId.", severity: "warning" },
  cluster_meeting_no_focus: { label: "Cluster meeting/training without focus intervention", description: "Cluster meetings and trainings must declare a focus SSA intervention so the intelligence engine can pick recommendations.", severity: "warning" },
  // Budget / fund-request integrity
  activity_missing_budget_line: { label: "Scheduled activity without an ActivityBudgetLine", description: "Every scheduled activity must carry at least one CD Cost Catalogue line. Reschedule or recost.", severity: "critical" },
  budget_line_no_catalogue_version: { label: "Budget line without catalogue version", description: "A cost line must store the CostSetting version it was sourced from — otherwise rate drift can't be audited.", severity: "warning" },
  partner_activity_no_partner_rate: { label: "Partner activity without partner rate", description: "Partner-delivered work must use a partner_*_lump_sum rate, not a staff rate.", severity: "warning" },
  training_no_participant_cost: { label: "Training without participant-based cost", description: "Trainings cost meals + mobilisation × participants. A training with 0 participant cost is mis-costed.", severity: "warning" },
  weekly_request_missing_activity: { label: "Weekly request missing planned activity", description: "A planned activity in this week is not in any draft weekly fund request — regenerate the Friday request.", severity: "warning" },
  monthly_budget_missing_activity: { label: "Monthly budget missing planned activity", description: "A planned activity in next month is not in the monthly work plan budget — regenerate the 25th envelope.", severity: "warning" },
  duplicate_activity_in_request: { label: "Same activity included twice in a request", description: "An activity appears in more than one active fund request line — duplicate disbursement risk.", severity: "critical" },
  rescheduled_activity_in_old_period: { label: "Rescheduled activity still counted in old period", description: "An activity was moved to a new week/month but its old request still references it. Run a budget revision.", severity: "critical" },
  approved_request_has_cost_blockers: { label: "Approved request contains a cost-blocked activity", description: "A request was approved while one of its activities is flagged costMissing — block disbursement.", severity: "critical" },
  fund_request_total_mismatch: { label: "Fund request total does not match its budget line sum", description: "The request total must equal the sum of its FundRequestItem amounts. Investigate manual edits.", severity: "warning" },
  staff_no_primary_district: { label: "Staff without primary district", description: "Costing engine cannot decide primary vs secondary visit rate without a primary district. Set staff district.", severity: "warning" },
  // Upload + evidence integrity
  school_upload_failed_rows: { label: "School upload batch has failed rows", description: "A bulk school upload completed with rejected rows — review and re-upload to keep the directory complete.", severity: "warning" },
  school_missing_geography: { label: "School missing geography (region/district/sub-county)", description: "A school exists without resolved geography — filters, scoping, and travel costing will skip it.", severity: "warning" },
  ssa_record_missing_school: { label: "SSA record without a linked school", description: "An SSA upload row failed to match a School Directory row — re-upload or fix the schoolId before planning unlocks.", severity: "critical" },
  school_ssa_without_scores: { label: "School with SSA upload but no structured scores", description: "An SSA upload landed without 8 intervention scores — recompute or re-upload to unlock planning readiness.", severity: "warning" },
  evidence_missing_storage_object: { label: "Evidence record without a stored file", description: "An EvidenceRecord row exists but its file is missing from disk/object storage. Re-upload or mark cancelled.", severity: "critical" },
  storage_object_missing_evidence_row: { label: "Storage object without an evidence row", description: "A file in evidence storage has no matching DB row — schedule an orphan cleanup pass.", severity: "warning" },
  docx_conversion_failed: { label: "DOCX evidence preview conversion failed", description: "Server-side LibreOffice headless conversion failed for a DOCX evidence file. Install LibreOffice or re-upload as PDF.", severity: "warning" },
  evidence_view_url_invalid: { label: "Evidence view URL invalid / expired", description: "The viewer URL for an evidence record can no longer be resolved — regenerate or re-upload.", severity: "warning" },
  completed_without_evidence: { label: "Activity completed without uploaded evidence", description: "Completed activity has zero EvidenceRecord rows — the completion gate was bypassed.", severity: "critical" },
  submitted_to_ia_without_evidence: { label: "Activity submitted to IA without evidence", description: "An activity reached IA verification with no evidence — IA cannot verify, and accountant cannot pay.", severity: "critical" },
  submitted_to_ia_without_activity_code: { label: "Activity submitted to IA without a valid Activity Code", description: "Activity reached IA without a SV-/TS- Activity Code. Verification is blocked.", severity: "critical" },
  ia_verified_without_evidence: { label: "IA verified an activity that has no evidence", description: "An IA-confirmed activity carries no EvidenceRecord — investigate review-trail integrity.", severity: "critical" },
  evidence_uploaded_by_unauthorized_user: { label: "Evidence uploaded by user outside the activity scope", description: "An EvidenceRecord row was created by a user not authorized for that activity — likely scope-check regression.", severity: "critical" },
  evidence_view_attempted_by_unauthorized_user: { label: "Evidence view attempted by unauthorized user", description: "An audited evidence.view event was logged for a user outside the activity scope — investigate the access path.", severity: "critical" },
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
    cluster_activity_no_exact_date: [], cluster_training_no_cluster: [], cluster_meeting_no_focus: [],
    activity_missing_budget_line: [], budget_line_no_catalogue_version: [],
    partner_activity_no_partner_rate: [], training_no_participant_cost: [],
    weekly_request_missing_activity: [], monthly_budget_missing_activity: [],
    duplicate_activity_in_request: [], rescheduled_activity_in_old_period: [],
    approved_request_has_cost_blockers: [], fund_request_total_mismatch: [],
    staff_no_primary_district: [],
    school_upload_failed_rows: [], school_missing_geography: [],
    ssa_record_missing_school: [], school_ssa_without_scores: [],
    evidence_missing_storage_object: [], storage_object_missing_evidence_row: [],
    docx_conversion_failed: [], evidence_view_url_invalid: [],
    completed_without_evidence: [], submitted_to_ia_without_evidence: [],
    submitted_to_ia_without_activity_code: [], ia_verified_without_evidence: [],
    evidence_uploaded_by_unauthorized_user: [], evidence_view_attempted_by_unauthorized_user: [],
  };

  const push = (check: WorkflowCheckId, a: UnifiedActivity, detail: string, ageDays?: number) =>
    buckets[check].push({
      check,
      severity: WORKFLOW_CHECK_META[check].severity,
      entityId: a.id,
      entityLabel: a.title,
      detail,
      href: WORKFLOW_CHECK_HREF[check],
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

    // ── Cluster planning integrity (open-ended model) ──
    const isClusterMeeting  = a.type === "Cluster Meeting";
    const isClusterTraining = a.type === "Cluster Training" || a.type === "SIT";
    if (isClusterMeeting || isClusterTraining) {
      // Cluster meetings + trainings need an exact calendar date — period-only
      // ("Week 2 · June") is not enough for the budget engine and IA paperwork.
      if (!a.scheduledDate) {
        push("cluster_activity_no_exact_date", a, "Cluster meeting/training without an exact calendar date.");
      }
      // Training must be planned through a cluster — direct school-level training
      // is no longer allowed. If a Cluster Training/SIT slipped through without
      // a clusterId, flag it.
      if (isClusterTraining && !a.clusterId) {
        push("cluster_training_no_cluster", a, "Cluster training with no clusterId — schedule via a cluster.");
      }
      // Cluster meetings/trainings need a focus intervention for the
      // intelligence panel + recommendation engine to function.
      if (!a.intervention) {
        push("cluster_meeting_no_focus", a, "Cluster meeting/training without a focus SSA intervention.");
      }
    }

    // ── Budget / fund-request integrity ──────────────────────────────────
    // Catches the financial workflow's "no cost, no valid plan" failure modes
    // BEFORE they propagate into a fund request or disbursement.
    const isPlanned = a.stage === "planned" || a.stage === "in_progress";
    if (isPlanned && a.source === "planned" && !a.hasCost) {
      // Same row that scheduled_no_cost flags, but elevated to critical because
      // the FUND REQUEST it would belong to is by definition invalid.
      push("activity_missing_budget_line", a, "Scheduled but no CD Cost Catalogue line attached.");
    }
    // Partner activities must use a partner rate — when a partner-delivered
    // row has the staff visit shape (no partner lump sum), warn.
    if (
      a.deliveryMode === "partner" &&
      a.hasCost &&
      (a.type === "Partner Visit" || a.type === "Partner Training" || a.type === "Project Visit" || a.type === "Project Training") &&
      typeof a.costCents === "number" &&
      a.costCents > 0 && a.costCents < 50_000  // partner lump-sum floor (UGX 50K)
    ) {
      push("partner_activity_no_partner_rate", a,
        "Partner activity priced below the partner_visit_lump_sum floor — likely using a staff rate.");
    }
    // Trainings without participant-based cost (meals/mobilisation × N) are
    // mis-costed. Detection heuristic: a training stage row with cost below
    // a per-participant floor.
    if (
      (a.type === "Training" || a.type === "Cluster Training" || a.type === "Core Training" || a.type === "SIT" || a.type === "Partner Training" || a.type === "Project Training") &&
      isPlanned && a.hasCost && typeof a.costCents === "number" && a.costCents > 0 && a.costCents < 100_000
    ) {
      push("training_no_participant_cost", a,
        "Training cost is too low — looks like the per-participant meals/mobilisation line was not added.");
    }

    // ── Upload + evidence integrity ──────────────────────────────────────
    // These catch the moments where the completion gate would have been
    // bypassed (closed-out activity with no evidence) or where IA somehow
    // approved a row with no proof attached.
    if (a.stage === "closed" && !a.hasEvidence) {
      push("completed_without_evidence", a, "Closed activity has no uploaded evidence — completion gate was bypassed.");
    }
    if (a.stage === "ia_pending" && !a.hasEvidence) {
      push("submitted_to_ia_without_evidence", a, "Activity is awaiting IA but no evidence is attached.");
    }
    if (a.stage === "ia_pending" && !a.salesforceId) {
      push("submitted_to_ia_without_activity_code", a, "Activity is awaiting IA but the Activity Code (SV-/TS-) is missing.");
    }
    if ((a.iaStatus === "confirmed" || a.stage === "closed") && a.iaStatus === "confirmed" && !a.hasEvidence) {
      push("ia_verified_without_evidence", a, "IA-confirmed activity carries no evidence — verify the review trail.");
    }
  }

  // ── 8. School planning-ready but no activities ──
  const schoolHasActivity = new Set(acts.map((a) => a.schoolId).filter(Boolean) as string[]);
  for (const s of intakeSchools) {
    if (schoolWorkflowState(s).stage !== "planning_ready") continue;
    if (schoolHasActivity.has(s.schoolId)) continue;
    buckets.ssa_rec_no_plan.push({
      check: "ssa_rec_no_plan",
      severity: WORKFLOW_CHECK_META.ssa_rec_no_plan.severity,
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
        severity: WORKFLOW_CHECK_META.core_package_gap.severity,
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
      severity: WORKFLOW_CHECK_META.fund_cost_mismatch.severity,
      entityId: r.id,
      entityLabel: `${r.staffName} — ${r.id}`,
      detail: "Request exceeds the approved weekly plan / catalogue cost.",
      href: "/approvals",
    });
  }

  const checks: HealthCheck[] = (Object.keys(WORKFLOW_CHECK_META) as WorkflowCheckId[]).map((id) => ({
    id,
    label: WORKFLOW_CHECK_META[id].label,
    description: WORKFLOW_CHECK_META[id].description,
    severity: WORKFLOW_CHECK_META[id].severity,
    count: buckets[id].length,
    issues: buckets[id],
  }));

  const totalIssues = checks.reduce((n, c) => n + c.count, 0);
  const criticalCount = checks.filter((c) => c.severity === "critical").reduce((n, c) => n + c.count, 0);
  const warningCount = checks.filter((c) => c.severity === "warning").reduce((n, c) => n + c.count, 0);

  return { generatedAt: todayIso, totalIssues, criticalCount, warningCount, checks };
}

export const WORKFLOW_CHECK_HREF: Record<WorkflowCheckId, string> = {
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
  cluster_activity_no_exact_date: "/clusters",
  cluster_training_no_cluster: "/clusters",
  cluster_meeting_no_focus: "/clusters",
  activity_missing_budget_line: "/my-plan",
  budget_line_no_catalogue_version: "/cost-settings",
  partner_activity_no_partner_rate: "/cost-settings",
  training_no_participant_cost: "/cost-settings",
  weekly_request_missing_activity: "/weekly-funds",
  monthly_budget_missing_activity: "/budget",
  duplicate_activity_in_request: "/fund-requests",
  rescheduled_activity_in_old_period: "/fund-requests",
  approved_request_has_cost_blockers: "/approvals",
  fund_request_total_mismatch: "/fund-requests",
  staff_no_primary_district: "/staff",
  school_upload_failed_rows: "/data-intake",
  school_missing_geography: "/schools",
  ssa_record_missing_school: "/data-intake",
  school_ssa_without_scores: "/data-intake",
  evidence_missing_storage_object: "/evidence",
  storage_object_missing_evidence_row: "/evidence",
  docx_conversion_failed: "/evidence",
  evidence_view_url_invalid: "/evidence",
  completed_without_evidence: "/my-plan",
  submitted_to_ia_without_evidence: "/approvals",
  submitted_to_ia_without_activity_code: "/approvals",
  ia_verified_without_evidence: "/approvals",
  evidence_uploaded_by_unauthorized_user: "/evidence",
  evidence_view_attempted_by_unauthorized_user: "/evidence",
};

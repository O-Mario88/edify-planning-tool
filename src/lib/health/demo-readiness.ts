// Demo Readiness Score (spec layer #3).
//
// A single 0–100 score answering "can we run the contract demo end-to-end right
// now?" — computed from REAL system state, not a static doc. Each demo-critical
// surface has a check: is its data populated, is the workflow chain unbroken, is
// the app safe (no mock leakage in prod, roles mapped). When a check fails it
// says exactly WHERE and links to the fix.
//
// server-only: reads the live stores + the Workflow Health Monitor (layer #2).

import "server-only";

import { allUnifiedActivities } from "@/lib/activity/unified-activity-source";
import type { UnifiedActivityStage } from "@/lib/activity/unified-activity";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { schoolWorkflowState } from "@/lib/school-directory/school-state";
import { activeClusters } from "@/lib/cluster/cluster-core";
import { missingCostSettings } from "@/lib/cost-settings-mock";
import { isProductionSafe } from "@/lib/mock-policy";
import { ROLE_REDIRECT, type EdifyRole } from "@/lib/auth-public";
import { workflowHealth } from "./workflow-health";

export type DemoCheckCategory = "Data" | "Workflow" | "Safety";

export type DemoCheck = {
  id: string;
  label: string;
  category: DemoCheckCategory;
  weight: number;
  /** A blocker check must pass for the demo to be "Ready". */
  blocker: boolean;
  pass: boolean;
  detail: string;
  fixHref?: string;
};

export type DemoReadinessBand = "Ready" | "Nearly ready" | "Not ready";

export type DemoReadinessReport = {
  generatedAt: string;
  score: number;
  band: DemoReadinessBand;
  passed: number;
  total: number;
  blockers: DemoCheck[];
  checks: DemoCheck[];
};

const ALL_ROLES: EdifyRole[] = [
  "CCEO", "CountryProgramLead", "CountryDirector", "RVP",
  "ImpactAssessment", "ProgramAccountant", "ProjectCoordinator",
  "HumanResource", "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
];

export function demoReadiness(): DemoReadinessReport {
  const today = new Date().toISOString().slice(0, 10);
  const acts = allUnifiedActivities();
  const byStage = (s: UnifiedActivityStage) => acts.filter((a) => a.stage === s).length;
  const planningReady = intakeSchools.filter((s) => schoolWorkflowState(s).stage === "planning_ready").length;
  const health = workflowHealth({ todayIso: today });
  const missingCost = missingCostSettings();

  const checks: DemoCheck[] = [
    // ── Data: every demo step needs real content to show ──
    {
      id: "directory_populated", label: "School Directory populated", category: "Data", weight: 3, blocker: true,
      pass: intakeSchools.length >= 5,
      detail: `${intakeSchools.length} schools in the directory.`, fixHref: "/schools",
    },
    {
      id: "clusters_exist", label: "Clusters created", category: "Data", weight: 2, blocker: true,
      pass: activeClusters().length >= 1,
      detail: `${activeClusters().length} active cluster(s).`, fixHref: "/clusters",
    },
    {
      id: "planning_ready", label: "Schools ready to plan (SSA done)", category: "Data", weight: 2, blocker: false,
      pass: planningReady >= 1,
      detail: `${planningReady} school(s) planning-ready.`, fixHref: "/planning",
    },
    {
      id: "cost_catalogue", label: "Cost catalogue complete", category: "Data", weight: 2, blocker: true,
      pass: missingCost.length === 0,
      detail: missingCost.length === 0 ? "All required cost items are set." : `${missingCost.length} cost item(s) missing: ${missingCost.slice(0, 3).join(", ")}.`,
      fixHref: "/budget",
    },
    {
      id: "scheduling_budget", label: "Scheduling creates budget lines", category: "Data", weight: 2, blocker: false,
      pass: acts.some((a) => a.source === "planned" && a.hasCost),
      detail: `${acts.filter((a) => a.hasCost).length} costed activit(ies).`, fixHref: "/my-plan",
    },
    {
      id: "partner_workflow", label: "Partner workflow has work", category: "Data", weight: 1, blocker: false,
      pass: acts.some((a) => a.deliveryMode === "partner"),
      detail: `${acts.filter((a) => a.deliveryMode === "partner").length} partner-delivered activit(ies).`, fixHref: "/partners",
    },
    {
      id: "evidence_works", label: "Evidence present", category: "Data", weight: 1, blocker: false,
      pass: acts.some((a) => a.hasEvidence),
      detail: `${acts.filter((a) => a.hasEvidence).length} activit(ies) with evidence.`, fixHref: "/evidence",
    },
    {
      id: "ia_queue", label: "IA verification queue non-empty", category: "Data", weight: 1, blocker: false,
      pass: byStage("ia_pending") >= 1,
      detail: `${byStage("ia_pending")} awaiting IA.`, fixHref: "/data-verification",
    },
    {
      id: "accountant_queue", label: "Accountant queue non-empty", category: "Data", weight: 1, blocker: false,
      pass: byStage("payment_pending") >= 1,
      detail: `${byStage("payment_pending")} awaiting payment.`, fixHref: "/disbursements",
    },
    {
      id: "completed_log", label: "Completed log non-empty", category: "Data", weight: 1, blocker: false,
      pass: byStage("closed") >= 1,
      detail: `${byStage("closed")} closed activit(ies).`, fixHref: "/completed-log",
    },
    // ── Workflow: the chain itself is unbroken ──
    {
      id: "no_critical_stuck", label: "No critical stuck workflows", category: "Workflow", weight: 3, blocker: true,
      pass: health.criticalCount === 0,
      detail: health.criticalCount === 0 ? "No critical stuck items." : `${health.criticalCount} critical stuck item(s).`,
      fixHref: "/system-health",
    },
    {
      id: "low_warnings", label: "Workflow warnings under control", category: "Workflow", weight: 1, blocker: false,
      pass: health.warningCount <= 8,
      detail: `${health.warningCount} workflow warning(s).`, fixHref: "/system-health",
    },
    // ── Safety: nothing fake or unguarded in front of the approver ──
    {
      id: "production_safe", label: "Production-safe (no mock leakage)", category: "Safety", weight: 2, blocker: false,
      pass: isProductionSafe(),
      detail: isProductionSafe() ? "Mock data cannot render in production." : "Mock data is allowed in this environment.",
      fixHref: "/system-health",
    },
    {
      id: "roles_mapped", label: "All roles have a landing route", category: "Safety", weight: 1, blocker: false,
      pass: ALL_ROLES.every((r) => !!ROLE_REDIRECT[r]),
      detail: `${ALL_ROLES.filter((r) => !!ROLE_REDIRECT[r]).length}/${ALL_ROLES.length} roles routed.`,
    },
  ];

  const total = checks.reduce((n, c) => n + c.weight, 0);
  const earned = checks.filter((c) => c.pass).reduce((n, c) => n + c.weight, 0);
  const score = Math.round((earned / total) * 100);
  const blockers = checks.filter((c) => c.blocker && !c.pass);

  const band: DemoReadinessBand =
    blockers.length === 0 && score >= 90 ? "Ready"
      : score >= 75 && blockers.length === 0 ? "Nearly ready"
        : score >= 60 ? "Nearly ready"
          : "Not ready";

  return {
    generatedAt: today,
    score,
    band,
    passed: checks.filter((c) => c.pass).length,
    total: checks.length,
    blockers,
    checks,
  };
}

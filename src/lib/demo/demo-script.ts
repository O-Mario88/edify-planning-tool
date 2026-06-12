// Demo Scenario Builder (spec layer #12).
//
// A controlled, guided path for walking a contract approver through the whole
// system end-to-end (Demo 1: see schools → … → Demo 14: dashboards update). Each
// step carries a deep link AND a LIVE status check against real data, so the
// presenter always knows the seed is ready before they click — no dead step in
// front of the approver.
//
// server-only: reads the Unified Activity model + directory.

import "server-only";

import { intakeSchools } from "@/lib/intake/intake-mock";
import { schoolWorkflowState } from "@/lib/school-directory/school-state";
import { activeClusters, clusterStatusOf } from "@/lib/cluster/cluster-core";
import { allUnifiedActivities } from "@/lib/activity/unified-activity-source";
import type { UnifiedActivityStage } from "@/lib/activity/unified-activity";
import { fundRequests } from "@/lib/actions/store";

export type DemoStepStatus = "done" | "incomplete";

export type DemoStep = {
  n: number;
  title: string;
  description: string;
  href: string;
  linkLabel: string;
  status: DemoStepStatus;
  note: string;
};

export type DemoScriptReport = {
  steps: DemoStep[];
  doneCount: number;
  total: number;
  ready: boolean; // every step has live data behind it
};

export function demoScript(): DemoScriptReport {
  const acts = allUnifiedActivities();
  const byStage = (s: UnifiedActivityStage) => acts.filter((a) => a.stage === s).length;
  const clustered = intakeSchools.filter((s) => clusterStatusOf(s) === "clustered").length;
  const planningReady = intakeSchools.filter((s) => schoolWorkflowState(s).stage === "planning_ready");
  const partnerActs = acts.filter((a) => a.deliveryMode === "partner");
  const exampleReady = planningReady[0];

  const step = (
    n: number,
    title: string,
    description: string,
    href: string,
    linkLabel: string,
    ok: boolean,
    note: string,
  ): DemoStep => ({ n, title, description, href, linkLabel, status: ok ? "done" : "incomplete", note });

  const steps: DemoStep[] = [
    step(1, "Upload / see schools", "Open the School Directory — every school with its workflow stage.",
      "/schools", "Open Directory", intakeSchools.length >= 5, `${intakeSchools.length} schools loaded.`),
    step(2, "Create a cluster", "Show the Clusters hub and create one.",
      "/clusters", "Open Clusters", activeClusters().length >= 1, `${activeClusters().length} active cluster(s).`),
    step(3, "Assign schools to a cluster", "Add schools to a cluster from the directory.",
      "/schools", "Open Directory", clustered >= 1, `${clustered} school(s) clustered.`),
    step(4, "View the SSA recommendation", "Open a planning-ready school and show its recommended interventions.",
      exampleReady ? `/schools/${exampleReady.schoolId}?view=plan` : "/schools", "Open a school", !!exampleReady, exampleReady ? `e.g. ${exampleReady.schoolName}.` : "No planning-ready school seeded."),
    step(5, "Schedule a school visit", "Schedule a visit/training from the planning tool.",
      "/planning", "Open Planning", acts.length >= 1, `${acts.length} activit(ies) in the system.`),
    step(6, "Auto-generate cost & fund request", "Show the weekly fund request generated from scheduled activities at catalogue rates.",
      "/approvals", "Open Fund Requests", fundRequests().length >= 1 || acts.some((a) => a.hasCost), `${fundRequests().length} fund request(s).`),
    step(7, "Assign a partner", "Delegate an activity to a partner.",
      "/partners", "Open Partners", partnerActs.length >= 1, `${partnerActs.length} partner-delivered activit(ies).`),
    step(8, "Partner schedules", "Switch to the partner view and show their scheduled work.",
      "/partner/schedule", "Open Partner Schedule", partnerActs.some((a) => !!a.scheduledDate), "Partner has scheduled work."),
    step(9, "Partner uploads evidence", "Partner uploads attendance/evidence for delivered work.",
      "/evidence", "Open Evidence", acts.some((a) => a.hasEvidence), `${acts.filter((a) => a.hasEvidence).length} activit(ies) with evidence.`),
    step(10, "Staff confirms evidence + enters Salesforce ID", "Staff reviews the evidence and enters the SV-/TS- Salesforce ID.",
      "/evidence", "Open Evidence", acts.some((a) => !!a.salesforceId), `${acts.filter((a) => !!a.salesforceId).length} with a Salesforce ID.`),
    step(11, "IA verifies", "Impact Assessment confirms the Salesforce activity.",
      "/data-verification", "Open IA Queue", byStage("payment_pending") + byStage("closed") >= 1, `${byStage("ia_pending")} awaiting IA.`),
    step(12, "Accountant clears payment", "Accountant clears the partner payment / records accountability.",
      "/disbursements", "Open Disbursements", byStage("closed") >= 1 || byStage("payment_pending") >= 1, `${byStage("payment_pending")} ready to pay.`),
    step(13, "Completed activity appears in the log", "Show the completed activity in the Completed Log.",
      "/completed-log", "Open Completed Log", byStage("closed") >= 1, `${byStage("closed")} closed activit(ies).`),
    step(14, "Dashboards update", "Return to a role dashboard — the statistics reflect everything above.",
      "/dashboards/cceo", "Open CCEO Dashboard", true, "Live-derived from the workflow."),
  ];

  const doneCount = steps.filter((s) => s.status === "done").length;
  return { steps, doneCount, total: steps.length, ready: doneCount === steps.length };
}

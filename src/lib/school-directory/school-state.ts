// School Directory — the single source-of-truth status for a school.
//
// Every uploaded school flows through one pipeline:
//   Owner → Cluster → SSA → Planning
// schoolWorkflowState() collapses owner-mapping, duplicate risk, clustering and
// SSA into ONE canonical stage + the stage-appropriate next actions, so the
// directory, the School 360 record, planning, and dashboards all read the same
// truth. Activities link back to the school via schoolId / clusterId.

import { intakeSchools, ssaUploads, type IntakeSchool } from "@/lib/intake/intake-mock";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { clusterStatusOf, clusterById, meetingsForCluster, CLUSTER_MEETING_LABEL, type ClusterMeeting } from "@/lib/cluster/cluster-core";
import { openDuplicateCandidates } from "@/lib/intake/duplicate-candidates-mock";

export type SchoolStage =
  | "needs_owner"
  | "unclustered"
  | "ssa_required"
  | "planning_ready";

export type SchoolNextAction = {
  key: "map_owner" | "add_to_cluster" | "schedule_sit" | "assign_ssa_partner" | "schedule_ssa_self" | "upload_ssa" | "plan_support" | "view_cluster";
  label: string;
  /** Where the action is executed (the school record is the launch point). */
  href?: string;
  primary?: boolean;
};

export type SchoolWorkflowState = {
  schoolId: string;
  stage: SchoolStage;
  stageLabel: string;
  /** Short reason the school isn't planning-ready yet (when it isn't). */
  blocker?: string;
  /** Non-blocking flags (duplicate review pending, etc.). */
  flags: string[];
  ownerStatus: "matched" | "unmatched" | "none";
  clustered: boolean;
  clusterId?: string;
  clusterName?: string;
  ssaDone: boolean;
  duplicatePending: boolean;
  nextActions: SchoolNextAction[];
};

const STAGE_LABEL: Record<SchoolStage, string> = {
  needs_owner: "Setup — needs account owner",
  unclustered: "Unclustered — assign first",
  ssa_required: "SSA required — planning locked",
  planning_ready: "Planning ready",
};

/** The canonical per-school workflow state. */
export function schoolWorkflowState(s: IntakeSchool): SchoolWorkflowState {
  const owner = resolveOwner(s.assignedCceo);
  const clustered = clusterStatusOf(s) === "clustered";
  const ssaDone = s.ssaStatus === "SSA Done";
  const duplicatePending = openDuplicateCandidates().some((d) => d.schoolId === s.schoolId);
  const cluster = clusterById(s.clusterId);

  const flags: string[] = [];
  if (duplicatePending) flags.push("Duplicate review pending");

  let stage: SchoolStage;
  let blocker: string | undefined;
  const nextActions: SchoolNextAction[] = [];

  if (owner.status !== "matched") {
    stage = "needs_owner";
    blocker = owner.status === "unmatched"
      ? `Account owner "${owner.name}" isn't a registered staff member.`
      : "No account owner assigned.";
    nextActions.push({ key: "map_owner", label: "Map account owner", href: "/data-intake/queue", primary: true });
  } else if (!clustered) {
    stage = "unclustered";
    blocker = "Not in a cluster yet — clustering unlocks SSA / SIT and planning.";
    nextActions.push({ key: "add_to_cluster", label: "Add to Cluster", primary: true });
  } else if (!ssaDone) {
    stage = "ssa_required";
    blocker = "No current-FY SSA — complete it via SIT, a partner, or yourself.";
    nextActions.push(
      { key: "schedule_sit", label: "Schedule SIT", href: s.clusterId ? `/clusters/${s.clusterId}` : undefined, primary: true },
      { key: "assign_ssa_partner", label: "Assign SSA to partner", href: "/planning" },
      { key: "schedule_ssa_self", label: "Schedule SSA myself", href: "/planning" },
      { key: "upload_ssa", label: "Upload SSA (IA)", href: "/data-intake/upload" },
    );
  } else {
    stage = "planning_ready";
    nextActions.push({ key: "plan_support", label: "Plan support", href: "/planning", primary: true });
  }

  if (cluster) nextActions.push({ key: "view_cluster", label: "View cluster", href: `/clusters/${cluster.id}` });

  return {
    schoolId: s.schoolId,
    stage,
    stageLabel: STAGE_LABEL[stage],
    blocker,
    flags,
    ownerStatus: owner.status,
    clustered,
    clusterId: s.clusterId,
    clusterName: s.cluster,
    ssaDone,
    duplicatePending,
    nextActions,
  };
}

/** All activities that link back to a school: its cluster's meetings + SSA uploads. */
export type LinkedActivity = {
  kind: "cluster_meeting" | "ssa_upload";
  label: string;
  date: string;
  status: string;
  ref?: string;
};

export function schoolLinkedActivities(s: IntakeSchool): LinkedActivity[] {
  const out: LinkedActivity[] = [];
  // SSA uploads for this school
  for (const u of ssaUploads.filter((x) => x.schoolId === s.schoolId)) {
    out.push({
      kind: "ssa_upload",
      label: `SSA performance (avg ${u.averageScore}/10)`,
      date: u.ssaDate,
      status: `${u.quarter} FY ${u.fy}`,
    });
  }
  // Cluster meetings the school participates in (via its cluster)
  if (s.clusterId) {
    for (const m of meetingsForCluster(s.clusterId)) {
      out.push({
        kind: "cluster_meeting",
        label: CLUSTER_MEETING_LABEL[m.kind],
        date: m.date,
        status: m.status,
        ref: m.salesforceTrainingId,
      });
    }
  }
  return out.sort((a, b) => (a.date < b.date ? 1 : -1));
}

/** Directory-wide stage rollup (for the directory header / dashboards). */
export function schoolStageCounts(schools: IntakeSchool[] = intakeSchools) {
  const counts: Record<SchoolStage, number> = { needs_owner: 0, unclustered: 0, ssa_required: 0, planning_ready: 0 };
  for (const s of schools) counts[schoolWorkflowState(s).stage] += 1;
  return counts;
}

// Server-only aggregator for the Unified Activity Record (spec layer #6).
//
// Reads the three live activity stores and projects each through the pure
// mappers in `unified-activity.ts`. This is the single read entry point for the
// Next-Best-Action engine, the Workflow Health Monitor, the per-school Timeline,
// the country Data-Quality score, and the Demo Readiness check.
//
// server-only because PlannedActivity lives in the globalThis-backed store
// (src/lib/actions/store.ts). Cluster meetings + project activities are
// client-safe arrays, but we aggregate them here so callers have ONE accessor.

import "server-only";

import { activities, trainingParticipants } from "@/lib/actions/store";
import { clusterMeetings } from "@/lib/cluster/cluster-core";
import { projectActivities } from "@/lib/projects/project-activities";
import {
  fromPlannedActivity,
  fromClusterMeeting,
  fromProjectActivity,
  type UnifiedActivity,
} from "./unified-activity";

/** Evidence proxy for a planned activity: any captured training participant. */
function plannedHasEvidence(activityId: string): boolean {
  return trainingParticipants().some(
    (p) => p.activityId === activityId && p.evidenceStatus !== "None",
  );
}

/** Every activity in the system, projected onto the one canonical shape. */
export function allUnifiedActivities(): UnifiedActivity[] {
  const planned = activities().map((a) =>
    fromPlannedActivity(a, { hasEvidence: plannedHasEvidence(a.id) }),
  );
  const cluster = clusterMeetings.map(fromClusterMeeting);
  const project = projectActivities.map(fromProjectActivity);
  return [...planned, ...cluster, ...project];
}

export function unifiedActivitiesForSchool(schoolId: string): UnifiedActivity[] {
  return allUnifiedActivities().filter((a) => a.schoolId === schoolId);
}

export function unifiedActivitiesForCluster(clusterId: string): UnifiedActivity[] {
  return allUnifiedActivities().filter((a) => a.clusterId === clusterId);
}

export function unifiedActivitiesForProject(projectId: string): UnifiedActivity[] {
  return allUnifiedActivities().filter((a) => a.projectId === projectId);
}

export function unifiedActivityById(id: string): UnifiedActivity | undefined {
  return allUnifiedActivities().find((a) => a.id === id);
}

/** Activities assigned to a given staff/partner id (for My Plan / next-action). */
export function unifiedActivitiesForAssignee(assigneeId: string): UnifiedActivity[] {
  return allUnifiedActivities().filter((a) => a.assignedToId === assigneeId);
}

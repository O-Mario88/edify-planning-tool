// Operational Timeline (spec layer #4).
//
// Every school's story as one chronological thread: Uploaded → SSA → Cluster →
// Recommendation → Scheduled → Evidence → Salesforce ID → IA verified → Payment
// → SSA improved. Aggregated from the intake record, SSA uploads, cluster
// assignment, and the Unified Activity model (layer #6) — so CD/PL/IA/donors can
// answer "what happened with this school?" at a glance, and debugging is trivial.
//
// server-only: reads the unified activity aggregator.

import "server-only";

import { intakeSchools, ssaUploads } from "@/lib/intake/intake-mock";
import { clusterAssignments, clusterById } from "@/lib/cluster/cluster-core";
import { unifiedActivitiesForSchool } from "@/lib/activity/unified-activity-source";

export type TimelineEventKind =
  | "uploaded"
  | "ssa_uploaded"
  | "cluster_assigned"
  | "recommendation"
  | "scheduled"
  | "evidence"
  | "salesforce"
  | "ia_verified"
  | "payment"
  | "ssa_improved";

export type TimelineEvent = {
  kind: TimelineEventKind;
  date: string; // ISO date
  title: string;
  detail?: string;
  done: boolean;
};

/** Ordering when two events share a date — follows the lifecycle. */
const KIND_ORDER: Record<TimelineEventKind, number> = {
  uploaded: 0, ssa_uploaded: 1, cluster_assigned: 2, recommendation: 3,
  scheduled: 4, evidence: 5, salesforce: 6, ia_verified: 7, payment: 8, ssa_improved: 9,
};

export function schoolTimeline(schoolId: string): TimelineEvent[] {
  const school = intakeSchools.find((s) => s.schoolId === schoolId);
  if (!school) return [];
  const events: TimelineEvent[] = [];

  // 1. Uploaded to the directory.
  if (school.dateAdded) {
    events.push({
      kind: "uploaded",
      date: school.dateAdded,
      title: "Uploaded to School Directory",
      detail: school.addedBy ? `Added by ${school.addedBy}` : undefined,
      done: true,
    });
  }

  // 2. SSA uploads (+ improvement detection).
  const ssas = ssaUploads
    .filter((u) => u.schoolId === schoolId)
    .slice()
    .sort((a, b) => (a.ssaDate < b.ssaDate ? -1 : 1));
  ssas.forEach((u, i) => {
    events.push({
      kind: "ssa_uploaded",
      date: u.ssaDate,
      title: `SSA uploaded — avg ${u.averageScore}/10`,
      done: true,
    });
    if (i > 0) {
      const delta = Math.round((u.averageScore - ssas[i - 1].averageScore) * 10) / 10;
      if (delta > 0) {
        events.push({
          kind: "ssa_improved",
          date: u.ssaDate,
          title: `SSA improved +${delta}`,
          detail: `${ssas[i - 1].averageScore} → ${u.averageScore}/10`,
          done: true,
        });
      }
    }
  });

  // 3. Cluster assignment (real assignment date).
  const assignment = clusterAssignments.find((a) => a.schoolId === schoolId && a.isActive);
  if (assignment) {
    const cluster = clusterById(assignment.clusterId);
    events.push({
      kind: "cluster_assigned",
      date: assignment.assignedAt,
      title: `Assigned to cluster${cluster ? ` — ${cluster.name}` : ""}`,
      detail: assignment.assignedBy ? `By ${assignment.assignedBy}` : undefined,
      done: true,
    });
  }

  // 4. Recommendation generated (derives from the latest SSA).
  if (ssas.length > 0) {
    events.push({
      kind: "recommendation",
      date: ssas[ssas.length - 1].ssaDate,
      title: "Recommended intervention generated",
      detail: "From the school's two weakest SSA interventions.",
      done: true,
    });
  }

  // 5. Activities — schedule event + current milestone for each.
  for (const a of unifiedActivitiesForSchool(schoolId)) {
    const schedDate = a.scheduledDate ?? a.createdAt;
    if (schedDate) {
      events.push({
        kind: "scheduled",
        date: schedDate,
        title: `${a.type} scheduled`,
        detail: a.intervention ?? undefined,
        done: a.stage !== "planned",
      });
    }
    const at = a.updatedAt ?? schedDate ?? school.dateAdded;
    if (!at) continue;
    if (a.paymentStatus === "cleared") {
      events.push({ kind: "payment", date: at, title: `Payment / accountability cleared`, detail: a.type, done: true });
    } else if (a.iaStatus === "confirmed") {
      events.push({ kind: "ia_verified", date: at, title: `IA verified`, detail: a.type, done: true });
    } else if (a.salesforceId) {
      events.push({ kind: "salesforce", date: at, title: `Salesforce ID entered — ${a.salesforceId}`, detail: a.type, done: true });
    } else if (a.hasEvidence) {
      events.push({ kind: "evidence", date: at, title: `Evidence uploaded`, detail: a.type, done: true });
    }
  }

  return events.sort((x, y) => {
    if (x.date === y.date) return KIND_ORDER[x.kind] - KIND_ORDER[y.kind];
    return x.date < y.date ? -1 : 1;
  });
}

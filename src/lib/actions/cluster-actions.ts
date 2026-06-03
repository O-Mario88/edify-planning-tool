"use server";

// Cluster assignment server actions — the write path behind the mandatory
// Cluster Assignment Gate.
//
// After a school is uploaded and mapped to its account owner, staff assign it
// to a cluster here. Clustering creates planning structure (it drives SIT, SSA,
// cluster meetings, partner assignment, travel, and reporting) but never
// changes ownership — the school stays in its account owner's portfolio.
//
// Who can assign: Staff/CCEO, Program Lead, Country Director, IA, Admin.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut } from "./audit";
import {
  assignSchoolToCluster,
  assignClusterToPartner,
  bulkAssign,
  createCluster,
  createClusterAndAssign,
  removeFromCluster,
  validateNewCluster,
  type ClusterActor,
  type NewClusterInput,
} from "@/lib/cluster/cluster-core";
import { partners } from "@/lib/partner/partner-mock";

const CLUSTER_ROLES = new Set<string>([
  "CCEO",
  "CountryProgramLead",
  "CountryDirector",
  "ImpactAssessment",
  "Admin",
]);

export type ClusterActionResult<T = Record<string, unknown>> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "INVALID_INPUT"; errors: Record<string, string> }
  | { ok: false; reason: "FAILED"; message: string };

async function actorOrForbidden(): Promise<ClusterActor | null> {
  const user = await getCurrentUser();
  if (!CLUSTER_ROLES.has(user.role)) return null;
  return { name: user.name, role: user.role };
}

function revalidateClusterSurfaces() {
  try {
    revalidatePath("/clusters");
    revalidatePath("/clusters/assign");
    revalidatePath("/planning");
    revalidatePath("/portfolio");
    revalidatePath("/analytics");
    revalidatePath("/notifications");
  } catch {
    /* outside request */
  }
}

// ─── Assign selected schools to an existing cluster ─────────────────

export async function assignToExistingClusterAction(
  schoolIds: string[],
  clusterId: string,
): Promise<ClusterActionResult<{ assigned: number; failed: { schoolId: string; reason: string }[] }>> {
  const actor = await actorOrForbidden();
  if (!actor) return { ok: false, reason: "FORBIDDEN" };
  if (!schoolIds.length) return { ok: false, reason: "FAILED", message: "Select at least one school." };

  const { assigned, failed } = bulkAssign(schoolIds, clusterId, actor);
  if (assigned.length > 0) {
    emitAudit({
      action: "cluster.schoolsAssigned",
      subjectKind: "Cluster",
      subjectId: clusterId,
      actorId: actor.name,
      actorRole: actor.role,
      actorName: actor.name,
      payload: { clusterId, assigned: assigned.length, failed: failed.length, schoolIds: assigned },
    });
    emitNotificationFanOut(["CCEO", "PROGRAM_LEAD"], {
      template: "cluster.schoolsAssigned",
      channel: "Inbox",
      title: `${assigned.length} school${assigned.length === 1 ? "" : "s"} clustered`,
      body: `${assigned.length} school${assigned.length === 1 ? "" : "s"} assigned to a cluster — SSA / SIT planning is now unlocked.`,
      href: "/clusters/assign",
    });
    revalidateClusterSurfaces();
  }
  return { ok: true, assigned: assigned.length, failed };
}

// ─── Create a new cluster and assign selected schools ───────────────

export async function createClusterAndAssignAction(
  schoolIds: string[],
  input: Partial<NewClusterInput> & { name: string },
): Promise<ClusterActionResult<{ clusterId: string; clusterName: string; assigned: number }>> {
  const actor = await actorOrForbidden();
  if (!actor) return { ok: false, reason: "FORBIDDEN" };

  // Validate the cluster shell first (name uniqueness, required geography).
  // Sub-counties are derived from the selected schools when not supplied.
  const v = validateNewCluster({
    name: input.name,
    region: input.region ?? "",
    district: input.district ?? "",
    subCounties: input.subCounties ?? ["—"],
  });
  if (!v.ok) return { ok: false, reason: "INVALID_INPUT", errors: v.errors };

  const res = createClusterAndAssign(schoolIds, input, actor);
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };

  emitAudit({
    action: "cluster.created",
    subjectKind: "Cluster",
    subjectId: res.cluster.id,
    actorId: actor.name,
    actorRole: actor.role,
    actorName: actor.name,
    payload: {
      name: res.cluster.name,
      district: res.cluster.district,
      subCounty: res.cluster.subCounty,
      assigned: res.result.assigned.length,
    },
  });
  emitNotificationFanOut(["CCEO", "PROGRAM_LEAD"], {
    template: "cluster.created",
    channel: "Inbox",
    title: `Cluster ${res.cluster.name} created`,
    body: `${res.result.assigned.length} school${res.result.assigned.length === 1 ? "" : "s"} attached to ${res.cluster.name} (${res.cluster.district}). SSA / SIT planning unlocked.`,
    href: "/clusters/assign",
  });
  revalidateClusterSurfaces();
  return { ok: true, clusterId: res.cluster.id, clusterName: res.cluster.name, assigned: res.result.assigned.length };
}

// ─── Create an empty cluster (no schools yet) ───────────────────────

export async function createEmptyClusterAction(
  input: NewClusterInput,
): Promise<ClusterActionResult<{ clusterId: string; clusterName: string }>> {
  const actor = await actorOrForbidden();
  if (!actor) return { ok: false, reason: "FORBIDDEN" };
  const v = validateNewCluster(input);
  if (!v.ok) return { ok: false, reason: "INVALID_INPUT", errors: v.errors };
  const cluster = createCluster(input, actor);
  emitAudit({
    action: "cluster.created",
    subjectKind: "Cluster",
    subjectId: cluster.id,
    actorId: actor.name,
    actorRole: actor.role,
    actorName: actor.name,
    payload: { name: cluster.name, district: cluster.district, subCounty: cluster.subCounty },
  });
  revalidateClusterSurfaces();
  return { ok: true, clusterId: cluster.id, clusterName: cluster.name };
}

// ─── Delegate a cluster to a partner to manage ──────────────────────

export async function assignClusterToPartnerAction(
  clusterId: string,
  partnerId: string,
): Promise<ClusterActionResult<{ partnerName: string }>> {
  const actor = await actorOrForbidden();
  if (!actor) return { ok: false, reason: "FORBIDDEN" };

  // Empty partnerId clears the delegation; otherwise resolve the partner name.
  const partner = partnerId ? partners.find((p) => p.id === partnerId) : undefined;
  if (partnerId && !partner) return { ok: false, reason: "FAILED", message: "Partner not found." };

  const res = assignClusterToPartner(clusterId, partnerId, partner?.name ?? "", actor);
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };

  emitAudit({
    action: partnerId ? "cluster.delegatedToPartner" : "cluster.partnerCleared",
    subjectKind: "Cluster",
    subjectId: clusterId,
    actorId: actor.name,
    actorRole: actor.role,
    actorName: actor.name,
    payload: { partnerId, partnerName: partner?.name },
  });
  if (partnerId) {
    emitNotificationFanOut(["CCEO", "PROGRAM_LEAD"], {
      template: "cluster.delegatedToPartner",
      channel: "Inbox",
      title: `${res.cluster.name} delegated to ${partner!.name}`,
      body: `${partner!.name} will manage ${res.cluster.name} (${res.cluster.district}). Account ownership stays with the staff member.`,
      href: "/clusters",
    });
  }
  revalidateClusterSurfaces();
  return { ok: true, partnerName: partner?.name ?? "" };
}

// ─── Single-school assign / remove (row actions + IA correction) ────

export async function assignSchoolAction(
  schoolId: string,
  clusterId: string,
): Promise<ClusterActionResult> {
  const actor = await actorOrForbidden();
  if (!actor) return { ok: false, reason: "FORBIDDEN" };
  const r = assignSchoolToCluster(schoolId, clusterId, actor);
  if (!r.ok) return { ok: false, reason: "FAILED", message: r.reason };
  emitAudit({
    action: "cluster.schoolAssigned",
    subjectKind: "School",
    subjectId: schoolId,
    actorId: actor.name,
    actorRole: actor.role,
    actorName: actor.name,
    payload: { clusterId },
  });
  revalidateClusterSurfaces();
  return { ok: true };
}

export async function removeSchoolFromClusterAction(
  schoolId: string,
  reason?: string,
): Promise<ClusterActionResult> {
  const actor = await actorOrForbidden();
  if (!actor) return { ok: false, reason: "FORBIDDEN" };
  const r = removeFromCluster(schoolId, actor, reason);
  if (!r.ok) return { ok: false, reason: "FAILED", message: r.reason };
  emitAudit({
    action: "cluster.schoolRemoved",
    subjectKind: "School",
    subjectId: schoolId,
    actorId: actor.name,
    actorRole: actor.role,
    actorName: actor.name,
    payload: { reason },
  });
  revalidateClusterSurfaces();
  return { ok: true };
}

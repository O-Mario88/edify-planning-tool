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
  updateClusterLeader,
  scheduleClusterMeeting,
  recordClusterActivitySalesforce,
  iaConfirmClusterActivity,
  accountantPayClusterActivity,
  returnClusterActivity,
  clusterActivityById,
  clusterById,
  bulkAssign,
  createCluster,
  createClusterAndAssign,
  removeFromCluster,
  validateNewCluster,
  CLUSTER_MEETING_LABEL,
  type ClusterActor,
  type ClusterMeetingKind,
  type ClusterMeetingOrganizer,
  type NewClusterInput,
} from "@/lib/cluster/cluster-core";
import { partners } from "@/lib/partner/partner-mock";
import { getCurrentPartner } from "@/lib/partner/partner-identity";

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

// ─── Edit a cluster's leader ────────────────────────────────────────

export async function updateClusterLeaderAction(
  clusterId: string,
  name: string,
  phone: string,
  schoolId?: string,
): Promise<ClusterActionResult> {
  const actor = await actorOrForbidden();
  if (!actor) return { ok: false, reason: "FORBIDDEN" };
  const res = updateClusterLeader(clusterId, { name, phone, schoolId }, actor);
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };
  emitAudit({
    action: "cluster.leaderChanged",
    subjectKind: "Cluster",
    subjectId: clusterId,
    actorId: actor.name,
    actorRole: actor.role,
    actorName: actor.name,
    payload: { name, phone },
  });
  revalidateClusterSurfaces();
  return { ok: true };
}

// ─── Schedule a cluster meeting (partner OR Edify staff) ────────────

export async function scheduleClusterMeetingAction(
  clusterId: string,
  kind: ClusterMeetingKind,
  isoDate: string,
  participants?: number,
  notes?: string,
): Promise<ClusterActionResult<{ label: string; organizer: ClusterMeetingOrganizer }>> {
  const cluster = clusterById(clusterId);
  if (!cluster) return { ok: false, reason: "FAILED", message: "Cluster not found." };

  // A delegated partner manages their own clusters; staff schedule Edify activities.
  const partner = await getCurrentPartner();
  let actor: ClusterActor;
  let organizer: ClusterMeetingOrganizer;
  if (partner) {
    if (cluster.managedByPartnerId !== partner.id) {
      return { ok: false, reason: "FORBIDDEN" };
    }
    actor = { name: partner.name, role: "Partner" };
    organizer = "partner";
  } else {
    const staff = await actorOrForbidden();
    if (!staff) return { ok: false, reason: "FORBIDDEN" };
    actor = staff;
    organizer = "edify";
  }

  const res = scheduleClusterMeeting(clusterId, { kind, date: isoDate, participants, notes }, actor, organizer);
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };

  emitAudit({
    action: "cluster.meetingScheduled",
    subjectKind: "Cluster",
    subjectId: clusterId,
    actorId: actor.name,
    actorRole: actor.role,
    actorName: actor.name,
    payload: { kind, date: isoDate, organizer, participants },
  });
  // Cross-notify the other side: partner → CCEO/PL; Edify staff → the partner.
  emitNotificationFanOut(organizer === "partner" ? ["CCEO", "PROGRAM_LEAD"] : ["PARTNER"], {
    template: "cluster.meetingScheduled",
    channel: "Inbox",
    title: `${CLUSTER_MEETING_LABEL[kind]} scheduled — ${cluster.name}`,
    body: `${actor.name} scheduled ${CLUSTER_MEETING_LABEL[kind]} for ${cluster.name} on ${isoDate}.`,
    href: organizer === "partner" ? "/clusters" : "/partner/clusters",
  });
  try {
    revalidatePath("/partner/clusters");
    revalidatePath("/partner/today");
  } catch { /* outside request */ }
  revalidateClusterSurfaces();
  return { ok: true, label: CLUSTER_MEETING_LABEL[kind], organizer };
}

// ─── Cluster-activity lifecycle (TS- → IA confirm → accountant pay) ─

/** Executor (partner managing the cluster OR Edify staff) records TS + attendance. */
export async function recordClusterActivityAction(
  activityId: string,
  salesforceTrainingId: string,
  teachersCount: number,
  schoolLeadersCount: number,
  otherCount?: number,
): Promise<ClusterActionResult> {
  const a = clusterActivityById(activityId);
  if (!a) return { ok: false, reason: "FAILED", message: "Activity not found." };
  const partner = await getCurrentPartner();
  let actor: ClusterActor;
  if (partner) {
    const cluster = clusterById(a.clusterId);
    if (cluster?.managedByPartnerId !== partner.id) return { ok: false, reason: "FORBIDDEN" };
    actor = { name: partner.name, role: "Partner" };
  } else {
    const staff = await actorOrForbidden();
    if (!staff) return { ok: false, reason: "FORBIDDEN" };
    actor = staff;
  }
  const res = recordClusterActivitySalesforce(activityId, { salesforceTrainingId, teachersCount, schoolLeadersCount, otherCount }, actor);
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };
  emitAudit({
    action: "cluster.activitySalesforceRecorded", subjectKind: "Cluster", subjectId: a.clusterId,
    actorId: actor.name, actorRole: actor.role, actorName: actor.name,
    payload: { activityId, salesforceTrainingId, total: res.activity.totalParticipants },
  });
  emitNotificationFanOut(["IMPACT_ASSESSMENT"], {
    template: "cluster.awaitingIa", channel: "Inbox",
    title: "Cluster activity awaiting Salesforce confirmation",
    body: `${CLUSTER_MEETING_LABEL[a.kind]} (${salesforceTrainingId}) needs IA confirmation.`,
    href: "/data-intake/clusters",
  });
  revalidateClusterSurfaces();
  return { ok: true };
}

const IA_ROLES = new Set<string>(["ImpactAssessment", "Admin"]);
const ACCOUNTANT_ROLES = new Set<string>(["ProgramAccountant", "Admin"]);

/** IA confirms the Salesforce training record — makes the activity count. */
export async function iaConfirmClusterActivityAction(activityId: string): Promise<ClusterActionResult> {
  const user = await getCurrentUser();
  if (!IA_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const res = iaConfirmClusterActivity(activityId, { name: user.name, role: user.role });
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };
  emitAudit({
    action: "cluster.activityIaConfirmed", subjectKind: "Cluster", subjectId: res.activity.clusterId,
    actorId: user.staffId, actorRole: user.role, actorName: user.name,
    payload: { activityId, salesforceTrainingId: res.activity.salesforceTrainingId },
  });
  if (res.activity.organizer === "partner") {
    emitNotificationFanOut(["PROGRAM_ACCOUNTANT"], {
      template: "cluster.paymentReady", channel: "Inbox",
      title: "Partner cluster payment ready",
      body: `${CLUSTER_MEETING_LABEL[res.activity.kind]} confirmed — partner payment can be cleared.`,
      href: "/disbursements",
    });
  }
  revalidateClusterSurfaces();
  return { ok: true };
}

/** Accountant clears partner payment — only after IA confirmation. */
export async function payClusterActivityAction(activityId: string): Promise<ClusterActionResult> {
  const user = await getCurrentUser();
  if (!ACCOUNTANT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const res = accountantPayClusterActivity(activityId, { name: user.name, role: user.role });
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };
  emitAudit({
    action: "cluster.activityPaid", subjectKind: "Cluster", subjectId: res.activity.clusterId,
    actorId: user.staffId, actorRole: user.role, actorName: user.name,
    payload: { activityId },
  });
  revalidateClusterSurfaces();
  return { ok: true };
}

/** Return an activity for correction (IA / PL / CD / Admin). */
export async function returnClusterActivityAction(activityId: string, reason: string): Promise<ClusterActionResult> {
  const actor = await actorOrForbidden();
  if (!actor) return { ok: false, reason: "FORBIDDEN" };
  const res = returnClusterActivity(activityId, reason, actor);
  if (!res.ok) return { ok: false, reason: "FAILED", message: res.reason };
  emitAudit({
    action: "cluster.activityReturned", subjectKind: "Cluster", subjectId: res.activity.clusterId,
    actorId: actor.name, actorRole: actor.role, actorName: actor.name, payload: { activityId, reason },
  });
  revalidateClusterSurfaces();
  return { ok: true };
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

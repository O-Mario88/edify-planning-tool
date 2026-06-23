"use server";

// W8 — Partner workflow server actions.
//
// State machine on PartnerActivity:
//   Planned → Delivered → CceoConfirmed → MeVerified → (paid)
//                                       ↘ Rejected
//
// Payment gate (integrity rule #6): a PartnerActivity can only have a
// Disbursement record created against it when status === MeVerified.
// `createPartnerDisbursement` enforces this server-side.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { storage, observability } from "@/lib/infra";
import { isBackendEnabled } from "@/lib/api/backend";
import { emitAudit, emitNotificationFanOut } from "./audit";
import {
  type DonorEvidenceStatus,
  type DonorCountStatus,
  type InterventionArea,
  type PartnerActivityRecord,
  type PartnerActivityStatus,
  claimIdempotencyKey,
  findPartnerActivity,
  newId,
  partnerActivities as partnerActivitiesStore,
  updatePartnerActivity,
} from "./store";

export type PartnerActionResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_FOUND" }
  | { ok: false; reason: "INVALID_STATE"; current: PartnerActivityStatus }
  | { ok: false; reason: "INVALID_INPUT"; field: string }
  | { ok: false; reason: "PAYMENT_GATE_BLOCKED"; details: string }
  | { ok: false; reason: "DUPLICATE" };

// Role gates
const PARTNER_ROLES = new Set(["PartnerAdmin", "PartnerFieldOfficer", "Admin"]);
const CCEO_ROLES    = new Set(["CCEO", "Admin"]);
const PL_ROLES      = new Set(["CountryProgramLead", "Admin"]);
const ME_ROLES      = new Set(["ImpactAssessment", "Admin"]);
const ACCT_ROLES    = new Set(["ProgramAccountant", "Admin"]);

// ─── 1. assignPartnerActivity (CCEO assigns a partner to a school) ──

export async function assignPartnerActivity(input: {
  partnerId: string;
  partnerName: string;
  schoolId: string;
  interventionArea: InterventionArea;
  title: string;
  date: string;
  costUgxCents?: number;
}): Promise<PartnerActionResult> {
  const user = await getCurrentUser();
  if (!CCEO_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!input.partnerId)   return { ok: false, reason: "INVALID_INPUT", field: "partnerId" };
  if (!input.schoolId)    return { ok: false, reason: "INVALID_INPUT", field: "schoolId" };
  if (!input.title || input.title.trim().length < 3) {
    return { ok: false, reason: "INVALID_INPUT", field: "title" };
  }
  const now = new Date().toISOString();
  const row: PartnerActivityRecord = {
    id: newId("pa"),
    partnerId: input.partnerId,
    partnerName: input.partnerName,
    schoolId: input.schoolId,
    interventionArea: input.interventionArea,
    title: input.title.trim(),
    date: input.date,
    status: "Planned",
    evidenceStatus: "None",
    donorCountStatus: "pending_evidence",
    costUgxCents: input.costUgxCents,
    createdAt: now,
    updatedAt: now,
  };
  partnerActivitiesStore().push(row);

  emitAudit({
    action: "partnerActivity.assigned",
    subjectKind: "PartnerActivity",
    subjectId: row.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { partnerId: input.partnerId, schoolId: input.schoolId },
  });
  // Tell the partner.
  emitNotificationFanOut([input.partnerId], {
    template: "partnerActivity.assigned",
    channel: "Inbox",
    title: `New activity assigned: ${input.title}`,
    body: `${user.name} assigned you a ${input.interventionArea} activity at ${input.schoolId}.`,
    href: `/partner/today`,
  });
  revalidatePartnerSurfaces(row.id);
  return { ok: true, id: row.id };
}

// ─── 2. partnerMarkDelivered ───────────────────────────────────────

export async function partnerMarkDelivered(
  activityId: string,
  input: { teachersReached?: number; leadersReached?: number; studentsReached?: number; notes?: string },
): Promise<PartnerActionResult> {
  const user = await getCurrentUser();
  if (!PARTNER_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const a = findPartnerActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (a.status !== "Planned") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  updatePartnerActivity(activityId, {
    status: "Delivered",
    teachersReached: input.teachersReached,
    leadersReached: input.leadersReached,
    studentsReached: input.studentsReached,
    evidenceNotes: input.notes,
    evidenceStatus: "Captured",
  });
  emitAudit({
    action: "partnerActivity.delivered",
    subjectKind: "PartnerActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: input,
  });
  // Tell the assigning CCEO so they can review & upload the evidence
  // confirmation — closes the "delivered silently, CCEO doesn't know"
  // gap surfaced by the cross-feature sync audit.
  emitNotificationFanOut(["CCEO_OWNER"], {
    template: "partnerActivity.delivered",
    channel: "Inbox",
    title: `Partner delivery complete: ${a.title}`,
    body: `${user.name} marked the activity delivered at ${a.schoolId}. Review & upload evidence to confirm.`,
    href: `/partner/evidence`,
  });
  revalidatePartnerSurfaces(activityId);
  return { ok: true, id: activityId };
}

// ─── 3. partnerUploadEvidence ──────────────────────────────────────
//
// Fixes the audit-flagged "broken evidence dropzone" — partners can
// upload evidence and the URI persists. Real storage is S3 via a
// presigned URL; mock-mode produces a deterministic stub.

export async function partnerUploadEvidence(args: {
  activityId: string;
  filename: string;
  contentLength: number;
  notes?: string;
}): Promise<PartnerActionResult & { uri?: string }> {
  const user = await getCurrentUser();
  if (!PARTNER_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  // Backend-first: real evidence is uploaded via POST /api/evidence/upload
  // (multipart → on-disk file + EvidenceRecord). This legacy path only writes a
  // stub URI into the in-memory store and is invisible to backend evidence
  // queries, so it is inert whenever the backend is on (mock/demo use only).
  if (isBackendEnabled()) return { ok: false, reason: "FORBIDDEN" };
  const a = findPartnerActivity(args.activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (a.status !== "Delivered") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  if (args.contentLength <= 0 || args.contentLength > 10 * 1024 * 1024) {
    return { ok: false, reason: "INVALID_INPUT", field: "contentLength" };
  }
  if (!args.filename) return { ok: false, reason: "INVALID_INPUT", field: "filename" };

  // Route through the storage adapter — dev returns a stub URI, S3
  // returns a presigned PUT URL + canonical s3:// URI.
  const plan = await storage.planUpload({
    kind: "partner-activity",
    subjectId: args.activityId,
    filename: args.filename,
    contentLength: args.contentLength,
  });
  updatePartnerActivity(args.activityId, {
    evidenceStatus: "Uploaded",
    evidenceUri: plan.uri,
    evidenceNotes: args.notes ?? a.evidenceNotes,
    donorCountStatus: "pending_verification",
  });

  emitAudit({
    action: "partnerActivity.evidenceUploaded",
    subjectKind: "PartnerActivity",
    subjectId: args.activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      uri: plan.uri,
      presigned: !!plan.presignedPutUrl,
      filename: args.filename,
      bytes: args.contentLength,
    },
  });
  // Tell the CCEO who owns confirmation.
  emitNotificationFanOut(["CCEO_OWNER"], {
    template: "partnerActivity.evidenceUploaded",
    channel: "Inbox",
    title: `Evidence uploaded for ${a.title}`,
    body: `${user.name} uploaded evidence at ${a.schoolId} — please confirm.`,
    href: `/partner/evidence`,
  });
  revalidatePartnerSurfaces(args.activityId);
  return { ok: true, id: args.activityId, uri: plan.uri };
}

// ─── 4. cceoConfirmPartnerActivity ─────────────────────────────────

export async function cceoConfirmPartnerActivity(
  activityId: string,
): Promise<PartnerActionResult> {
  const user = await getCurrentUser();
  if (!CCEO_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const a = findPartnerActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (a.status !== "Delivered") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  if (a.evidenceStatus !== "Uploaded" && a.evidenceStatus !== "Captured") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  updatePartnerActivity(activityId, {
    status: "CceoConfirmed",
    evidenceStatus: "CceoConfirmed",
    cceoConfirmedAt: new Date().toISOString(),
    cceoConfirmedById: user.staffId,
    donorCountStatus: "included_confirmed",
  });
  emitAudit({
    action: "partnerActivity.cceoConfirmed",
    subjectKind: "PartnerActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  // PL is now the next stop in the partner-payment chain (spec
  // CCEO → PL → IA → Accountant). The previous flow jumped CCEO
  // confirm straight to IA verification, leaving the PL invisible.
  emitNotificationFanOut(["PROGRAM_LEAD"], {
    template: "partnerActivity.pendingPlApproval",
    channel: "Inbox",
    title: `Partner activity ready for your approval: ${a.title}`,
    body: "CCEO confirmed delivery. Review & approve before IA verification.",
    href: `/data-verification`,
  });
  revalidatePartnerSurfaces(activityId);
  return { ok: true, id: activityId };
}

// ─── 4b. plApprovePartnerActivity (CCEO confirm → PL approve → IA) ──

export async function plApprovePartnerActivity(
  activityId: string,
): Promise<PartnerActionResult> {
  const user = await getCurrentUser();
  if (!PL_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const a = findPartnerActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (a.status !== "CceoConfirmed") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  updatePartnerActivity(activityId, {
    status: "PlApproved",
  });
  emitAudit({
    action: "partnerActivity.plApproved",
    subjectKind: "PartnerActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  emitNotificationFanOut(["IMPACT_ASSESSMENT"], {
    template: "partnerActivity.pendingMeVerification",
    channel: "Inbox",
    title: `Partner activity approved by PL: ${a.title}`,
    body: "PL signed off on the CCEO confirmation. Ready for M&E verification.",
    href: `/data-verification`,
  });
  revalidatePartnerSurfaces(activityId);
  return { ok: true, id: activityId };
}

// ─── 5. meVerifyPartnerActivity ────────────────────────────────────

export async function meVerifyPartnerActivity(
  activityId: string,
): Promise<PartnerActionResult> {
  const user = await getCurrentUser();
  if (!ME_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const a = findPartnerActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  // Accept PlApproved (the new canonical predecessor) or CceoConfirmed
  // (back-compat for activities started before the PL gate was wired).
  if (a.status !== "PlApproved" && a.status !== "CceoConfirmed") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  updatePartnerActivity(activityId, {
    status: "MeVerified",
    evidenceStatus: "MeVerified",
    meVerifiedAt: new Date().toISOString(),
    meVerifiedById: user.staffId,
    donorCountStatus: "included_verified",
  });
  emitAudit({
    action: "partnerActivity.meVerified",
    subjectKind: "PartnerActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  // Tell the partner + the accountant — payment gate just opened.
  emitNotificationFanOut([a.partnerId, "ACCOUNTANT"], {
    template: "partnerActivity.paymentGateOpen",
    channel: "Inbox",
    title: `Verified: ${a.title}`,
    body: "M&E verification complete. Payment can now be released.",
    href: `/dashboards/accountant`,
  });
  revalidatePartnerSurfaces(activityId);
  return { ok: true, id: activityId };
}

// ─── 6. rejectPartnerActivity ──────────────────────────────────────

export async function rejectPartnerActivity(
  activityId: string,
  reason: string,
): Promise<PartnerActionResult> {
  const user = await getCurrentUser();
  if (!CCEO_ROLES.has(user.role) && !ME_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (!reason || reason.trim().length < 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "reason" };
  }
  const a = findPartnerActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (a.status === "Rejected" || a.status === "Cancelled") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  updatePartnerActivity(activityId, {
    status: "Rejected",
    evidenceStatus: "Rejected",
    rejectedReason: reason.trim(),
    donorCountStatus: "excluded_not_eligible",
  });
  emitAudit({
    action: "partnerActivity.rejected",
    subjectKind: "PartnerActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { reason: reason.trim() },
  });
  emitNotificationFanOut([a.partnerId], {
    template: "partnerActivity.rejected",
    channel: "Inbox",
    title: `Rejected: ${a.title}`,
    body: reason.trim(),
    href: `/partner/today`,
  });
  revalidatePartnerSurfaces(activityId);
  return { ok: true, id: activityId };
}

// ─── 7. createPartnerDisbursement ──────────────────────────────────
//
// INTEGRITY RULE #6: only MeVerified activities can be paid. Server-
// side gate before any record is written. Idempotent on activityId so
// a double-tap can never produce two payments.

export async function createPartnerDisbursement(input: {
  activityId: string;
  amountUgxCents: number;
  reference: string;
}): Promise<PartnerActionResult & { paymentRef?: string }> {
  const user = await getCurrentUser();
  if (!ACCT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const a = findPartnerActivity(input.activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };

  // Integrity rule #6 — hard server-side gate.
  if (a.status !== "MeVerified") {
    return {
      ok: false,
      reason: "PAYMENT_GATE_BLOCKED",
      details: `Activity status is "${a.status}". Payment requires "MeVerified" (CCEO confirmation + M&E sign-off).`,
    };
  }
  if (a.paymentDisbursementId) {
    return { ok: false, reason: "DUPLICATE" };
  }
  if (input.amountUgxCents <= 0) {
    return { ok: false, reason: "INVALID_INPUT", field: "amountUgxCents" };
  }
  if (!input.reference || input.reference.trim().length < 4) {
    return { ok: false, reason: "INVALID_INPUT", field: "reference" };
  }
  // Idempotency: one disbursement per (activity, ref).
  if (!claimIdempotencyKey(`partnerPayment:${input.activityId}:${input.reference}`)) {
    return { ok: false, reason: "DUPLICATE" };
  }

  const paymentId = newId("ppay");
  updatePartnerActivity(input.activityId, {
    paymentDisbursementId: paymentId,
  });

  emitAudit({
    action: "partnerActivity.paid",
    subjectKind: "PartnerActivity",
    subjectId: input.activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { paymentId, amountUgxCents: input.amountUgxCents, reference: input.reference },
  });
  emitNotificationFanOut([a.partnerId], {
    template: "partnerActivity.paid",
    channel: "Inbox",
    title: `Payment released for ${a.title}`,
    body: `${(input.amountUgxCents / 100).toLocaleString()} UGX · ref ${input.reference.trim()}`,
    href: `/partner/payments`,
  });
  revalidatePartnerSurfaces(input.activityId);
  return { ok: true, id: input.activityId, paymentRef: paymentId };
}

function revalidatePartnerSurfaces(activityId?: string) {
  try {
    revalidatePath("/partner/today");
    revalidatePath("/partner/activities");
    revalidatePath("/partner/evidence");
    revalidatePath("/partner/payments");
    revalidatePath("/partner/schools");
    revalidatePath("/partners");
    revalidatePath("/dashboards/partner");
    revalidatePath("/dashboards/accountant");
    revalidatePath("/dashboards/impact");
    revalidatePath("/data-verification");
    revalidatePath("/notifications");
  } catch { /* outside request */ }
}

"use server";

// W6 — Activity execution & verification server actions.
//
// State machine on PlannedActivity:
//   Planned → Completed → SubmittedForVerification → Verified
//                                                  ↘ Returned (back to Planned)
//
// Side effects:
//   • First completion under a week's WeeklyFundRequest flips the WFR
//     from RECEIVED → IN_USE (auto-cron behaviour, called inline here).
//   • Verifying an activity advances the parent Plan's completion %.
//   • Evidence statuses gate donor counts (integrity rule #4): only
//     CceoConfirmed / MeVerified evidence counts. Anything else is
//     pending_evidence / pending_verification in DonorCountStatus.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { storage } from "@/lib/infra";
import { emitAudit, emitNotificationFanOut } from "./audit";
import { isValidId } from "@/lib/intake/id-formats";
import {
  type ActivityKind,
  type DonorCountStatus,
  type DonorEvidenceStatus,
  type DonorParticipantType,
  type SchoolVisitRecord,
  type TrainingParticipantRecord,
  activities as activitiesStore,
  claimIdempotencyKey,
  findActivity,
  findPlan,
  findTrainingParticipant,
  fundRequests as fundRequestsStore,
  newId,
  schoolVisits as schoolVisitsStore,
  trainingParticipants as participantsStore,
  updateActivity,
  updateTrainingParticipant,
  upsertFundRequest,
} from "./store";

// ─── Result types ───────────────────────────────────────────────────

export type ActivityActionResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_FOUND" }
  | { ok: false; reason: "INVALID_STATE"; current: string }
  | { ok: false; reason: "INVALID_INPUT"; field: string }
  | { ok: false; reason: "DUPLICATE" };

// ─── Authorisation gates ───────────────────────────────────────────

const ASSIGNEE_ROLES = new Set(["CCEO", "Admin"]);
const ME_ROLES       = new Set(["ImpactAssessment", "Admin"]);
const ACCOUNTANT_ROLES = new Set(["ProgramAccountant", "Admin"]);

// ─── 1. markActivityCompleted ──────────────────────────────────────

export async function markActivityCompleted(
  activityId: string,
  notes?: string,
): Promise<ActivityActionResult> {
  const user = await getCurrentUser();
  const a = findActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (!ASSIGNEE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (a.assigneeId && a.assigneeId !== user.staffId && user.role !== "Admin") {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (a.status !== "Planned" && a.status !== "Draft") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  updateActivity(activityId, { status: "Completed" });

  // First completion in the week auto-flips the matching WFR from
  // RECEIVED → IN_USE so the staff doesn't have to remember the step.
  flipWeeklyFundRequestToInUseFor(a.planId);

  emitAudit({
    action: "activity.completed",
    subjectKind: "PlannedActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { notes, kind: a.kind, planId: a.planId },
  });
  revalidateActivitySurfaces(a.planId);
  return { ok: true, id: activityId };
}

// ─── 2. submitActivityForVerification ───────────────────────────────

export async function submitActivityForVerification(
  activityId: string,
  salesforceId?: string,
): Promise<ActivityActionResult> {
  const user = await getCurrentUser();
  const a = findActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (!ASSIGNEE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (a.status !== "Completed") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  // Store the exact Salesforce ID the staff entered so the IA verification
  // queue shows the same value they'll paste into Salesforce to confirm.
  updateActivity(activityId, {
    status: "SubmittedForVerification",
    ...(salesforceId?.trim() ? { salesforceId: salesforceId.trim() } : {}),
  });
  emitAudit({
    action: "activity.submittedForVerification",
    subjectKind: "PlannedActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  emitNotificationFanOut(["IMPACT_ASSESSMENT"], {
    template: "activity.pendingVerification",
    channel: "Inbox",
    title: `${a.title} needs verification`,
    body: `${user.name} marked their activity complete and submitted it for M&E verification.`,
    href: `/data-verification`,
  });
  revalidateActivitySurfaces(a.planId);
  return { ok: true, id: activityId };
}

// ─── 3. verifyActivity ──────────────────────────────────────────────
//
// Integrity rule #3: verifying an activity advances Plan.completion%.
// The plan-completion percentage is read on the fly via
// `planCompletionPercent(planId)` — no cache field to keep in sync.

export async function verifyActivity(
  activityId: string,
  salesforceActivityId?: string,
): Promise<ActivityActionResult> {
  const user = await getCurrentUser();
  if (!ME_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const a = findActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (a.status !== "SubmittedForVerification" && a.status !== "Completed") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  updateActivity(activityId, { status: "Verified" });
  emitAudit({
    action: "activity.verified",
    subjectKind: "PlannedActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { salesforceActivityId, planId: a.planId },
  });
  // Tell the activity owner.
  if (a.assigneeId) {
    emitNotificationFanOut([a.assigneeId], {
      template: "activity.verified",
      channel: "Inbox",
      title: `Verified: ${a.title}`,
      body: "M&E confirmed this activity. It now counts toward your plan completion.",
      href: `/plans/${a.planId}`,
    });
  }
  // Phase 8 hand-off: IA confirmation done → the accountant now owns NetSuite
  // accountability closure. They see this in the accountant console with the
  // staff-entered Salesforce ID as verified proof.
  emitNotificationFanOut(["ProgramAccountant"], {
    template: "activity.awaitingAccountability",
    channel: "Inbox",
    title: `Accountability required: ${a.title}`,
    body: `IA confirmed Salesforce ${a.salesforceId ?? ""}. Confirm NetSuite accountability to close.`,
    href: "/dashboards/accountant",
  });
  revalidateActivitySurfaces(a.planId);
  try { revalidatePath("/dashboards/accountant"); } catch { /* outside request */ }
  return { ok: true, id: activityId };
}

// ─── 3b. confirmActivityAccountability (accountant closes after IA) ──
//
// After IA confirmation, the accountant enters the NetSuite Expense ID (digits)
// to close staff accountability. Cannot act before IA confirmation (status must
// be Verified). This is the finance end of the chain — staff progress ended at
// IA; accountability closes here.

export async function confirmActivityAccountability(
  activityId: string,
  netsuiteExpenseId: string,
): Promise<ActivityActionResult> {
  const user = await getCurrentUser();
  if (!ACCOUNTANT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const a = findActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (a.status !== "Verified") return { ok: false, reason: "INVALID_STATE", current: a.status };
  if (!isValidId("expense", netsuiteExpenseId)) {
    return { ok: false, reason: "INVALID_INPUT", field: "netsuiteExpenseId" };
  }
  updateActivity(activityId, { status: "AccountabilityClosed", netsuiteExpenseId: netsuiteExpenseId.trim() });
  emitAudit({
    action: "activity.accountabilityClosed",
    subjectKind: "PlannedActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { netsuiteExpenseId: netsuiteExpenseId.trim(), salesforceId: a.salesforceId, planId: a.planId },
  });
  if (a.assigneeId) {
    emitNotificationFanOut([a.assigneeId], {
      template: "activity.accountabilityClosed",
      channel: "Inbox",
      title: `Accountability closed: ${a.title}`,
      body: `NetSuite ${netsuiteExpenseId.trim()} recorded. This activity is fully closed.`,
      href: `/plans/${a.planId}`,
    });
  }
  revalidateActivitySurfaces(a.planId);
  try { revalidatePath("/dashboards/accountant"); } catch { /* outside request */ }
  return { ok: true, id: activityId };
}

// ─── 4. returnActivity (Verifier sends back) ───────────────────────

export async function returnActivity(
  activityId: string,
  reason: string,
): Promise<ActivityActionResult> {
  const user = await getCurrentUser();
  if (!ME_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!reason || reason.trim().length < 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "reason" };
  }
  const a = findActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (a.status !== "SubmittedForVerification" && a.status !== "Completed") {
    return { ok: false, reason: "INVALID_STATE", current: a.status };
  }
  updateActivity(activityId, { status: "Returned" });
  emitAudit({
    action: "activity.returned",
    subjectKind: "PlannedActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { reason: reason.trim(), planId: a.planId },
  });
  if (a.assigneeId) {
    emitNotificationFanOut([a.assigneeId], {
      template: "activity.returned",
      channel: "Inbox",
      title: `Returned for correction: ${a.title}`,
      body: reason.trim(),
      href: `/plans/${a.planId}`,
    });
  }
  revalidateActivitySurfaces(a.planId);
  return { ok: true, id: activityId };
}

// ─── 5. addTrainingParticipants (bulk attendance capture) ──────────
//
// Identity is deduped by `identityKey`: a stable hash of preferred
// identity fields (externalId → name+school+phone → name+email). The
// engine writes the same identityKey for two rows referring to the
// same human, so donor "Teachers Trained = COUNT DISTINCT identityKey
// WHERE evidenceStatus IN (...)" works correctly.

export type DraftParticipant = {
  participantType: DonorParticipantType;
  participantName: string;
  schoolId?:       string;
  schoolRole?:     string;
  phone?:          string;
  email?:          string;
  externalId?:     string;
};

export async function addTrainingParticipants(
  activityId: string,
  drafts: DraftParticipant[],
): Promise<ActivityActionResult & { addedIds?: string[] }> {
  const user = await getCurrentUser();
  if (!ASSIGNEE_ROLES.has(user.role) && !ME_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  const a = findActivity(activityId);
  if (!a) return { ok: false, reason: "NOT_FOUND" };
  if (drafts.length === 0) return { ok: false, reason: "INVALID_INPUT", field: "drafts" };

  const now = new Date().toISOString();
  const added: string[] = [];
  for (const d of drafts) {
    if (!d.participantName || d.participantName.trim().length < 2) continue;
    const identityKey = computeIdentityKey(d);
    const row: TrainingParticipantRecord = {
      id: newId("tp"),
      activityId,
      participantType: d.participantType,
      participantName: d.participantName.trim(),
      schoolId: d.schoolId,
      schoolRole: d.schoolRole,
      phone: d.phone,
      email: d.email,
      externalId: d.externalId,
      identityKey,
      evidenceStatus: "Captured",
      donorCountStatus: "pending_evidence",
      createdAt: now,
      updatedAt: now,
    };
    participantsStore().push(row);
    added.push(row.id);
  }

  emitAudit({
    action: "activity.participantsAdded",
    subjectKind: "PlannedActivity",
    subjectId: activityId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { count: added.length },
  });
  revalidateActivitySurfaces(a.planId);
  return { ok: true, id: activityId, addedIds: added };
}

// ─── 6. uploadEvidence — generic single-shot ───────────────────────
//
// Mock-mode: we record the *intent* to store a file plus a stub URI
// (`s3://edify-evidence/<path>`). Production swap point: a multipart
// POST handler streams to S3, returns the bucket URL, and the action
// records that URL here instead of the stub.

export async function uploadEvidence(args: {
  kind: "TrainingParticipant" | "PartnerActivity" | "SsaSnapshot";
  subjectId: string;
  filename: string;
  contentLength: number;
  notes?: string;
}): Promise<ActivityActionResult & { uri?: string }> {
  const user = await getCurrentUser();
  if (args.contentLength <= 0 || args.contentLength > 25 * 1024 * 1024) {
    return { ok: false, reason: "INVALID_INPUT", field: "contentLength" };
  }
  if (!args.filename || args.filename.length < 1) {
    return { ok: false, reason: "INVALID_INPUT", field: "filename" };
  }
  const plan = await storage.planUpload({
    kind: args.kind.toLowerCase(),
    subjectId: args.subjectId,
    filename: args.filename,
    contentLength: args.contentLength,
  });
  const uri = plan.uri;

  switch (args.kind) {
    case "TrainingParticipant": {
      const p = findTrainingParticipant(args.subjectId);
      if (!p) return { ok: false, reason: "NOT_FOUND" };
      updateTrainingParticipant(args.subjectId, {
        evidenceStatus: "Uploaded",
        evidenceUri: uri,
        evidenceNotes: args.notes,
        donorCountStatus: "pending_verification",
      });
      break;
    }
    case "PartnerActivity":
    case "SsaSnapshot": {
      // Delegated to their own actions to keep ownership rules + audit
      // routing clean. We refuse the generic path so we never double-write.
      return { ok: false, reason: "FORBIDDEN" };
    }
  }
  emitAudit({
    action: "evidence.uploaded",
    subjectKind: args.kind,
    subjectId: args.subjectId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { uri, filename: args.filename, bytes: args.contentLength },
  });
  return { ok: true, id: args.subjectId, uri };
}

// ─── 7. confirmEvidence (CCEO confirms participant evidence) ───────
//
// Moves DonorEvidenceStatus from Uploaded → CceoConfirmed. The
// participant now counts as `included_confirmed` for donor metrics
// pending M&E sign-off.

export async function confirmEvidence(
  participantId: string,
): Promise<ActivityActionResult> {
  const user = await getCurrentUser();
  if (!ASSIGNEE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const p = findTrainingParticipant(participantId);
  if (!p) return { ok: false, reason: "NOT_FOUND" };
  if (p.evidenceStatus !== "Uploaded" && p.evidenceStatus !== "Captured") {
    return { ok: false, reason: "INVALID_STATE", current: p.evidenceStatus };
  }
  updateTrainingParticipant(participantId, {
    evidenceStatus: "CceoConfirmed",
    cceoConfirmedAt: new Date().toISOString(),
    cceoConfirmedById: user.staffId,
    donorCountStatus: "included_confirmed",
  });
  emitAudit({
    action: "evidence.cceoConfirmed",
    subjectKind: "TrainingParticipant",
    subjectId: participantId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  revalidatePath("/data-verification");
  return { ok: true, id: participantId };
}

// ─── 8. verifyEvidenceByME (M&E independent verification) ──────────
//
// Final donor gate: only `included_verified` evidence counts in the
// highest-tier donor reports. Integrity rule #4.

export async function verifyEvidenceByME(
  participantId: string,
): Promise<ActivityActionResult> {
  const user = await getCurrentUser();
  if (!ME_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const p = findTrainingParticipant(participantId);
  if (!p) return { ok: false, reason: "NOT_FOUND" };
  if (p.evidenceStatus !== "CceoConfirmed") {
    return { ok: false, reason: "INVALID_STATE", current: p.evidenceStatus };
  }
  updateTrainingParticipant(participantId, {
    evidenceStatus: "MeVerified",
    meVerifiedAt: new Date().toISOString(),
    meVerifiedById: user.staffId,
    donorCountStatus: "included_verified",
  });
  emitAudit({
    action: "evidence.meVerified",
    subjectKind: "TrainingParticipant",
    subjectId: participantId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
  });
  revalidatePath("/data-verification");
  return { ok: true, id: participantId };
}

// ─── 9. rejectEvidence ─────────────────────────────────────────────

export async function rejectEvidence(
  participantId: string,
  reason: string,
): Promise<ActivityActionResult> {
  const user = await getCurrentUser();
  if (!ME_ROLES.has(user.role) && !ASSIGNEE_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (!reason || reason.trim().length < 5) {
    return { ok: false, reason: "INVALID_INPUT", field: "reason" };
  }
  const p = findTrainingParticipant(participantId);
  if (!p) return { ok: false, reason: "NOT_FOUND" };
  updateTrainingParticipant(participantId, {
    evidenceStatus: "Rejected",
    rejectedReason: reason.trim(),
    donorCountStatus: "excluded_not_eligible",
  });
  emitAudit({
    action: "evidence.rejected",
    subjectKind: "TrainingParticipant",
    subjectId: participantId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { reason: reason.trim() },
  });
  revalidatePath("/data-verification");
  return { ok: true, id: participantId };
}

// ─── 10. recordVisit (creates a SchoolVisit row) ───────────────────

export async function recordVisit(input: {
  schoolId: string;
  kind: ActivityKind;
  date: string;
  completed?: boolean;
}): Promise<ActivityActionResult> {
  const user = await getCurrentUser();
  if (!ASSIGNEE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!input.schoolId) return { ok: false, reason: "INVALID_INPUT", field: "schoolId" };
  if (!input.date) return { ok: false, reason: "INVALID_INPUT", field: "date" };
  // Idempotency: one visit per (user, school, date, kind) — protects
  // against accidental double-tap from offline-sync queues.
  if (!claimIdempotencyKey(`visit:${user.staffId}:${input.schoolId}:${input.date}:${input.kind}`)) {
    return { ok: false, reason: "DUPLICATE" };
  }
  const row: SchoolVisitRecord = {
    id: newId("vis"),
    userId: user.staffId,
    schoolId: input.schoolId,
    kind: input.kind,
    date: input.date,
    completed: input.completed ?? true,
    createdAt: new Date().toISOString(),
  };
  schoolVisitsStore().push(row);
  emitAudit({
    action: "visit.recorded",
    subjectKind: "SchoolVisit",
    subjectId: row.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { schoolId: input.schoolId, kind: input.kind, date: input.date },
  });
  revalidatePath("/visits");
  revalidatePath("/today");
  return { ok: true, id: row.id };
}

// ─── Helpers ────────────────────────────────────────────────────────

/** Identity-dedup hash. Production: SHA-256 of a canonical payload.
 * Mock: a deterministic string that's good enough for dedup-by-equal. */
function computeIdentityKey(d: DraftParticipant): string {
  if (d.externalId) return `ext:${d.externalId.trim().toLowerCase()}`;
  const phone = d.phone?.replace(/\s+/g, "") ?? "";
  const email = d.email?.trim().toLowerCase() ?? "";
  const name = d.participantName.trim().toLowerCase();
  const school = d.schoolId ?? "no_school";
  return `nat:${name}|${school}|${phone || email || "no_contact"}`;
}

/** Find the weekly fund request that owns this plan/staff/week and
 * flip RECEIVED → IN_USE on first activity completion. No-op if the
 * WFR is already past RECEIVED. */
function flipWeeklyFundRequestToInUseFor(planId: string): void {
  for (const r of fundRequestsStore()) {
    if (r.monthlyPlanId !== planId) continue;
    if (r.status !== "RECEIVED") continue;
    upsertFundRequest({ ...r, status: "IN_USE" });
  }
}

function revalidateActivitySurfaces(planId?: string) {
  try {
    revalidatePath("/today");
    revalidatePath("/visits");
    revalidatePath("/trainings");
    revalidatePath("/calendar");
    revalidatePath("/data-verification");
    revalidatePath("/quality-checks");
    if (planId) revalidatePath(`/plans/${planId}`);
    revalidatePath("/dashboards/cceo");
    revalidatePath("/dashboards/impact");
    revalidatePath("/notifications");
  } catch { /* outside request */ }
}

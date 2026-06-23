"use server";

// Core School lifecycle actions — the one connected chain. Every action keys on
// the directory schoolId, mutates the unified core store, emits audit +
// notification, revalidates, and returns a discriminated union. Canonical
// Bucket-C shape.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { ssaAverage, deriveFyFromDate, SSA_AREA_TO_BACKEND, SSA_INTERVENTION_AREAS, type SsaInterventionArea } from "@/lib/intake/intake-core";
import { isBackendEnabled } from "@/lib/api/backend";
import {
  backendAdvanceChampion, backendCoreSlotAction, backendOnboardCoreSchool,
  backendRejectCoreCandidate, backendScheduleCoreFollowUp, backendUploadCoreFollowUpSsa,
  backendVerifyCoreCandidate,
} from "@/lib/api/surfaces";
import { emitAudit, emitNotification, emitNotificationFanOut } from "./audit";
import {
  candidateSnapshotFor,
  verificationFor,
  onboardingFor,
  profileFor,
  planById,
  planForSchool,
  slotById,
  slotsForPlan,
  addVerification,
  addOnboarding,
  addProfile,
  addPlan,
  addIntervention,
  addSlot,
  addSsaSnapshot,
  addFollowUp,
  updatePlan,
  updateSlot,
  updateProfile,
  effectiveSchoolType,
} from "@/lib/core/core-store";
import { corePlanProgress, recomputePlanCounters } from "@/lib/core/core-progress";
import { coreImpactFor } from "@/lib/core/core-impact";
import { recordCompletion } from "@/lib/execution/completion-overlay";
import { syncSlotToActivities } from "@/lib/core/sync-to-activities";
import { intakeSchools } from "@/lib/intake/intake-mock";

// Look up the slot's school name from the intake directory so the
// mirrored canonical activity displays the school by name in My Plan,
// PL Team Plan, and Targets — not just an opaque id.
function schoolNameFor(schoolId: string): string | undefined {
  return intakeSchools.find((s) => s.schoolId === schoolId)?.schoolName;
}

// Re-read the slot after an updateSlot patch so the mirrored activity
// reflects the new status. Safe no-op when the slot is missing.
function mirrorAfterSlotChange(slotId: string, staffId: string): void {
  const fresh = slotById(slotId);
  if (!fresh) return;
  syncSlotToActivities(fresh, { actingStaffId: staffId, schoolName: schoolNameFor(fresh.schoolId) });
}
import {
  CORE_SSA_THRESHOLD, VISITS_TARGET, TRAININGS_TARGET,
  type CoreSlotOwner, type CoreActivitySlot, type CoreSsaScores,
} from "@/lib/core/core-types";

const VERIFY_ROLES = new Set(["ImpactAssessment", "CCEO", "CountryProgramLead", "CountryDirector", "Admin"]);
const ONBOARD_ROLES = new Set(["CountryDirector", "CountryProgramLead", "ImpactAssessment", "Admin"]);
// Core-slot scheduling/assignment is a PLANNING write — planning roles only.
// (CD onboards + flags, IA verifies; neither schedules — mirrors ACTIVITY_ASSIGN.)
const ASSIGN_ROLES = new Set(["CCEO", "CountryProgramLead", "Admin"]);
const IA_ROLES = new Set(["ImpactAssessment", "Admin"]);
const EXEC_ROLES = new Set(["CCEO", "CountryProgramLead", "PartnerAdmin", "PartnerFieldOfficer", "Admin"]);
const PL_ROLES = new Set(["CountryProgramLead", "Admin"]);
const ACCOUNTANT_ROLES = new Set(["ProgramAccountant", "Admin"]);
const REVIEW_ROLES = new Set(["CCEO", "CountryProgramLead", "CountryDirector", "ProjectCoordinator", "Admin"]);

const id = (p: string) => `${p}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;

function rev(...paths: string[]) {
  try { for (const p of paths) revalidatePath(p); } catch { /* outside request */ }
}
const CORE_SURFACES = ["/ssa/core-candidates", "/core-onboarding", "/planning/core-schools", "/planning", "/core-schools", "/notifications"];

function beUser(user: { email: string; role: string }) {
  return { email: user.email, role: user.role };
}

// ─── 1. Verify candidate → Verified Potential Core ──────────────────

export type CoreVerifyResult =
  | { ok: true; schoolId: string }
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "INVALID_INPUT" | "DUPLICATE" };

export async function verifyCoreCandidate(schoolId: string, verificationId: string, comments?: string): Promise<CoreVerifyResult> {
  const user = await getCurrentUser();
  if (!VERIFY_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendVerifyCoreCandidate(beUser(user), schoolId, { verificationId, comments });
    if (!r.live) return { ok: false, reason: "INVALID_INPUT" };
    rev(...CORE_SURFACES);
    return { ok: true, schoolId };
  }
  const snap = candidateSnapshotFor(schoolId);
  if (!snap) return { ok: false, reason: "NOT_FOUND" };
  const vid = verificationId?.trim() ?? "";
  if (vid.length < 3) return { ok: false, reason: "INVALID_INPUT" };
  if (verificationFor(schoolId)) return { ok: false, reason: "DUPLICATE" };

  addVerification({
    id: id("cver"), schoolId, ssaRecordId: snap.id, verificationId: vid,
    verifiedById: user.staffId, verifiedByName: user.name, verifiedAt: new Date().toISOString(),
    status: snap.average >= CORE_SSA_THRESHOLD ? "Verified Potential Core" : "Rejected", comments,
  });

  emitAudit({ action: "core.candidateVerified", subjectKind: "CoreCandidate", subjectId: schoolId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { verificationId: vid, average: snap.average } });
  emitNotificationFanOut(["PROGRAM_LEAD", "COUNTRY_DIRECTOR", "IMPACT_ASSESSMENT"], {
    template: "core.candidateVerified", channel: "Inbox",
    title: "Verified Potential Core — ready to onboard",
    body: `Verification ID ${vid} recorded. The school is in the Core Onboarding Queue.`,
    href: "/core-onboarding",
  });
  rev(...CORE_SURFACES);
  return { ok: true, schoolId };
}

// ─── 2. Onboard → create profile + plan + interventions + 8 slots ───

export type CoreOnboardResult =
  | { ok: true; schoolId: string; planId: string }
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "NOT_VERIFIED" | "ALREADY_CORE" };

export async function onboardCoreSchool(schoolId: string, reason?: string): Promise<CoreOnboardResult> {
  const user = await getCurrentUser();
  if (!ONBOARD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendOnboardCoreSchool(beUser(user), schoolId, { reason });
    if (!r.live) return { ok: false, reason: "NOT_VERIFIED" };
    rev(...CORE_SURFACES);
    return { ok: true, schoolId, planId: r.data!.planId };
  }
  if (effectiveSchoolType(schoolId) === "Core" || onboardingFor(schoolId)?.status === "Onboarded") return { ok: false, reason: "ALREADY_CORE" };
  const v = verificationFor(schoolId);
  if (!v || v.status !== "Verified Potential Core") return { ok: false, reason: "NOT_VERIFIED" };
  const snap = candidateSnapshotFor(schoolId);
  const school = intakeSchools.find((x) => x.schoolId === schoolId);
  if (!snap || !school) return { ok: false, reason: "NOT_FOUND" };

  const now = new Date().toISOString();
  const fy = snap.fy;

  // Baseline snapshot = the verified candidate SSA, snapshotted as baseline.
  const baselineId = `cssa-${schoolId}-base-${Date.now().toString(36)}`;
  addSsaSnapshot({ id: baselineId, schoolId, kind: "baseline", fy, date: snap.date, scores: snap.scores, average: snap.average, verificationId: v.verificationId });

  addOnboarding({
    id: id("con"), schoolId, fy, previousSchoolType: school.schoolType, newSchoolType: "Core",
    baselineSSARecordId: baselineId, baselineAverageScore: snap.average,
    onboardedById: user.staffId, onboardedByName: user.name, onboardedAt: now,
    onboardingReason: reason?.trim() || "Verified Potential Core — onboarded.", status: "Onboarded",
  });

  const planId = `cplan-${schoolId}`;
  addPlan({
    id: planId, schoolId, fy, baselineSSARecordId: baselineId, status: "Active",
    visitsTarget: VISITS_TARGET, trainingsTarget: TRAININGS_TARGET,
    visitsCompleted: 0, trainingsCompleted: 0, packageCompletionPercent: 0,
    createdById: user.staffId, createdByName: user.name, createdAt: now, updatedAt: now,
  });
  addProfile({ id: `cprof-${schoolId}`, schoolId, activeCorePlanId: planId, coreStartFy: fy, championStatus: "Not Eligible", status: "Active" });

  // 4 priority interventions = the 4 weakest baseline areas.
  const ranked = (Object.keys(snap.scores) as SsaInterventionArea[])
    .map((a) => ({ area: a, score: snap.scores[a] ?? 0 }))
    .sort((a, b) => a.score - b.score)
    .slice(0, 4);
  ranked.forEach((r, i) => addIntervention({
    id: `cint-${schoolId}-${i + 1}`, corePlanId: planId, intervention: r.area, baselineScore: r.score,
    priorityRank: (i + 1) as 1 | 2 | 3 | 4, reason: "Weakest baseline area.", selectedById: user.staffId, selectedAt: now,
  }));

  // 8 slots (4 visits + 4 trainings).
  (["visit", "training"] as const).forEach((type) => {
    for (let nn = 1; nn <= 4; nn++) {
      addSlot({
        id: `cslot-${schoolId}-${type[0]}${nn}`, corePlanId: planId, schoolId,
        intervention: ranked[(nn - 1) % ranked.length].area, activityType: type, sequenceNumber: nn as 1 | 2 | 3 | 4,
        status: "Not Planned", owner: "unassigned", createdAt: now, updatedAt: now,
      });
    }
  });

  emitAudit({ action: "core.schoolOnboarded", subjectKind: "CoreSchool", subjectId: schoolId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { planId, baselineAverage: snap.average, fy } });
  emitNotificationFanOut(["CCEO", "PROGRAM_LEAD"], {
    template: "core.schoolOnboarded", channel: "Inbox",
    title: `${school.schoolName} onboarded as Core`,
    body: `Core plan created — 4 priority interventions, 4 visits + 4 trainings. Start planning the package.`,
    href: "/planning/core-schools",
  });
  rev(...CORE_SURFACES);
  return { ok: true, schoolId, planId };
}

export async function rejectCoreCandidate(schoolId: string, reason: string): Promise<CoreVerifyResult> {
  const user = await getCurrentUser();
  if (!ONBOARD_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendRejectCoreCandidate(beUser(user), schoolId, { reason });
    if (!r.live) return { ok: false, reason: "INVALID_INPUT" };
    rev(...CORE_SURFACES);
    return { ok: true, schoolId };
  }
  if (!candidateSnapshotFor(schoolId)) return { ok: false, reason: "NOT_FOUND" };
  if ((reason?.trim() ?? "").length < 5) return { ok: false, reason: "INVALID_INPUT" };
  if (verificationFor(schoolId)) return { ok: false, reason: "DUPLICATE" };
  addVerification({ id: id("cver"), schoolId, ssaRecordId: candidateSnapshotFor(schoolId)!.id, verificationId: "—", verifiedById: user.staffId, verifiedByName: user.name, verifiedAt: new Date().toISOString(), status: "Rejected", comments: reason.trim() });
  emitAudit({ action: "core.candidateRejected", subjectKind: "CoreCandidate", subjectId: schoolId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { reason: reason.trim() } });
  rev(...CORE_SURFACES);
  return { ok: true, schoolId };
}

// ─── 3. Slot assignment + scheduling ────────────────────────────────

export type CoreSlotResult =
  | { ok: true; slotId: string }
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "INVALID_INPUT" | "INVALID_STATE" };

function notifyPlanRefresh(planId: string) {
  const slots = slotsForPlan(planId);
  const counters = recomputePlanCounters(slots);
  updatePlan(planId, counters);
}

export async function assignCoreSlot(
  slotId: string,
  input: { owner: CoreSlotOwner; ownerName?: string; partnerId?: string; monthLabel?: string; week?: number },
): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!ASSIGN_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendCoreSlotAction(beUser(user), slotId, "assign", input as Record<string, unknown>);
    if (!r.live) return { ok: false, reason: "NOT_FOUND" };
    rev(...CORE_SURFACES);
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };

  const isPartner = input.owner === "partner" || input.owner === "partner_facilitator";
  // Real partner identity: use the chosen partner's id, falling back to a slug
  // of the name (never the literal "PARTNER" placeholder).
  const partnerId = isPartner
    ? (input.partnerId || `pt-${(input.ownerName ?? "partner").toLowerCase().replace(/[^a-z0-9]+/g, "-")}`)
    : undefined;
  updateSlot(slotId, {
    owner: input.owner,
    assignedStaffId: !isPartner ? user.staffId : undefined,
    assignedStaffName: input.owner === "myself" ? user.name : input.owner === "staff" ? input.ownerName : undefined,
    assignedPartnerName: isPartner ? input.ownerName : undefined,
    assignedPartnerId: partnerId,
    status: isPartner ? "Assigned to Partner" : input.monthLabel ? "Scheduled" : "Planned",
    scheduledMonth: input.monthLabel,
    scheduledWeek: input.week,
    scheduledFor: input.monthLabel ? `${input.monthLabel}${input.week ? ` · Wk ${input.week}` : ""}` : undefined,
  });

  emitAudit({ action: "core.slotAssigned", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { owner: input.owner, ownerName: input.ownerName, planId: slot.corePlanId } });
  if (isPartner) emitNotification({ userId: "PARTNER", template: "core.slotAssigned", channel: "Inbox", title: `Core ${slot.activityType} assigned`, body: `${user.name} assigned a core ${slot.activityType} (${slot.intervention}) to ${input.ownerName ?? "your team"}.`, href: "/partner/assignments" });
  // Mirror into the canonical activities() ledger so the assignee
  // sees the Core slot on their My Plan / Today, and PL Team Plan
  // counts include Core work.
  mirrorAfterSlotChange(slotId, user.staffId);
  rev(...CORE_SURFACES);
  return { ok: true, slotId };
}

export async function scheduleCoreSlot(slotId: string, monthLabel: string, week: number): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!ASSIGN_ROLES.has(user.role) && !EXEC_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendCoreSlotAction(beUser(user), slotId, "schedule", { monthLabel, week });
    if (!r.live) return { ok: false, reason: "NOT_FOUND" };
    rev(...CORE_SURFACES);
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };
  updateSlot(slotId, { status: "Scheduled", scheduledMonth: monthLabel, scheduledWeek: week, scheduledFor: `${monthLabel} · Wk ${week}` });
  emitAudit({ action: "core.slotScheduled", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { monthLabel, week } });
  mirrorAfterSlotChange(slotId, user.staffId);
  rev(...CORE_SURFACES);
  return { ok: true, slotId };
}

export async function startCoreSlot(slotId: string): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!EXEC_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendCoreSlotAction(beUser(user), slotId, "start", {});
    if (!r.live) return { ok: false, reason: "NOT_FOUND" };
    rev(...CORE_SURFACES);
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };
  updateSlot(slotId, { status: "In Progress" });
  emitAudit({ action: "core.slotStarted", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name });
  mirrorAfterSlotChange(slotId, user.staffId);
  rev(...CORE_SURFACES);
  return { ok: true, slotId };
}

export async function uploadCoreEvidence(slotId: string, evidenceUri: string, notes?: string): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!EXEC_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    if (!evidenceUri?.trim()) return { ok: false, reason: "INVALID_INPUT" };
    const r = await backendCoreSlotAction(beUser(user), slotId, "evidence", { evidenceUri, notes });
    if (!r.live) return { ok: false, reason: "NOT_FOUND" };
    rev(...CORE_SURFACES);
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };
  if (!evidenceUri?.trim()) return { ok: false, reason: "INVALID_INPUT" };
  updateSlot(slotId, { status: "Evidence Uploaded", evidenceUri: evidenceUri.trim(), evidenceNotes: notes?.trim() || undefined });
  mirrorAfterSlotChange(slotId, user.staffId);
  emitAudit({ action: "core.evidenceUploaded", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name });
  emitNotification({ userId: "CCEO", template: "core.evidenceUploaded", channel: "Inbox", title: "Core evidence to review", body: `Evidence uploaded for a core ${slot.activityType}. Review it, then enter the Salesforce ID.`, href: "/planning/core-schools" });
  rev(...CORE_SURFACES);
  return { ok: true, slotId };
}

// CCEO/PL accepts partner-delivered evidence before the Salesforce ID is entered
// (§12 partner path: partner uploads → staff/CCEO accepts → SF ID → IA → pay).
export async function acceptCoreEvidence(slotId: string): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!REVIEW_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendCoreSlotAction(beUser(user), slotId, "acceptEvidence", {});
    if (!r.live) return { ok: false, reason: "INVALID_STATE" };
    rev(...CORE_SURFACES);
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };
  if (slot.status !== "Evidence Uploaded") return { ok: false, reason: "INVALID_STATE" };
  updateSlot(slotId, { status: "Evidence Accepted" });
  emitAudit({ action: "core.evidenceAccepted", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { planId: slot.corePlanId } });
  emitNotification({ userId: "CCEO", template: "core.evidenceAccepted", channel: "Inbox", title: "Evidence accepted — enter Salesforce ID", body: `Partner evidence accepted for a core ${slot.activityType}. Enter the ${slot.activityType === "visit" ? "SVE-" : "TS-"} Salesforce ID.`, href: "/planning/core-schools" });
  rev(...CORE_SURFACES);
  return { ok: true, slotId };
}

// Reviewer returns partner evidence for rework (back to In Progress).
export async function returnCoreEvidence(slotId: string, reason: string): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!REVIEW_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    if ((reason?.trim() ?? "").length < 5) return { ok: false, reason: "INVALID_INPUT" };
    const r = await backendCoreSlotAction(beUser(user), slotId, "returnEvidence", { reason });
    if (!r.live) return { ok: false, reason: "INVALID_STATE" };
    rev(...CORE_SURFACES);
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };
  if (slot.status !== "Evidence Uploaded") return { ok: false, reason: "INVALID_STATE" };
  if ((reason?.trim() ?? "").length < 5) return { ok: false, reason: "INVALID_INPUT" };
  updateSlot(slotId, { status: "In Progress", evidenceNotes: `Returned: ${reason.trim()}` });
  emitAudit({ action: "core.evidenceReturned", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { reason: reason.trim() } });
  emitNotification({ userId: "PARTNER", template: "core.evidenceReturned", channel: "Inbox", title: "Core evidence returned", body: `Re-upload evidence: ${reason.trim()}`, href: "/partner/assignments" });
  rev(...CORE_SURFACES);
  return { ok: true, slotId };
}

// ─── 4. Completion (enter Salesforce ID) → Awaiting IA Verification ─

export type CoreCompleteInput = {
  salesforceId: string;
  teachers?: number;
  leaders?: number;
  participants?: number;
};

export async function completeCoreSlot(slotId: string, input: CoreCompleteInput): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!EXEC_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendCoreSlotAction(beUser(user), slotId, "complete", input as Record<string, unknown>);
    if (!r.live) return { ok: false, reason: "INVALID_INPUT" };
    rev(...CORE_SURFACES, "/data-verification");
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };

  const sf = input.salesforceId?.trim() ?? "";
  const wantPrefix = slot.activityType === "visit" ? "SVE" : "TS";
  if (sf.length < 4 || !sf.toUpperCase().startsWith(wantPrefix)) return { ok: false, reason: "INVALID_INPUT" };
  if (slot.activityType === "training" && (!input.teachers || !input.leaders)) return { ok: false, reason: "INVALID_INPUT" };
  // Partner-delivered work must have its evidence accepted before the staff
  // enters the Salesforce ID (§12 partner path).
  if (slot.assignedPartnerId && slot.status !== "Evidence Accepted") return { ok: false, reason: "INVALID_STATE" };

  // A completed slot is a real activity ledger record — keep the FK so the
  // "completed slot without Activity record" invariant holds (§22).
  const activityId = slot.activityId ?? `cact-${slotId}-${Date.now().toString(36)}`;
  // CCEO field visits need PL sign-off before IA verification (§12).
  const needsPl = user.role === "CCEO" && slot.activityType === "visit";

  updateSlot(slotId, {
    status: "Awaiting IA Verification",
    salesforceId: sf,
    activityId,
    plVerificationStatus: needsPl ? "Pending" : undefined,
    teachers: input.teachers,
    leaders: input.leaders,
    participants: input.participants ?? ((input.teachers ?? 0) + (input.leaders ?? 0)),
  });
  // Two-way activity-ledger integration: a completed core slot becomes a real
  // record in the shared completion overlay (the same ledger /visits + /trainings
  // and IA read), keyed by the entered Salesforce ID. No longer one-way (§9/§22).
  const coreSchool = intakeSchools.find((s) => s.schoolId === slot.schoolId);
  recordCompletion({
    activityId,
    activityType: slot.activityType === "visit" ? "Core Visit" : "Core Training",
    schoolName: coreSchool?.schoolName ?? slot.schoolId,
    salesforceId: sf,
    salesforceIdKind: slot.activityType === "visit" ? "SVE" : "TS",
    teachers: input.teachers,
    leaders: input.leaders,
    confirmedById: user.staffId,
    confirmedByName: user.name,
  });

  mirrorAfterSlotChange(slotId, user.staffId);
  emitAudit({ action: "core.slotCompleted", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { salesforceId: sf, activityId, planId: slot.corePlanId } });
  if (needsPl) {
    emitNotification({ userId: "PROGRAM_LEAD", template: "core.slotPlReview", channel: "Inbox", title: "CCEO core visit needs your sign-off", body: `Verify the CCEO core visit (${slot.intervention}) before it goes to IA.`, href: "/planning/core-schools" });
  } else {
    emitNotification({ userId: "IMPACT_ASSESSMENT", template: "core.slotCompleted", channel: "Inbox", title: `Core ${slot.activityType} to verify`, body: `Salesforce ID ${sf} entered — verify the core ${slot.activityType}.`, href: "/data-verification" });
  }
  rev(...CORE_SURFACES, "/data-verification");
  return { ok: true, slotId };
}

// ─── 4b. PL sign-off for CCEO visits (before IA) ────────────────────

export async function plVerifyCoreSlot(slotId: string): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!PL_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendCoreSlotAction(beUser(user), slotId, "plVerify", {});
    if (!r.live) return { ok: false, reason: "INVALID_STATE" };
    rev(...CORE_SURFACES, "/data-verification");
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };
  if (slot.plVerificationStatus !== "Pending") return { ok: false, reason: "INVALID_STATE" };
  updateSlot(slotId, { plVerificationStatus: "Verified" });
  mirrorAfterSlotChange(slotId, user.staffId);
  emitAudit({ action: "core.slotPlVerified", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { planId: slot.corePlanId } });
  emitNotification({ userId: "IMPACT_ASSESSMENT", template: "core.slotCompleted", channel: "Inbox", title: "CCEO core visit ready for IA", body: `PL signed off — verify the core visit (${slot.salesforceId ?? "no SF"}).`, href: "/data-verification" });
  rev(...CORE_SURFACES, "/data-verification");
  return { ok: true, slotId };
}

// ─── 5. IA verification → Completed (advances the 4/4 cycle) ────────

export async function iaVerifyCoreSlot(slotId: string): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!IA_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendCoreSlotAction(beUser(user), slotId, "iaVerify", {});
    if (!r.live) return { ok: false, reason: "INVALID_STATE" };
    rev(...CORE_SURFACES, "/data-verification", "/disbursements");
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };
  if (slot.status !== "Awaiting IA Verification") return { ok: false, reason: "INVALID_STATE" };
  // CCEO visits must clear PL sign-off first (§12).
  if (slot.plVerificationStatus === "Pending") return { ok: false, reason: "INVALID_STATE" };

  updateSlot(slotId, { status: "Completed", iaVerificationStatus: "Verified", completedAt: new Date().toISOString() });
  mirrorAfterSlotChange(slotId, user.staffId);
  notifyPlanRefresh(slot.corePlanId);

  // If the package is complete, flip the plan to Pending Follow-Up SSA.
  const progress = corePlanProgress(slot.corePlanId);
  if (progress.readyForFollowUpSSA) {
    updatePlan(slot.corePlanId, { status: "Completed Pending Follow-Up SSA" });
    emitNotificationFanOut(["IMPACT_ASSESSMENT", "CCEO", "PROGRAM_LEAD"], {
      template: "core.packageComplete", channel: "Inbox",
      title: "Core package complete — schedule Follow-Up SSA",
      body: `4 visits + 4 trainings done. Schedule the follow-up SSA to measure impact.`,
      href: "/planning/core-schools",
    });
  } else {
    updatePlan(slot.corePlanId, { status: "In Progress" });
  }

  emitAudit({ action: "core.slotIaVerified", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { planId: slot.corePlanId } });
  if (slot.assignedPartnerId) emitNotification({ userId: "PROGRAM_ACCOUNTANT", template: "core.partnerPayable", channel: "Inbox", title: "Core partner payment ready", body: `IA-verified core ${slot.activityType} — clear the partner payment.`, href: "/disbursements" });
  rev(...CORE_SURFACES, "/data-verification", "/disbursements");
  return { ok: true, slotId };
}

export async function returnCoreSlot(slotId: string, reason: string): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!IA_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    if ((reason?.trim() ?? "").length < 5) return { ok: false, reason: "INVALID_INPUT" };
    const r = await backendCoreSlotAction(beUser(user), slotId, "return", { reason });
    if (!r.live) return { ok: false, reason: "NOT_FOUND" };
    rev(...CORE_SURFACES, "/data-verification");
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };
  if ((reason?.trim() ?? "").length < 5) return { ok: false, reason: "INVALID_INPUT" };
  updateSlot(slotId, { status: "Returned", returnedReason: reason.trim() });
  mirrorAfterSlotChange(slotId, user.staffId);
  emitAudit({ action: "core.slotReturned", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { reason: reason.trim() } });
  rev(...CORE_SURFACES, "/data-verification");
  return { ok: true, slotId };
}

export async function accountantConfirmCoreSlot(slotId: string, netsuiteExpenseId?: string): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!ACCOUNTANT_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const r = await backendCoreSlotAction(beUser(user), slotId, "accountantConfirm", { netsuiteExpenseId });
    if (!r.live) return { ok: false, reason: "NOT_FOUND" };
    rev(...CORE_SURFACES, "/disbursements", "/dashboards/accountant");
    return { ok: true, slotId };
  }
  const slot = slotById(slotId);
  if (!slot) return { ok: false, reason: "NOT_FOUND" };
  updateSlot(slotId, { accountantStatus: "Confirmed" });
  emitAudit({ action: "core.slotAccountantConfirmed", subjectKind: "CoreActivitySlot", subjectId: slotId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { netsuiteExpenseId } });
  rev(...CORE_SURFACES, "/disbursements", "/dashboards/accountant");
  return { ok: true, slotId };
}

// ─── 6. Follow-up SSA: schedule/assign → IA upload → impact + champion ─

// Staff schedule the Follow-Up SSA (or assign it to a partner) once the package
// is complete. IA still records the actual follow-up scores afterward.
export async function scheduleCoreFollowUpSsa(
  planId: string,
  input: { assignee: "myself" | "partner"; partnerName?: string; monthLabel: string; week?: number },
): Promise<CoreSlotResult> {
  const user = await getCurrentUser();
  if (!ASSIGN_ROLES.has(user.role) && !EXEC_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (isBackendEnabled()) {
    const assigneeLabel = input.assignee === "partner" ? (input.partnerName?.trim() || "Partner team") : user.name;
    const r = await backendScheduleCoreFollowUp(beUser(user), planId, {
      assignee: assigneeLabel,
      monthLabel: input.monthLabel,
      week: input.week,
    });
    if (!r.live) return { ok: false, reason: "INVALID_STATE" };
    rev(...CORE_SURFACES);
    return { ok: true, slotId: planId };
  }
  const plan = planById(planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (plan.status !== "Completed Pending Follow-Up SSA" && plan.status !== "Follow-Up SSA Scheduled") return { ok: false, reason: "INVALID_STATE" };
  if (plan.followUpSSARecordId) return { ok: false, reason: "INVALID_STATE" };
  const assigneeLabel = input.assignee === "partner" ? (input.partnerName?.trim() || "Partner team") : user.name;
  const when = `${input.monthLabel}${input.week ? ` · Wk ${input.week}` : ""}`;
  updatePlan(planId, { status: "Follow-Up SSA Scheduled", followUpScheduledFor: when, followUpAssignee: assigneeLabel });
  emitAudit({ action: "core.followUpScheduled", subjectKind: "CorePlan", subjectId: planId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { assignee: assigneeLabel, when } });
  emitNotificationFanOut(["IMPACT_ASSESSMENT", "CCEO", "PROGRAM_LEAD"], {
    template: "core.followUpScheduled", channel: "Inbox",
    title: "Follow-Up SSA scheduled",
    body: `Follow-Up SSA set for ${when} (${assigneeLabel}). IA records the scores when done.`,
    href: "/planning/core-schools",
  });
  rev(...CORE_SURFACES);
  return { ok: true, slotId: planId };
}

export type CoreFollowUpResult =
  | { ok: true; planId: string; averageChange: number; championCandidate: boolean }
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "NOT_READY" | "INVALID_INPUT" | "DUPLICATE" };

export async function uploadCoreFollowUpSsa(planId: string, scores: CoreSsaScores, dateIso?: string): Promise<CoreFollowUpResult> {
  const user = await getCurrentUser();
  if (!IA_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const avg = ssaAverage(scores);
  if (avg <= 0) return { ok: false, reason: "INVALID_INPUT" };

  if (isBackendEnabled()) {
    const beScores = SSA_INTERVENTION_AREAS
      .map((area) => ({ intervention: SSA_AREA_TO_BACKEND[area], score: Number(scores[area]) }))
      .filter((s) => s.intervention && Number.isFinite(s.score));
    if (beScores.length !== 8) return { ok: false, reason: "INVALID_INPUT" };
    const r = await backendUploadCoreFollowUpSsa(beUser(user), planId, {
      dateOfSsa: new Date(dateIso || new Date().toISOString().slice(0, 10)).toISOString(),
      scores: beScores,
    });
    if (!r.live) return { ok: false, reason: "NOT_READY" };
    rev(...CORE_SURFACES);
    return {
      ok: true,
      planId,
      averageChange: r.data?.averageChange ?? 0,
      championCandidate: !!r.data?.championCandidate,
    };
  }

  const plan = planById(planId);
  if (!plan) return { ok: false, reason: "NOT_FOUND" };
  if (plan.followUpSSARecordId) return { ok: false, reason: "DUPLICATE" };
  const progress = corePlanProgress(planId);
  if (!progress.readyForFollowUpSSA) return { ok: false, reason: "NOT_READY" };

  const date = dateIso || new Date().toISOString().slice(0, 10);

  const followId = `cssa-${plan.schoolId}-follow-${Date.now().toString(36)}`;
  addFollowUp({ id: followId, corePlanId: planId, schoolId: plan.schoolId, baselineSSARecordId: plan.baselineSSARecordId, fy: deriveFyFromDate(date), date, scores, average: avg, uploadedById: user.staffId, uploadedByName: user.name });
  addSsaSnapshot({ id: followId, schoolId: plan.schoolId, kind: "followup", fy: deriveFyFromDate(date), date, scores, average: avg });
  updatePlan(planId, { followUpSSARecordId: followId, status: "Impact Measured" });

  const impact = coreImpactFor(planId);
  if (impact?.championCandidate) {
    updateProfile(plan.schoolId, { championStatus: "Potential Champion" });
    updatePlan(planId, { status: "Champion Candidate" });
  }

  emitAudit({ action: "core.followUpSsaUploaded", subjectKind: "CorePlan", subjectId: planId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { average: avg, averageChange: impact?.averageChange, championCandidate: impact?.championCandidate } });
  emitNotificationFanOut(["CCEO", "PROGRAM_LEAD", "COUNTRY_DIRECTOR"], {
    template: "core.impactMeasured", channel: "Inbox",
    title: `Core impact measured — ${impact && impact.averageChange >= 0 ? "+" : ""}${impact?.averageChange ?? 0} avg SSA`,
    body: `Follow-up SSA recorded. ${impact?.championCandidate ? "School is a Potential Champion." : "Impact computed across the 4 priority interventions."}`,
    href: "/core-schools",
  });
  rev(...CORE_SURFACES);
  return { ok: true, planId, averageChange: impact?.averageChange ?? 0, championCandidate: !!impact?.championCandidate };
}

// ─── 7. Champion pipeline transition ────────────────────────────────

const CHAMPION_FLOW: Record<string, { roles: Set<string>; next: string }> = {
  "Potential Champion": { roles: IA_ROLES, next: "Under Review" },
  "Under Review": { roles: IA_ROLES, next: "IA Verified" },
  "IA Verified": { roles: new Set(["CountryProgramLead", "Admin"]), next: "PL Recommended" },
  "PL Recommended": { roles: new Set(["CountryDirector", "Admin"]), next: "CD Approved" },
  "CD Approved": { roles: new Set(["CountryDirector", "Admin"]), next: "Verified Champion" },
  "Verified Champion": { roles: new Set(["CountryDirector", "Admin"]), next: "Champion Mentor School" },
};

export type ChampionResult = { ok: true; schoolId: string; status: string } | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "INVALID_STATE" };

export async function advanceChampion(schoolId: string): Promise<ChampionResult> {
  const user = await getCurrentUser();
  if (isBackendEnabled()) {
    const r = await backendAdvanceChampion(beUser(user), schoolId);
    if (!r.live) return { ok: false, reason: "INVALID_STATE" };
    rev(...CORE_SURFACES);
    return { ok: true, schoolId, status: r.data!.status };
  }
  const profile = profileFor(schoolId);
  if (!profile) return { ok: false, reason: "NOT_FOUND" };
  const step = CHAMPION_FLOW[profile.championStatus];
  if (!step) return { ok: false, reason: "INVALID_STATE" };
  if (!step.roles.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  updateProfile(schoolId, { championStatus: step.next as CoreSchoolProfileChampion });
  const plan = planForSchool(schoolId);
  if (plan && step.next === "Verified Champion") updatePlan(plan.id, { status: "Champion Verified" });
  emitAudit({ action: "core.championAdvanced", subjectKind: "CoreSchool", subjectId: schoolId, actorId: user.staffId, actorRole: user.role, actorName: user.name, payload: { from: profile.championStatus, to: step.next } });
  rev(...CORE_SURFACES);
  return { ok: true, schoolId, status: step.next };
}

// Local alias so the cast above stays readable.
type CoreSchoolProfileChampion = import("@/lib/core/core-types").ChampionStatus;

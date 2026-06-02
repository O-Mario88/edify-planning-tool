"use server";

// Data-intake server actions — Add School + Upload SSA performance.
//
// Data intake (creating school master records + uploading SSA performance) is
// the Impact Assessment + Admin job. Country Director does NOT upload data — CD
// only sets cost/price (see cost-setting-actions.ts). That role split is
// enforced here by DATA_INTAKE_ROLES, not by the UI alone.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut } from "./audit";
import { newId } from "./store";
import {
  DATA_INTAKE_ROLES,
  SSA_INTERVENTION_AREAS,
  deriveFyFromDate,
  deriveQuarterFromDate,
  ssaAverage,
  validateNewSchool,
  validateSsaUpload,
  type NewSchoolInput,
  type SsaInterventionArea,
  type SsaUploadInput,
} from "@/lib/intake/intake-core";
import { addIntakeSchool, addSsaUpload, assignSchoolToCceo, intakeSchoolIds, intakeSchools, updateIntakeSchool, type IntakeSchoolEditable } from "@/lib/intake/intake-mock";
import { orgStaff } from "@/lib/org/supervision";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { findDuplicateCandidates } from "@/lib/intake/duplicate-detection";
import { addDuplicateCandidate, resolveDuplicateCandidate } from "@/lib/intake/duplicate-candidates-mock";
import type { IntakeSchool } from "@/lib/intake/intake-mock";
import { getIntakeTemplate } from "@/lib/intake/intake-templates";
import { validateIntakeValues } from "@/lib/intake/intake-validate";
import { addIntakeRecords } from "@/lib/intake/intake-records-mock";

export type IntakeResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "INVALID_INPUT"; errors: Record<string, string> };

const INTAKE_ROLES = new Set<string>(DATA_INTAKE_ROLES);

// Flag (never block) a freshly-created school against the existing roster.
// Records a SchoolDuplicateCandidate per potential/strong match for the IA
// Duplicate Review Queue. Returns the number of flags raised.
function flagDuplicatesFor(school: IntakeSchool, others: IntakeSchool[], flaggedBy: string): number {
  const matches = findDuplicateCandidates(school, others.filter((o) => o.schoolId !== school.schoolId));
  for (const m of matches) {
    addDuplicateCandidate({
      schoolId: school.schoolId,
      schoolName: school.schoolName,
      matchSchoolId: m.matchSchoolId,
      matchSchoolName: m.matchSchoolName,
      score: m.score,
      band: m.band,
      reasons: m.reasons,
      flaggedBy,
    });
  }
  return matches.length;
}

// ─── 1. createSchool ───────────────────────────────────────────────

export async function createSchool(input: NewSchoolInput): Promise<IntakeResult> {
  const user = await getCurrentUser();
  if (!INTAKE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const v = validateNewSchool(input, intakeSchoolIds());
  if (!v.ok) return { ok: false, reason: "INVALID_INPUT", errors: v.errors };

  const enrollment =
    input.enrollment === undefined || input.enrollment === "" ? undefined : Number(input.enrollment);

  const row = addIntakeSchool({
    schoolId: input.schoolId.trim(),
    schoolName: input.schoolName.trim(),
    region: input.region,
    district: input.district,
    subCounty: input.subCounty,
    parish: input.parish,
    schoolType: input.schoolType,
    enrollment,
    assignedCceo: input.assignedCceo,
    cluster: input.cluster,
    dateAdded: new Date().toISOString().slice(0, 10),
    addedBy: user.name,
  });

  emitAudit({
    action: "intake.schoolCreated",
    subjectKind: "School",
    subjectId: row.schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { schoolName: row.schoolName, district: row.district, region: row.region, schoolType: row.schoolType },
  });

  // Duplicate detection — flag (never block) potential/strong matches for the
  // IA Duplicate Review Queue. The school stays live regardless.
  const flagged = flagDuplicatesFor(row, intakeSchools, user.name);
  if (flagged > 0) {
    emitAudit({
      action: "intake.duplicateFlagged",
      subjectKind: "School",
      subjectId: row.schoolId,
      actorId: user.staffId,
      actorRole: user.role,
      actorName: user.name,
      payload: { schoolName: row.schoolName, flags: flagged },
    });
    emitNotificationFanOut(["IMPACT_ASSESSMENT"], {
      template: "intake.duplicateFlagged",
      channel: "Inbox",
      title: "Possible duplicate school flagged",
      body: `${row.schoolName} looks similar to ${flagged} existing school${flagged === 1 ? "" : "s"}. Review in the duplicate queue.`,
      href: "/data-intake/duplicates",
    });
  }

  // A new school with no SSA is planning-locked — nudge the assigned CCEO /
  // IA team that an SSA is owed before planning can begin.
  emitNotificationFanOut(["IMPACT_ASSESSMENT", "CCEO"], {
    template: "intake.schoolAddedNeedsSsa",
    channel: "Inbox",
    title: "New school added — SSA required",
    body: `${row.schoolName} (${row.district}) is active but planning-locked until its first SSA is uploaded.`,
    href: "/data-intake",
  });

  revalidateIntakeSurfaces();
  return { ok: true, id: row.schoolId };
}

// ─── 1b. createSchoolsBulk (CSV upload) ────────────────────────────

export type BulkSchoolResult =
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: true; created: number; createdIds: string[]; failed: Array<{ schoolId: string; errors: Record<string, string> }> };

export async function createSchoolsBulk(inputs: NewSchoolInput[]): Promise<BulkSchoolResult> {
  const user = await getCurrentUser();
  if (!INTAKE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const createdIds: string[] = [];
  const createdRows: IntakeSchool[] = [];
  const failed: Array<{ schoolId: string; errors: Record<string, string> }> = [];
  const today = new Date().toISOString().slice(0, 10);

  for (const input of inputs) {
    // Re-validate server-side against the live id set (incl. rows just created).
    const v = validateNewSchool(input, intakeSchoolIds());
    if (!v.ok) {
      failed.push({ schoolId: input.schoolId, errors: v.errors });
      continue;
    }
    const enrollment =
      input.enrollment === undefined || input.enrollment === "" ? undefined : Number(input.enrollment);
    const row = addIntakeSchool({
      schoolId: input.schoolId.trim(),
      schoolName: input.schoolName.trim(),
      region: input.region,
      district: input.district,
      subCounty: input.subCounty,
      parish: input.parish,
      schoolType: input.schoolType,
      enrollment,
      assignedCceo: input.assignedCceo,
      cluster: input.cluster,
      dateAdded: today,
      addedBy: user.name,
    });
    createdIds.push(row.schoolId);
    createdRows.push(row);
  }

  // Duplicate detection — flag (never block) each created school. Compared
  // against the full live roster so cross-batch look-alikes are caught too.
  let flaggedTotal = 0;
  for (const row of createdRows) flaggedTotal += flagDuplicatesFor(row, intakeSchools, user.name);

  if (createdIds.length > 0) {
    emitAudit({
      action: "intake.schoolsBulkCreated",
      subjectKind: "School",
      subjectId: `bulk:${createdIds.length}`,
      actorId: user.staffId,
      actorRole: user.role,
      actorName: user.name,
      payload: { created: createdIds.length, failed: failed.length, ids: createdIds.slice(0, 50) },
    });
    emitNotificationFanOut(["IMPACT_ASSESSMENT", "CCEO"], {
      template: "intake.schoolsBulkAdded",
      channel: "Inbox",
      title: `${createdIds.length} schools added by CSV`,
      body: `${createdIds.length} new schools are active but planning-locked until each gets its first SSA.`,
      href: "/data-intake",
    });
    if (flaggedTotal > 0) {
      emitAudit({
        action: "intake.duplicateFlagged",
        subjectKind: "School",
        subjectId: `bulk:${createdIds.length}`,
        actorId: user.staffId,
        actorRole: user.role,
        actorName: user.name,
        payload: { flags: flaggedTotal, created: createdIds.length },
      });
      emitNotificationFanOut(["IMPACT_ASSESSMENT"], {
        template: "intake.duplicateFlagged",
        channel: "Inbox",
        title: "Possible duplicate schools flagged",
        body: `${flaggedTotal} possible duplicate${flaggedTotal === 1 ? "" : "s"} from this CSV need review.`,
        href: "/data-intake/duplicates",
      });
    }
    revalidateIntakeSurfaces();
  }

  return { ok: true, created: createdIds.length, createdIds, failed };
}

// ─── 2. uploadSsaPerformance ───────────────────────────────────────

export async function uploadSsaPerformance(input: SsaUploadInput): Promise<
  IntakeResult & { fy?: string; quarter?: string; averageScore?: number }
> {
  const user = await getCurrentUser();
  if (!INTAKE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const v = validateSsaUpload(input);
  if (!v.ok) return { ok: false, reason: "INVALID_INPUT", errors: v.errors };

  const fy = deriveFyFromDate(input.ssaDate);
  const quarter = deriveQuarterFromDate(input.ssaDate);
  const scores: Record<string, number> = {};
  for (const [area, raw] of Object.entries(input.scores)) scores[area] = Number(raw);
  const averageScore = ssaAverage(input.scores as Partial<Record<SsaInterventionArea, number>>);
  const newEnrollment =
    input.newEnrollment === undefined || input.newEnrollment === "" ? undefined : Number(input.newEnrollment);

  const row = addSsaUpload({
    id: newId("ssaup"),
    schoolId: input.schoolId,
    ssaDate: input.ssaDate,
    fy,
    quarter,
    scores,
    newEnrollment,
    uploadedBy: user.name,
  });

  emitAudit({
    action: "intake.ssaUploaded",
    subjectKind: "SsaSnapshot",
    subjectId: row.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { schoolId: input.schoolId, fy, quarter, averageScore },
  });
  emitNotificationFanOut(["CCEO", "PROGRAM_LEAD"], {
    template: "intake.ssaUploaded",
    channel: "Inbox",
    title: "SSA uploaded — planning unlocked",
    body: `${input.schoolId} scored ${averageScore}/10 avg (${quarter} FY ${fy}). Planning is now open.`,
    href: `/schools/${input.schoolId}`,
  });

  revalidateIntakeSurfaces(input.schoolId);
  return { ok: true, id: row.id, fy, quarter, averageScore };
}

// ─── 3. submitIntakeRecords (generic — manual single row OR CSV bulk) ──
//
// One action for every field-described template (visits, trainings, exam
// results, expenses, activity, and SSA-via-CSV). Re-validates each row
// server-side, then stores. SSA rows are routed through uploadSsaPerformance so
// the planning-unlock + FY/quarter derivation still fire.

export type IntakeRecordsResult =
  | { ok: false; reason: "FORBIDDEN" | "UNKNOWN_TEMPLATE" }
  | { ok: true; created: number; failed: Array<{ row: number; errors: Record<string, string> }> };

export async function submitIntakeRecords(
  templateId: string,
  rows: Array<Record<string, string>>,
): Promise<IntakeRecordsResult> {
  const user = await getCurrentUser();
  if (!INTAKE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const template = getIntakeTemplate(templateId);
  if (!template) return { ok: false, reason: "UNKNOWN_TEMPLATE" };

  const failed: Array<{ row: number; errors: Record<string, string> }> = [];

  // SSA gets special handling: reuse the unlock + FY-derive path per row.
  if (templateId === "tpl-ssa-performance") {
    let created = 0;
    for (let i = 0; i < rows.length; i++) {
      const v = validateIntakeValues(template, rows[i], intakeSchoolIds());
      if (Object.keys(v).length > 0) { failed.push({ row: i + 1, errors: v }); continue; }
      const scores: Partial<Record<SsaInterventionArea, number | string>> = {};
      for (const area of SSA_INTERVENTION_AREAS) scores[area] = rows[i][area];
      const res = await uploadSsaPerformance({
        schoolId: rows[i]["School ID"],
        ssaDate: rows[i]["SSA Date"],
        newEnrollment: rows[i]["Enrolment"],
        scores,
      });
      if (res.ok) created += 1;
      else failed.push({ row: i + 1, errors: res.reason === "INVALID_INPUT" ? res.errors : { _: "Rejected." } });
    }
    return { ok: true, created, failed };
  }

  const valid: Array<Record<string, string>> = [];
  for (let i = 0; i < rows.length; i++) {
    const v = validateIntakeValues(template, rows[i], intakeSchoolIds());
    if (Object.keys(v).length > 0) failed.push({ row: i + 1, errors: v });
    else valid.push(rows[i]);
  }

  if (valid.length > 0) {
    addIntakeRecords(templateId, valid, user.name);
    emitAudit({
      action: "intake.recordsSubmitted",
      subjectKind: "IntakeRecord",
      subjectId: `${templateId}:${valid.length}`,
      actorId: user.staffId,
      actorRole: user.role,
      actorName: user.name,
      payload: { templateId, created: valid.length, failed: failed.length },
    });
    revalidateIntakeSurfaces();
  }

  return { ok: true, created: valid.length, failed };
}

// ─── 4. assignSchoolsToStaff (IA school assignment → clears the activation gate) ──
//
// IA assigns onboarded schools to a staff member (their Account Owner). This is
// what moves a newly-created CCEO from "Pending School Assignment" forward: the
// schools land in their portfolio + planning scope, and the activation engine
// recomputes their status.

export type AssignSchoolsResult =
  | { ok: false; reason: "FORBIDDEN" | "STAFF_NOT_FOUND" | "INVALID_INPUT" }
  | { ok: true; assigned: number; staffName: string };

export async function assignSchoolsToStaff(staffId: string, schoolIds: string[]): Promise<AssignSchoolsResult> {
  const user = await getCurrentUser();
  if (!INTAKE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };

  const staff = orgStaff(staffId);
  if (!staff) return { ok: false, reason: "STAFF_NOT_FOUND" };
  if (!schoolIds.length) return { ok: false, reason: "INVALID_INPUT" };

  let assigned = 0;
  for (const id of schoolIds) {
    if (assignSchoolToCceo(id, staff.name)) assigned += 1;
  }

  if (assigned > 0) {
    emitAudit({
      action: "intake.schoolsAssignedToStaff",
      subjectKind: "Staff",
      subjectId: staffId,
      actorId: user.staffId,
      actorRole: user.role,
      actorName: user.name,
      payload: { staffName: staff.name, role: staff.role, assigned, schoolIds: schoolIds.slice(0, 50) },
    });
    emitNotificationFanOut(["CCEO"], {
      template: "intake.schoolsAssigned",
      channel: "Inbox",
      title: `${assigned} schools assigned to ${staff.name}`,
      body: `${staff.name} now owns ${assigned} school(s). Their planning scope, targets, and dashboard activate as onboarding completes.`,
      href: "/admin/users",
    });
    revalidateIntakeSurfaces();
    try { revalidatePath("/admin/users"); revalidatePath("/planning"); } catch { /* outside request */ }
  }

  return { ok: true, assigned, staffName: staff.name };
}

// ─── 5. updateSchoolDetails (complete optional fields after upload) ──
//
// A school is created with only the 4 required fields; staff/IA fill the rest
// (enrolment, contact, phone, address, owner, cluster) here, any time later.

export type UpdateSchoolResult =
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" | "INVALID_INPUT"; field?: string }
  | { ok: true; schoolId: string };

export async function updateSchoolDetails(schoolId: string, patch: IntakeSchoolEditable): Promise<UpdateSchoolResult> {
  const user = await getCurrentUser();
  if (!INTAKE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (patch.enrollment !== undefined && patch.enrollment !== null) {
    const n = Number(patch.enrollment);
    if (!Number.isFinite(n) || n < 0) return { ok: false, reason: "INVALID_INPUT", field: "enrollment" };
    patch.enrollment = n;
  }
  const row = updateIntakeSchool(schoolId, patch);
  if (!row) return { ok: false, reason: "NOT_FOUND" };

  emitAudit({
    action: "intake.schoolDetailsUpdated",
    subjectKind: "School",
    subjectId: schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { fields: Object.keys(patch), schoolName: row.schoolName },
  });
  revalidateIntakeSurfaces(schoolId);
  return { ok: true, schoolId };
}

// ─── 6. mapUnmatchedOwner (IA owner-mapping queue) ──────────────────
//
// When a school is uploaded with an Account Owner whose name doesn't resolve to
// a registered staff member, it surfaces in the IA owner-mapping queue. Here IA
// maps that exact entered name to a real staff member — rewriting those schools'
// owner to the staff's canonical name so they auto-distribute into the right
// portfolio. This is mapping, never deletion.

export type MapOwnerResult =
  | { ok: false; reason: "FORBIDDEN" | "STAFF_NOT_FOUND" | "NO_MATCH" }
  | { ok: true; mapped: number; staffName: string };

export async function mapUnmatchedOwner(enteredName: string, staffId: string): Promise<MapOwnerResult> {
  const user = await getCurrentUser();
  if (!INTAKE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const staff = orgStaff(staffId);
  if (!staff) return { ok: false, reason: "STAFF_NOT_FOUND" };

  const target = enteredName.trim().toLowerCase();
  const schools = intakeSchools.filter((s) => {
    const r = resolveOwner(s.assignedCceo);
    return r.status === "unmatched" && r.name.trim().toLowerCase() === target;
  });
  if (schools.length === 0) return { ok: false, reason: "NO_MATCH" };

  for (const s of schools) updateIntakeSchool(s.schoolId, { assignedCceo: staff.name });

  emitAudit({
    action: "intake.ownerMapped",
    subjectKind: "Staff",
    subjectId: staffId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { enteredName, mappedTo: staff.name, schoolIds: schools.map((s) => s.schoolId) },
  });
  emitNotificationFanOut([staffId], {
    template: "portfolio.schoolsMappedToYou",
    channel: "Inbox",
    title: "Schools added to your portfolio",
    body: `${schools.length} school${schools.length === 1 ? "" : "s"} previously uploaded under "${enteredName}" ${schools.length === 1 ? "was" : "were"} mapped to you.`,
    href: "/portfolio",
  });
  revalidateIntakeSurfaces();
  revalidatePath("/portfolio");
  return { ok: true, mapped: schools.length, staffName: staff.name };
}

// ─── 7. resolveDuplicate (IA Duplicate Review Queue) ────────────────
//
// Flag-not-block means a human always decides. IA either dismisses the flag
// ("Not a duplicate") or confirms it ("Confirmed duplicate" — acknowledged for
// follow-up). We never auto-delete or auto-merge; both schools stay live and
// the resolution is recorded for the audit trail.

export type ResolveDuplicateResult =
  | { ok: false; reason: "FORBIDDEN" | "NOT_FOUND" }
  | { ok: true; id: string; status: "Dismissed" | "Confirmed" };

export async function resolveDuplicate(
  id: string,
  status: "Dismissed" | "Confirmed",
  note?: string,
): Promise<ResolveDuplicateResult> {
  const user = await getCurrentUser();
  if (!INTAKE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const row = resolveDuplicateCandidate(id, status, user.name, note);
  if (!row) return { ok: false, reason: "NOT_FOUND" };

  emitAudit({
    action: status === "Dismissed" ? "intake.duplicateDismissed" : "intake.duplicateConfirmed",
    subjectKind: "School",
    subjectId: row.schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { matchSchoolId: row.matchSchoolId, score: row.score, band: row.band, note },
  });
  revalidatePath("/data-intake/duplicates");
  revalidatePath("/data-intake");
  return { ok: true, id, status };
}

function revalidateIntakeSurfaces(schoolId?: string) {
  try {
    revalidatePath("/data-intake");
    revalidatePath("/data-intake/upload");
    revalidatePath("/data-intake/queue");
    revalidatePath("/data-intake/readiness");
    revalidatePath("/analytics");
    revalidatePath("/dashboards/impact");
    if (schoolId) revalidatePath(`/schools/${schoolId}`);
    revalidatePath("/notifications");
  } catch { /* outside request */ }
}

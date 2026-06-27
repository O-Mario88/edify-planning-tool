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
  SSA_AREA_TO_BACKEND,
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
import { isBackendEnabled, type BackendUser } from "@/lib/api/backend";
import { isMockAllowed } from "@/lib/mock-policy";
import { backendCreateSchool, backendBulkSchools, backendUploadSsa, backendSetSchoolType, fetchDistricts, fetchSubCounties, fetchParishes, type BackendSchoolWrite } from "@/lib/api/surfaces";

// FE school-type label → backend SchoolType enum key.
const SCHOOL_TYPE_TO_BACKEND: Record<string, string> = {
  Client: "client",
  Core: "core",
  "Potential Core": "potential_core",
  Champion: "champion",
  "Potential Champion": "potential_champion",
  Other: "other",
};

// Resolve a school's region/district/sub-county NAMES to backend geography IDs
// (the create-school DTO needs regionId + districtId). Returns null if the
// district name doesn't match a backend district (caller falls back to mock).
async function resolveSchoolGeography(
  user: BackendUser,
  districtName: string,
  subCountyName?: string,
  parishName?: string,
): Promise<{ regionId: string; districtId: string; subCountyId?: string; parishId?: string } | null> {
  const dRes = await fetchDistricts(user);
  if (!dRes.live) return null;
  const district = dRes.data.find((d) => d.name.toLowerCase() === districtName.toLowerCase());
  if (!district) return null;
  let subCountyId: string | undefined;
  let parishId: string | undefined;
  if (subCountyName) {
    const scRes = await fetchSubCounties(user, district.id);
    if (scRes.live) subCountyId = scRes.data.find((s) => s.name.toLowerCase() === subCountyName.toLowerCase())?.id;
    if (subCountyId && parishName) {
      const pRes = await fetchParishes(user, subCountyId);
      if (pRes.live) parishId = pRes.data.find((p) => p.name.toLowerCase() === parishName.toLowerCase())?.id;
    }
  }
  return { regionId: district.regionId, districtId: district.id, subCountyId, parishId };
}

function beUser(u: { email: string; role: string }): BackendUser {
  return { email: u.email, role: u.role };
}

export type IntakeResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN"; message?: string }
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

  // ── Backend-first: persist the school master record to Postgres (POST
  // /schools). Resolve district/sub-county names → backend geography IDs. On a
  // backend error (e.g. duplicate schoolId) surface it; otherwise mirror into
  // the in-memory store so the FE's mock-reading intake surfaces stay in sync. ──
  if (isBackendEnabled()) {
    const geo = await resolveSchoolGeography(beUser(user), input.district, input.subCounty, input.parish);
    // Backend-authoritative: if the district/sub-county can't be resolved to a
    // backend geography ID, the school CANNOT be persisted to Postgres. We must
    // NOT silently fall back to the in-memory mirror and report success — that's
    // exactly how an "uploaded" school went missing from the live directory.
    // Surface a precise, correctable error instead.
    if (!geo) {
      return {
        ok: false,
        reason: "INVALID_INPUT",
        errors: { district: `"${input.district}" did not match a district in the backend geography. Check the spelling against the official district list.` },
      };
    }
    const r = await backendCreateSchool(beUser(user), {
      schoolId: input.schoolId.trim(),
      name: input.schoolName.trim(),
      regionId: geo.regionId,
      districtId: geo.districtId,
      subCountyId: geo.subCountyId,
      parishId: geo.parishId,
      enrollment,
      schoolType: SCHOOL_TYPE_TO_BACKEND[input.schoolType] ?? "client",
      accountOwnerName: input.assignedCceo,
    });
    if (!r.live) {
      return { ok: false, reason: "INVALID_INPUT", errors: { schoolId: `Backend rejected: ${r.error ?? "the school could not be saved."}` } };
    }
    // Backend authoritative: do NOT mirror into the in-memory store — it would
    // silently substitute fabricated data if the backend later diverges. The
    // live directory is the single source of truth. Revalidate the directory
    // (and the analytics surfaces it feeds) so the new school shows live.
    try {
      revalidatePath("/schools");
      revalidatePath("/data-intake");
      revalidatePath("/dashboards/impact");
      revalidatePath("/analytics");
    } catch { /* outside request */ }
    return { ok: true, id: input.schoolId.trim() };
  }

  // Backend disabled — dev/demo only. The in-memory store is the seed.
  if (!isMockAllowed()) {
    return { ok: false, reason: "FORBIDDEN", message: "Adding schools requires the live backend." };
  }

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

  // Cluster-first: a freshly uploaded school is unclustered. The required next
  // setup step is cluster assignment (it unlocks SSA / SIT and planning), so
  // nudge the assigned CCEO / IA team to the School Directory to cluster it.
  emitNotificationFanOut(["IMPACT_ASSESSMENT", "CCEO"], {
    template: "intake.schoolAddedNeedsCluster",
    channel: "Inbox",
    title: "New school added — assign to a cluster",
    body: `${row.schoolName} (${row.district}) is active and in its owner's portfolio. Assign it to a cluster — the next setup step — before planning support.`,
    href: "/schools",
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

  // Re-validate every row server-side against the live id set first.
  const validInputs: NewSchoolInput[] = [];
  for (const input of inputs) {
    const v = validateNewSchool(input, intakeSchoolIds());
    if (!v.ok) { failed.push({ schoolId: input.schoolId, errors: v.errors }); continue; }
    validInputs.push(input);
  }

  // Backend-first: resolve each row's geography → IDs and submit ONE tracked
  // batch (POST /schools/bulk creates an UploadBatch + per-row dedupe/owner-map).
  // Previously bulk CSV did N individual POSTs with no batch record. Rows whose
  // district can't be resolved are recorded as failures, never silently saved to
  // the in-memory mirror only.
  const persistedInputs: NewSchoolInput[] = [];
  if (isBackendEnabled()) {
    const beRows: BackendSchoolWrite[] = [];
    const inputBySchoolId = new Map<string, NewSchoolInput>();
    for (const input of validInputs) {
      const geo = await resolveSchoolGeography(beUser(user), input.district, input.subCounty);
      if (!geo) {
        failed.push({ schoolId: input.schoolId, errors: { district: `"${input.district}" did not match a backend district.` } });
        continue;
      }
      const enrollment = input.enrollment === undefined || input.enrollment === "" ? undefined : Number(input.enrollment);
      const beRow: BackendSchoolWrite = {
        schoolId: input.schoolId.trim(),
        name: input.schoolName.trim(),
        regionId: geo.regionId,
        districtId: geo.districtId,
        subCountyId: geo.subCountyId,
        enrollment,
        schoolType: SCHOOL_TYPE_TO_BACKEND[input.schoolType] ?? "client",
        accountOwnerName: input.assignedCceo,
      };
      beRows.push(beRow);
      inputBySchoolId.set(beRow.schoolId, input);
    }

    if (beRows.length > 0) {
      const res = await backendBulkSchools(beUser(user), "intake-csv-upload.csv", beRows);
      if (!res.live) {
        for (const r of beRows) {
          failed.push({ schoolId: r.schoolId, errors: { schoolId: `Backend rejected: ${res.error ?? "the bulk import could not be saved."}` } });
        }
      } else {
        for (const result of res.data.results) {
          const input = inputBySchoolId.get(result.schoolId);
          if (result.ok && input) persistedInputs.push(input);
          else failed.push({ schoolId: result.schoolId, errors: { schoolId: `Backend rejected: ${result.reason ?? "duplicate or invalid row"}` } });
        }
      }
    }
  } else {
    // Mock mode (dev only): the in-memory store is the source of truth.
    persistedInputs.push(...validInputs);
  }

  // Track the IDs of every successfully-persisted row (used for audit +
  // notifications below). The in-memory store mirror is dev-only.
  for (const input of persistedInputs) {
    createdIds.push(input.schoolId.trim());
  }
  if (isMockAllowed()) for (const input of persistedInputs) {
    const enrollment = input.enrollment === undefined || input.enrollment === "" ? undefined : Number(input.enrollment);
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
      body: `${createdIds.length} new schools are active and in their owners' portfolios. Assign them to clusters (the next setup step) before planning support.`,
      href: "/schools",
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

  // ── Backend-first: persist the SSA record + per-intervention scores to
  // Postgres (POST /ssa). Maps the FE display labels → backend enum keys. This
  // is what feeds the live SSA-driven recommendations (cluster dashboard,
  // planning interventions). On a backend error, surface it. ──
  if (isBackendEnabled()) {
    const beScores = Object.entries(input.scores)
      .map(([area, raw]) => ({ intervention: SSA_AREA_TO_BACKEND[area as SsaInterventionArea], score: Number(raw) }))
      .filter((s) => s.intervention && Number.isFinite(s.score));
    // Backend-authoritative: all 8 intervention areas must map to a backend enum
    // and persist. If fewer than 8 mapped, the FE labels drifted from
    // SSA_AREA_TO_BACKEND — fail loudly instead of writing a mock-only row that
    // never reaches the SSA-driven planning/recommendation engine.
    if (beScores.length < 8) {
      return { ok: false, reason: "INVALID_INPUT", errors: { scores: "Could not map all 8 SSA intervention areas to the backend. Refresh and re-enter the scores." } };
    }
    const r = await backendUploadSsa(beUser(user), {
      schoolId: input.schoolId,
      dateOfSsa: new Date(input.ssaDate).toISOString(),
      newEnrollment,
      scores: beScores,
    });
    if (!r.live) {
      return { ok: false, reason: "INVALID_INPUT", errors: { schoolId: `Backend rejected: ${r.error ?? "the SSA could not be saved. Confirm the school exists in the directory first."}` } };
    }
  }

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

// ─── 8. changeSchoolType (Client → Core → Champion) ─────────────────
//
// Editing a school's type promotes/demotes it across the dashboards: setting
// it to Core moves it onto the Core School dashboard (and increases the core
// count); Champion marks a graduated core school. Backend-first; the system
// proposes potential Core (best client SSA) / Champion (best core SSA) via
// fetchSchoolProposals.

const SCHOOL_TYPE_ROLES = new Set<string>([...DATA_INTAKE_ROLES, "CountryDirector", "CountryProgramLead", "CCEO"]);

export type ChangeTypeResult =
  | { ok: false; reason: "FORBIDDEN" | "INVALID_INPUT" | "FAILED"; message?: string }
  | { ok: true; schoolId: string; schoolType: string };

export async function changeSchoolType(schoolId: string, label: string): Promise<ChangeTypeResult> {
  const user = await getCurrentUser();
  if (!SCHOOL_TYPE_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  const beType = SCHOOL_TYPE_TO_BACKEND[label];
  if (!beType) return { ok: false, reason: "INVALID_INPUT" };

  if (isBackendEnabled()) {
    const r = await backendSetSchoolType(beUser(user), schoolId, beType);
    if (!r.live) return { ok: false, reason: "FAILED", message: r.error ?? "Could not change the school type." };
  }
  // The backend is the source of truth for school type; the directory + core
  // dashboard read it live, so no mock mirror is needed here.

  emitAudit({
    action: "intake.schoolTypeChanged", subjectKind: "School", subjectId: schoolId,
    actorId: user.staffId, actorRole: user.role, actorName: user.name,
    payload: { schoolType: label },
  });
  revalidateIntakeSurfaces(schoolId);
  try { revalidatePath("/core-schools"); revalidatePath("/schools"); } catch { /* outside request */ }
  return { ok: true, schoolId, schoolType: beType };
}

function revalidateIntakeSurfaces(schoolId?: string) {
  try {
    // The School Directory is the source of truth — always refresh it after an
    // intake mutation so uploaded/updated rows show live (previously /schools was
    // never revalidated here, leaving the directory stale after an upload).
    revalidatePath("/schools");
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

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
  deriveFyFromDate,
  deriveQuarterFromDate,
  ssaAverage,
  validateNewSchool,
  validateSsaUpload,
  type NewSchoolInput,
  type SsaInterventionArea,
  type SsaUploadInput,
} from "@/lib/intake/intake-core";
import { addIntakeSchool, addSsaUpload, intakeSchoolIds } from "@/lib/intake/intake-mock";

export type IntakeResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "INVALID_INPUT"; errors: Record<string, string> };

const INTAKE_ROLES = new Set<string>(DATA_INTAKE_ROLES);

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

"use server";

// W7 — SSA (Self-Service Assessment) server actions.
//
// SSA snapshots are the trajectory measurement. Each snapshot stores:
//   • current score (0..10 — higher = better)
//   • a pointer to the previous snapshot in the same (school, area)
//   • a computed trend ("Improved" | "Held" | "Declined" | "Inconclusive")
//
// Integrity rule #5: a school whose latest snapshot in
// TeachingAndLearning is below 5 should surface as a recommended
// in-school coaching activity in plan-builder. The recommendation
// helper here is consumed by the planner — keeping it server-side
// means the planner never sees a stale rec.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit, emitNotificationFanOut } from "./audit";
import {
  type ActivityKind,
  type DonorCountStatus,
  type DonorEvidenceStatus,
  type InterventionArea,
  type SsaSnapshotRecord,
  type SsaTrend,
  latestSsaSnapshotFor,
  newId,
  ssaSnapshots as ssaSnapshotsStore,
} from "./store";

export type SsaActionResult<T = { id: string }> =
  | ({ ok: true } & T)
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "NOT_FOUND" }
  | { ok: false; reason: "INVALID_INPUT"; field: string };

// Recording SSAs is the M&E + CCEO job. CCEO captures the assessment;
// M&E verifies. Both roles allowed to write a snapshot — the verified
// status differs.
const SSA_AUTHOR_ROLES = new Set(["CCEO", "ImpactAssessment", "Admin"]);

// ─── 1. recordSsaSnapshot ──────────────────────────────────────────

export async function recordSsaSnapshot(input: {
  schoolId: string;
  interventionArea: InterventionArea;
  score: number;                  // 0..10
  completedAt?: string;           // defaults to now
  notes?: string;
}): Promise<SsaActionResult & { trend?: SsaTrend; previousScore?: number }> {
  const user = await getCurrentUser();
  if (!SSA_AUTHOR_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  if (!input.schoolId) return { ok: false, reason: "INVALID_INPUT", field: "schoolId" };
  if (input.score < 0 || input.score > 10) {
    return { ok: false, reason: "INVALID_INPUT", field: "score" };
  }
  const completedAt = input.completedAt ?? new Date().toISOString();

  // Compute trend against the latest snapshot in the same area.
  const prev = latestSsaSnapshotFor(input.schoolId, input.interventionArea);
  const trend: SsaTrend = !prev
    ? "Inconclusive"
    : input.score > prev.score ? "Improved"
    : input.score < prev.score ? "Declined"
    : "Held";

  // M&E gets the highest evidence tier on write because they are the
  // independent verifier. CCEO writes start as "Uploaded" (pending M&E).
  const evidenceStatus: DonorEvidenceStatus = user.role === "ImpactAssessment" ? "MeVerified" : "Uploaded";
  const donorCountStatus: DonorCountStatus = evidenceStatus === "MeVerified"
    ? "included_verified"
    : "pending_verification";

  const row: SsaSnapshotRecord = {
    id: newId("ssa"),
    schoolId: input.schoolId,
    interventionArea: input.interventionArea,
    score: input.score,
    completedAt,
    completed: true,
    trend,
    previousId: prev?.id,
    conductedById: user.staffId,
    evidenceStatus,
    donorCountStatus,
    notes: input.notes,
    createdAt: new Date().toISOString(),
  };
  ssaSnapshotsStore().push(row);

  emitAudit({
    action: "ssa.snapshotRecorded",
    subjectKind: "SsaSnapshot",
    subjectId: row.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      schoolId: input.schoolId,
      area: input.interventionArea,
      score: input.score,
      previousScore: prev?.score,
      trend,
    },
  });
  // If the snapshot is a meaningful improvement, surface it to CPL
  // and IA — those audiences track "Schools Improved" donor metric.
  if (trend === "Improved" && (prev?.score ?? 0) < 5 && input.score >= 5) {
    emitNotificationFanOut(["PROGRAM_LEAD", "IMPACT_ASSESSMENT"], {
      template: "ssa.schoolImproved",
      channel: "Inbox",
      title: "School moved into Healthy band",
      body: `${input.interventionArea} score: ${prev?.score ?? "—"} → ${input.score}.`,
      href: `/schools/${input.schoolId}`,
    });
  }

  revalidateSsaSurfaces(input.schoolId);
  return { ok: true, id: row.id, trend, previousScore: prev?.score };
}

// ─── 2. recomputeSchoolRisk ────────────────────────────────────────
//
// Re-evaluates a school's risk tone from its latest SSA scores across
// every intervention area. Pure read on the store; returns the tone
// for the caller to apply (in mock-mode we don't persist school rows
// — the production swap writes School.riskTone).

export async function recomputeSchoolRisk(schoolId: string): Promise<
  SsaActionResult & {
    weakestArea?: InterventionArea;
    weakestScore?: number;
    tone?: "RED" | "AMBER" | "GREEN";
  }
> {
  const user = await getCurrentUser();
  if (!SSA_AUTHOR_ROLES.has(user.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  // Latest per area.
  const areas: InterventionArea[] = [
    "TeachingAndLearning", "FinancialHealth", "ChristlikeBehaviour",
    "ExposureToWordOfGod", "GovernmentComplianceAndRequirements",
    "Leadership", "EducationTechnology", "LearningEnvironment",
  ];
  let weakestArea: InterventionArea | undefined;
  let weakestScore = Infinity;
  for (const a of areas) {
    const snap = latestSsaSnapshotFor(schoolId, a);
    if (!snap) continue;
    if (snap.score < weakestScore) {
      weakestScore = snap.score;
      weakestArea = a;
    }
  }
  if (weakestArea == null) {
    return { ok: false, reason: "NOT_FOUND" };
  }

  const tone = weakestScore <= 3 ? "RED" : weakestScore <= 5 ? "AMBER" : "GREEN";

  emitAudit({
    action: "ssa.riskRecomputed",
    subjectKind: "School",
    subjectId: schoolId,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: { weakestArea, weakestScore, tone },
  });
  revalidateSsaSurfaces(schoolId);
  return { ok: true, id: schoolId, weakestArea, weakestScore, tone };
}

// ─── 3. recommendedActivitiesForSchool (read-only helper) ──────────
//
// Plan-builder integration. Integrity rule #5: weak areas → prescribed
// activity kinds. Returns the recommended `(kind, reason)` list for
// the latest snapshot per area, with severity-band justification.
//
// Exported as a server action (not just a plain function) so the
// plan-builder UI can call it via fetch / form-action without leaking
// the entity store into a client bundle.

export async function recommendedActivitiesForSchool(schoolId: string): Promise<
  Array<{ kind: ActivityKind; reason: string; weakArea: InterventionArea; score: number }>
> {
  // No role gate — recommendations are advisory; any signed-in user
  // can ask. (Middleware still enforces shell auth.)
  const out: Array<{ kind: ActivityKind; reason: string; weakArea: InterventionArea; score: number }> = [];
  const ACTIVITY_FOR_AREA: Record<InterventionArea, ActivityKind> = {
    TeachingAndLearning:                "IN_SCHOOL_COACHING",
    FinancialHealth:                    "PARTNER_FOLLOW_UP",
    ChristlikeBehaviour:                "TRAINING_FOLLOW_UP",
    ExposureToWordOfGod:                "TRAINING_FOLLOW_UP",
    GovernmentComplianceAndRequirements:"COURTESY_VISIT",
    Leadership:                         "CLUSTER_TRAINING",
    EducationTechnology:                "IN_SCHOOL_COACHING",
    LearningEnvironment:                "SCHOOL_VISIT",
  };
  const areas = Object.keys(ACTIVITY_FOR_AREA) as InterventionArea[];
  for (const a of areas) {
    const snap = latestSsaSnapshotFor(schoolId, a);
    if (!snap) continue;
    if (snap.score >= 5) continue;
    const band = snap.score <= 3 ? "Critical" : "At-risk";
    out.push({
      kind: ACTIVITY_FOR_AREA[a],
      weakArea: a,
      score: snap.score,
      reason: `${band} in ${a} (score ${snap.score}/10) — prescribed: ${ACTIVITY_FOR_AREA[a]}`,
    });
  }
  // Stable order: critical first, then by score asc.
  out.sort((x, y) => x.score - y.score);
  return out;
}

function revalidateSsaSurfaces(schoolId?: string) {
  try {
    revalidatePath("/ssa");
    revalidatePath("/ssa/core-candidates");
    revalidatePath("/core-schools");
    revalidatePath("/fy/ssa-comparison");
    if (schoolId) revalidatePath(`/schools/${schoolId}`);
    revalidatePath("/dashboards/cceo");
    revalidatePath("/dashboards/impact");
    revalidatePath("/notifications");
  } catch { /* outside request */ }
}

"use server";

// W11 — Donor reporting snapshot server action.
//
// Builds a deterministic donor metric snapshot from the live entity
// stores, with strict evidence gating per integrity rule #4:
//
//   • TrainingParticipants only count when evidenceStatus IN
//     (CceoConfirmed, MeVerified)
//   • PartnerActivities only count when status === MeVerified
//   • SsaSnapshots only count when evidenceStatus === MeVerified
//     (for "Schools Improved")
//
// Determinism guarantee (integrity rule "deterministic donor report"):
// for a fixed (roleScope, filters, dateRange) the same input data
// produces an identical filtersHash and identical numbers. Two
// snapshots taken at the same minute on the same store state will
// agree to the cent.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { emitAudit } from "./audit";
import {
  type DonorEvidenceStatus,
  type DonorMetricSnapshotRecord,
  type DonorRoleScope,
  type InterventionArea,
  donorSnapshots as donorSnapshotsStore,
  newId,
  partnerActivities as partnerActivitiesStore,
  schoolVisits as schoolVisitsStore,
  ssaSnapshots as ssaSnapshotsStore,
  trainingParticipants as participantsStore,
  activities as activitiesStore,
  disbursements as disbursementsStore,
} from "./store";

export type DonorActionResult =
  | { ok: true; snapshotId: string; filtersHash: string; numbers: DonorMetricSnapshotRecord }
  | { ok: false; reason: "FORBIDDEN" }
  | { ok: false; reason: "INVALID_INPUT"; field: string };

const DONOR_ROLES = new Set([
  "CCEO",
  "CountryProgramLead",
  "ImpactAssessment",
  "CountryDirector",
  "RVP",
  "Admin",
]);

export type DonorFilters = {
  countryId?: string;
  districtIds?: string[];
  interventionAreas?: InterventionArea[];
  schoolIds?: string[];
};

// ─── Public action ──────────────────────────────────────────────────

export async function generateDonorSnapshot(input: {
  roleScope: DonorRoleScope;
  scopeLabel: string;
  operationalCycle: string;     // "FY 2025/26 · Q4"
  dateRangeStart: string;       // ISO date
  dateRangeEnd: string;         // ISO date
  filters?: DonorFilters;
}): Promise<DonorActionResult> {
  const user = await getCurrentUser();
  if (!DONOR_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!input.dateRangeStart || !input.dateRangeEnd) {
    return { ok: false, reason: "INVALID_INPUT", field: "dateRange" };
  }

  const filters = input.filters ?? {};
  const filtersHash = canonicalHash({
    roleScope: input.roleScope,
    dateRangeStart: input.dateRangeStart,
    dateRangeEnd:   input.dateRangeEnd,
    countryId:        filters.countryId ?? null,
    districtIds:      [...(filters.districtIds ?? [])].sort(),
    interventionAreas:[...(filters.interventionAreas ?? [])].sort(),
    schoolIds:        [...(filters.schoolIds ?? [])].sort(),
  });

  const dateStart = new Date(input.dateRangeStart).getTime();
  const dateEnd   = new Date(input.dateRangeEnd).getTime();
  const inDateRange = (iso: string) => {
    const t = new Date(iso).getTime();
    return Number.isFinite(t) && t >= dateStart && t <= dateEnd;
  };
  const matchesFilters = (areaOrSchoolId: { area?: InterventionArea; schoolId?: string }) => {
    if (filters.interventionAreas && filters.interventionAreas.length && areaOrSchoolId.area && !filters.interventionAreas.includes(areaOrSchoolId.area)) return false;
    if (filters.schoolIds && filters.schoolIds.length && areaOrSchoolId.schoolId && !filters.schoolIds.includes(areaOrSchoolId.schoolId)) return false;
    return true;
  };

  // ─── TrainingParticipant rollups ─────────────────────────────────
  // Identity-deduped: same identityKey counts once per participant
  // type even if they appear in multiple sessions.
  const participantsInRange = participantsStore()
    .filter((p) => inDateRange(p.createdAt))
    .filter((p) => matchesFilters({ schoolId: p.schoolId }));
  const verifiedParticipants = participantsInRange.filter(includedForDonor);

  const teachersTrained = countDistinct(
    verifiedParticipants.filter((p) => p.participantType === "Teacher").map((p) => p.identityKey),
  );
  const schoolLeadersTrained = countDistinct(
    verifiedParticipants.filter((p) => p.participantType === "SchoolLeader").map((p) => p.identityKey),
  );

  // ─── PartnerActivity rollups (MeVerified only) ───────────────────
  const partnerVerified = partnerActivitiesStore()
    .filter((a) => inDateRange(a.date))
    .filter((a) => a.status === "MeVerified")
    .filter((a) => matchesFilters({ area: a.interventionArea, schoolId: a.schoolId }));
  const partnerActivitiesConfirmed = partnerVerified.length;

  // ─── Visits + activities ─────────────────────────────────────────
  const visitsInRange = schoolVisitsStore().filter((v) => inDateRange(v.date));
  const trainingsDelivered = activitiesStore().filter(
    (a) => inDateRange(a.createdAt) && a.kind === "CLUSTER_TRAINING" && a.status === "Verified",
  ).length;

  // ─── SsaSnapshot rollups ─────────────────────────────────────────
  const ssaInRange = ssaSnapshotsStore().filter((s) => inDateRange(s.completedAt));
  const ssaVerified = ssaInRange.filter((s) => s.evidenceStatus === "MeVerified");
  const schoolsImproved = countDistinct(
    ssaVerified.filter((s) => s.trend === "Improved").map((s) => s.schoolId),
  );

  // ─── Geography rollups (distinct school / district counts) ───────
  const schoolsReached = countDistinct([
    ...participantsInRange.map((p) => p.schoolId).filter(isNonNullString),
    ...partnerVerified.map((a) => a.schoolId),
    ...visitsInRange.map((v) => v.schoolId),
  ]);

  // ─── Financials ──────────────────────────────────────────────────
  const totalInvestmentUgx = disbursementsStore().reduce((sum, d) => sum + d.amount.amount, 0);
  const costPerSchoolReachedUgx = schoolsReached > 0 ? Math.round(totalInvestmentUgx / schoolsReached) : undefined;
  const costPerTeacherTrainedUgx = teachersTrained > 0 ? Math.round(totalInvestmentUgx / teachersTrained) : undefined;

  // ─── Readiness scoring ───────────────────────────────────────────
  const verifiedCount = verifiedParticipants.length + ssaVerified.length + partnerVerified.length;
  const pendingEvidenceCount = participantsInRange.filter((p) => p.evidenceStatus === "Captured" || p.evidenceStatus === "None").length
                             + partnerActivitiesStore().filter((a) => a.status === "Delivered").length;
  const pendingVerificationCount = participantsInRange.filter((p) => p.evidenceStatus === "Uploaded").length
                                 + ssaInRange.filter((s) => s.evidenceStatus === "Uploaded" || s.evidenceStatus === "CceoConfirmed").length
                                 + partnerActivitiesStore().filter((a) => a.status === "CceoConfirmed").length;
  const excludedCount = participantsInRange.filter((p) => p.evidenceStatus === "Rejected").length
                      + partnerActivitiesStore().filter((a) => a.status === "Rejected").length;

  const totalConsidered = verifiedCount + pendingEvidenceCount + pendingVerificationCount + excludedCount;
  const readinessScore = totalConsidered === 0
    ? 0
    : Math.round((verifiedCount / totalConsidered) * 100);

  const now = new Date().toISOString();
  const snapshot: DonorMetricSnapshotRecord = {
    id: newId("dms"),
    roleScope: input.roleScope,
    userId: user.staffId,
    scopeLabel: input.scopeLabel,
    operationalCycle: input.operationalCycle,
    dateRangeStart: input.dateRangeStart,
    dateRangeEnd:   input.dateRangeEnd,
    filtersHash,
    filtersJson: filters as Record<string, unknown>,
    teachersTrained,
    schoolLeadersTrained,
    studentsImpacted: undefined, // requires enrollment table
    schoolsReached,
    districtsCovered: undefined, // requires district resolution
    trainingsDelivered,
    visitsCompleted: visitsInRange.length,
    ssaCompleted: ssaInRange.length,
    schoolsImproved,
    partnerActivitiesConfirmed,
    totalInvestmentUgx,
    costPerSchoolReachedUgx,
    costPerTeacherTrainedUgx,
    costPerStudentImpactedUgx: undefined,
    verifiedCount,
    pendingEvidenceCount,
    pendingVerificationCount,
    excludedCount,
    readinessScore,
    generatedAt: now,
    generatedByName: user.name,
  };
  donorSnapshotsStore().push(snapshot);

  emitAudit({
    action: "donor.snapshotGenerated",
    subjectKind: "DonorMetricSnapshot",
    subjectId: snapshot.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      filtersHash,
      teachersTrained,
      schoolsReached,
      readinessScore,
      operationalCycle: input.operationalCycle,
    },
  });

  try {
    revalidatePath("/donor-reporting");
    revalidatePath("/donor-reporting/print");
    revalidatePath("/dashboards/impact");
  } catch { /* outside request */ }

  return { ok: true, snapshotId: snapshot.id, filtersHash, numbers: snapshot };
}

// ─── Helpers ────────────────────────────────────────────────────────

// Evidence gate: only confirmed / verified participants count.
const COUNTABLE_EVIDENCE: Set<DonorEvidenceStatus> = new Set([
  "CceoConfirmed",
  "MeVerified",
]);

function includedForDonor(p: { evidenceStatus: DonorEvidenceStatus }): boolean {
  return COUNTABLE_EVIDENCE.has(p.evidenceStatus);
}

function countDistinct(values: (string | undefined | null)[]): number {
  const set = new Set<string>();
  for (const v of values) {
    if (v && v.length > 0) set.add(v);
  }
  return set.size;
}

function isNonNullString(v: unknown): v is string {
  return typeof v === "string" && v.length > 0;
}

// Stable hash of a canonical object. Real implementation: SHA-256
// of a sorted-key JSON. For the mock store we use a simple djb2-like
// hash that's deterministic and collision-resistant enough for the
// few hundred records we'll ever see in a session.
function canonicalHash(obj: unknown): string {
  const json = JSON.stringify(obj, Object.keys(obj as object).sort());
  let h = 5381;
  for (let i = 0; i < json.length; i++) {
    h = ((h << 5) + h + json.charCodeAt(i)) | 0;
  }
  return `dh_${(h >>> 0).toString(16).padStart(8, "0")}`;
}

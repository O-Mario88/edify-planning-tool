// Core candidate derivation — Potential Core Candidates are DERIVED from the
// School Directory (not a separate mock): a Client school with an FY SSA whose
// average ≥ 7.5, not already Core, not archived. The live verification +
// onboarding overlay decorates each with its lifecycle status.

import "server-only";
import { SSA_INTERVENTION_AREAS } from "@/lib/intake/intake-core";
import { isBackendEnabled } from "@/lib/api/backend";
import { fetchCoreCandidates } from "@/lib/api/surfaces";
import type { BackendUser } from "@/lib/api/backend";
import { intakeSchools } from "@/lib/intake/intake-mock";
import {
  candidateSnapshotFor,
  verificationFor,
  onboardingFor,
  effectiveSchoolType,
} from "./core-store";
import { CORE_SSA_THRESHOLD, type CoreCandidate, type CoreCandidateStatus, type SsaInterventionArea } from "./core-types";

/** Next-October FY label for an onboarding recommendation. */
function nextOctoberFy(today = new Date()): string {
  // FY rolls on Oct 1; recommend the next FY start.
  const y = today.getMonth() >= 9 ? today.getFullYear() + 1 : today.getFullYear();
  return `FY ${y}/${String((y + 1) % 100).padStart(2, "0")}`;
}

function rankInterventions(scores: Partial<Record<SsaInterventionArea, number>>) {
  const rows = SSA_INTERVENTION_AREAS.map((a) => ({ area: a, score: scores[a] ?? 0 }));
  const best = [...rows].sort((a, b) => b.score - a.score).slice(0, 3);
  const weakest = [...rows].sort((a, b) => a.score - b.score).slice(0, 4);
  return { best, weakest };
}

function candidateStatusFor(schoolId: string): CoreCandidateStatus {
  if (effectiveSchoolType(schoolId) === "Core" || onboardingFor(schoolId)?.status === "Onboarded") {
    return "Onboarded as Core";
  }
  const v = verificationFor(schoolId);
  if (v) return v.status === "Rejected" ? "Rejected Candidate" : "Verified Potential Core";
  return "Candidate";
}

/** All potential core candidates derived from the directory + SSA snapshots. */
export function coreCandidates(): CoreCandidate[] {
  const out: CoreCandidate[] = [];
  for (const school of intakeSchools) {
    if (school.status !== "Active") continue;
    if (effectiveSchoolType(school.schoolId) === "Core") continue; // already core
    const snap = candidateSnapshotFor(school.schoolId);
    if (!snap || snap.average < CORE_SSA_THRESHOLD) continue;

    const { best, weakest } = rankInterventions(snap.scores);
    const v = verificationFor(school.schoolId);
    out.push({
      schoolId: school.schoolId,
      schoolName: school.schoolName,
      district: school.district,
      region: school.region,
      cluster: school.cluster,
      clusterId: school.clusterId,
      accountOwnerName: school.assignedCceo,
      enrollment: school.enrollment,
      currentSchoolType: school.schoolType,
      ssaRecordId: snap.id,
      fy: snap.fy,
      averageScore: snap.average,
      bestInterventions: best,
      weakestInterventions: weakest,
      candidateStatus: candidateStatusFor(school.schoolId),
      verificationId: v?.verificationId,
      recommendedOnboardingMonth: "October",
      recommendedOnboardingFy: nextOctoberFy(),
    });
  }
  return out.sort((a, b) => b.averageScore - a.averageScore);
}

export function coreCandidate(schoolId: string): CoreCandidate | undefined {
  return coreCandidates().find((c) => c.schoolId === schoolId);
}

/** Core Onboarding Queue — verified candidates not yet onboarded as Core. */
export function coreOnboardingQueue(): CoreCandidate[] {
  return coreCandidates().filter((c) => c.candidateStatus === "Verified Potential Core");
}

export function coreCandidateSummaryFrom(all: CoreCandidate[]) {
  return {
    total: all.length,
    candidate: all.filter((c) => c.candidateStatus === "Candidate").length,
    verified: all.filter((c) => c.candidateStatus === "Verified Potential Core").length,
    rejected: all.filter((c) => c.candidateStatus === "Rejected Candidate").length,
  };
}

/** Backend-first candidate list; mock only when backend is off. */
export async function resolveCoreCandidates(user: BackendUser): Promise<CoreCandidate[]> {
  if (isBackendEnabled()) {
    const r = await fetchCoreCandidates(user);
    if (r.live && Array.isArray(r.data)) return r.data as CoreCandidate[];
    return [];
  }
  return coreCandidates();
}

export async function resolveCoreOnboardingQueue(user: BackendUser): Promise<CoreCandidate[]> {
  const all = await resolveCoreCandidates(user);
  return all.filter((c) => c.candidateStatus === "Verified Potential Core");
}

export async function resolveCoreCandidateSummary(user: BackendUser) {
  return coreCandidateSummaryFrom(await resolveCoreCandidates(user));
}

export function coreCandidateSummary() {
  return coreCandidateSummaryFrom(coreCandidates());
}

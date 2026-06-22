import "server-only";

// Backend-derived planning gaps — the SchoolGapsBoard's REAL data source.
// Maps the role-scoped /planning/setup buckets (real backend schools, real
// business schoolIds) into the board's SchoolGap shape, so the board lists
// actual schools and scheduling from it writes straight to the backend.
// Returns null when the backend is disabled (caller keeps the mock).

import { fetchPlanningSetup, type BePlanningSchool, type BeWeakestArea } from "@/lib/api/surfaces";
import { isBackendEnabled, type BackendUser } from "@/lib/api/backend";
import type { SchoolGap, SsaInterventionArea } from "./planning-gaps-mock";

// Setup bucket → the board's client-school gap category. (Core schools have
// their own tab, so coreSchoolPlanning is intentionally excluded here.)
const BUCKET_TO_GAP: Record<string, { gapCategory: SchoolGap["gapCategory"]; risk: SchoolGap["riskLevel"]; ssaDone: boolean; clustered: boolean }> = {
  notYetClustered: { gapCategory: "no_cluster", risk: "High", ssaDone: false, clustered: false },
  clusteredSsaRequired: { gapCategory: "no_ssa", risk: "Critical", ssaDone: false, clustered: true },
  sitScheduledSsaMissing: { gapCategory: "no_ssa", risk: "High", ssaDone: false, clustered: true },
  readyToPlan: { gapCategory: "no_visit", risk: "Medium", ssaDone: true, clustered: true },
};

// Backend SSA intervention enum → the board's display union. Keyed on the
// canonical enum value (not the backend label) so copy differences
// ("Christ-like" vs "Christlike", "& Compliance") never break the mapping.
const INTERVENTION_TO_AREA: Record<string, SsaInterventionArea> = {
  teaching_and_learning: "Teaching & Learning",
  financial_health: "Financial Health",
  christlike_behaviour: "Christlike Behaviour",
  exposure_to_word_of_god: "Exposure to the Word of God",
  government_requirements: "Government Requirements & Compliance",
  leadership: "Leadership",
  education_technology: "Education Technology",
  learning_environment: "Learning Environment",
};

function toWeakArea(w?: BeWeakestArea): { area: SsaInterventionArea; score: number } | undefined {
  if (!w) return undefined;
  const area = INTERVENTION_TO_AREA[w.intervention];
  return area ? { area, score: w.score } : undefined;
}

function mapSchoolGaps(r: Awaited<ReturnType<typeof fetchPlanningSetup>>): SchoolGap[] {
  if (!r.live) return [];
  const gaps: SchoolGap[] = [];
  for (const bucket of r.data) {
    const meta = BUCKET_TO_GAP[bucket.key];
    if (!meta) continue;
    for (const s of bucket.items as unknown as BePlanningSchool[]) {
      const weak = s.weakest ?? [];
      gaps.push({
        id: s.schoolId,
        schoolName: s.name,
        district: "",
        subCounty: s.subCounty ?? "",
        assignedCceo: s.owner ?? "—",
        ssaCompleted: meta.ssaDone,
        inCluster: meta.clustered,
        riskLevel: meta.risk,
        gapCategory: meta.gapCategory,
        weakestArea: toWeakArea(weak[0]),
        secondWeakArea: toWeakArea(weak[1]),
      });
    }
  }
  return gaps;
}

export type BackendSchoolGapsResult = { gaps: SchoolGap[] | null; error: string | null };

/** Full fetch result — use when the caller must distinguish offline from empty. */
export async function fetchBackendSchoolGaps(user: BackendUser): Promise<BackendSchoolGapsResult> {
  if (!isBackendEnabled()) return { gaps: null, error: null };
  const r = await fetchPlanningSetup(user, "");
  if (!r.live) return { gaps: null, error: r.error ?? "Backend unreachable" };
  return { gaps: mapSchoolGaps(r), error: null };
}

export async function backendSchoolGaps(user: BackendUser): Promise<SchoolGap[] | null> {
  const { gaps } = await fetchBackendSchoolGaps(user);
  return gaps;
}

import "server-only";

// Backend-derived planning gaps — the SchoolGapsBoard's REAL data source.
// Maps the role-scoped /planning/setup buckets (real backend schools, real
// business schoolIds) into the board's SchoolGap shape, so the board lists
// actual schools and scheduling from it writes straight to the backend.
// Returns null when the backend is disabled (caller keeps the mock).

import { fetchPlanningSetup, type BePlanningSchool } from "@/lib/api/surfaces";
import { isBackendEnabled, type BackendUser } from "@/lib/api/backend";
import type { SchoolGap } from "./planning-gaps-mock";

// Setup bucket → the board's client-school gap category. (Core schools have
// their own tab, so coreSchoolPlanning is intentionally excluded here.)
const BUCKET_TO_GAP: Record<string, { gapCategory: SchoolGap["gapCategory"]; risk: SchoolGap["riskLevel"]; ssaDone: boolean; clustered: boolean }> = {
  notYetClustered: { gapCategory: "no_cluster", risk: "High", ssaDone: false, clustered: false },
  clusteredSsaRequired: { gapCategory: "no_ssa", risk: "Critical", ssaDone: false, clustered: true },
  sitScheduledSsaMissing: { gapCategory: "no_ssa", risk: "High", ssaDone: false, clustered: true },
  readyToPlan: { gapCategory: "no_visit", risk: "Medium", ssaDone: true, clustered: true },
};

export async function backendSchoolGaps(user: BackendUser): Promise<SchoolGap[] | null> {
  if (!isBackendEnabled()) return null;
  const r = await fetchPlanningSetup(user, "");
  if (!r.live) return null;

  const gaps: SchoolGap[] = [];
  for (const bucket of r.data) {
    const meta = BUCKET_TO_GAP[bucket.key];
    if (!meta) continue; // skip coreSchoolPlanning (own tab) etc.
    for (const s of bucket.items as unknown as BePlanningSchool[]) {
      gaps.push({
        id: s.schoolId, // REAL business schoolId → live writer resolves it
        schoolName: s.name,
        district: "",
        subCounty: s.subCounty ?? "",
        assignedCceo: s.owner ?? "—",
        ssaCompleted: meta.ssaDone,
        inCluster: meta.clustered,
        riskLevel: meta.risk,
        gapCategory: meta.gapCategory,
      });
    }
  }
  return gaps;
}

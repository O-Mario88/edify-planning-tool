import "server-only";

// Backend-derived CORE-school planning gaps — feeds the Core Schools tab the
// SAME detail-rich SchoolGap rows as the Client Schools tab, so core + client
// planning look and behave identically (schedule a visit / assign to a partner,
// straight to My Plan). Reads the role-scoped /planning/setup coreSchoolPlanning
// bucket (real schools, real business schoolIds). Returns null when the backend
// is off (caller keeps the mock CorePlanningAccordion).

import { fetchPlanningSetup, type BePlanningSchool } from "@/lib/api/surfaces";
import { isBackendEnabled, type BackendUser } from "@/lib/api/backend";
import type { SchoolGap } from "./planning-gaps-mock";

export async function backendCoreSchoolGaps(user: BackendUser): Promise<SchoolGap[] | null> {
  if (!isBackendEnabled()) return null;
  const r = await fetchPlanningSetup(user, "");
  if (!r.live) return null;

  const bucket = r.data.find((b) => b.key === "coreSchoolPlanning");
  if (!bucket) return [];

  const gaps: SchoolGap[] = [];
  for (const s of bucket.items as unknown as BePlanningSchool[]) {
    gaps.push({
      id: s.schoolId, // REAL business schoolId → live writer resolves it
      schoolName: s.name,
      district: "",
      subCounty: s.subCounty ?? "",
      assignedCceo: s.owner ?? "—",
      ssaCompleted: true, // core schools are post-SSA, ready to plan
      inCluster: true,
      riskLevel: "Medium",
      gapCategory: "no_visit",
    });
  }
  return gaps;
}

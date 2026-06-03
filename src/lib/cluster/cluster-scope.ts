// Per-viewer cluster counts — the one helper role dashboards use to render the
// ClusterReadinessCard. Scopes intake schools to the viewer's supervision chain
// (CD / RVP / Admin / IA see everything), then counts cluster status.
//
// Keeps the scoping logic in one place so every dashboard shows the same number
// as the Clusters hub and the Cluster Assignment Workspace.

import type { EdifyRole } from "@/lib/auth";
import { intakeSchools } from "@/lib/intake/intake-mock";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { visibleStaffIds } from "@/lib/org/supervision";
import { clusterCountsFor, type ClusterCounts } from "./cluster-core";

export function scopedClusterCounts(staffId: string, role: EdifyRole): ClusterCounts {
  const seesAll = role === "Admin" || role === "CountryDirector" || role === "RVP" || role === "ImpactAssessment";
  const scope = seesAll ? null : visibleStaffIds(staffId, role);
  const schools = intakeSchools.filter((s) => {
    if (seesAll) return true;
    const r = resolveOwner(s.assignedCceo);
    // Keep schools we can't place (unmatched owner) so they're never hidden.
    return r.status === "matched" ? scope!.has(r.staffId) : true;
  });
  return clusterCountsFor(schools);
}

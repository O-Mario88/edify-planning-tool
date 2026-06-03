import { TitleRegister } from "@/components/shell/TitleRegister";
import {
  ClusterAssignmentWorkspace,
  type WorkspaceSchool,
  type WorkspaceCluster,
} from "@/components/cluster/ClusterAssignmentWorkspace";
import { getCurrentUser } from "@/lib/auth";
import {
  unclusteredSchools,
  activeClusters,
  schoolsInCluster,
  recommendClusterFor,
} from "@/lib/cluster/cluster-core";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { visibleStaffIds } from "@/lib/org/supervision";
import { openDuplicateCandidates } from "@/lib/intake/duplicate-candidates-mock";

// Cluster Assignment Workspace — the operational page immediately after upload.
// Server-computed so runtime uploads + assignments show on refresh, scoped to
// the viewer's supervision chain (CD / RVP / Admin / IA see everything).
export default async function ClusterAssignmentPage() {
  const user = await getCurrentUser();

  const seesAll =
    user.role === "Admin" ||
    user.role === "CountryDirector" ||
    user.role === "RVP" ||
    user.role === "ImpactAssessment";
  const scope = seesAll ? null : visibleStaffIds(user.staffId, user.role);

  const dupeIds = new Set(openDuplicateCandidates().map((d) => d.schoolId));

  const schools: WorkspaceSchool[] = unclusteredSchools()
    .filter((s) => {
      if (seesAll) return true;
      const r = resolveOwner(s.assignedCceo);
      // Keep schools we can't place (unmatched owner) so they're never hidden.
      return r.status === "matched" ? scope!.has(r.staffId) : true;
    })
    .map((s) => {
      const rec = recommendClusterFor(s);
      return {
        schoolId: s.schoolId,
        schoolName: s.schoolName,
        region: s.region,
        district: s.district,
        subCounty: s.subCounty,
        schoolType: s.schoolType,
        assignedCceo: s.assignedCceo,
        ssaStatus: s.ssaStatus,
        duplicate: dupeIds.has(s.schoolId),
        recommendation:
          rec.kind === "existing" ? `Recommended: ${rec.cluster.name} — ${rec.reason}` : rec.reason,
      };
    });

  const clusters: WorkspaceCluster[] = activeClusters().map((c) => ({
    id: c.id,
    name: c.name,
    district: c.district,
    subCounty: c.subCounty,
    schoolCount: schoolsInCluster(c.id).length,
  }));

  return (
    <>
      <TitleRegister title="Cluster Assignment" dateLabel="Setup" />
      <ClusterAssignmentWorkspace schools={schools} clusters={clusters} />
    </>
  );
}

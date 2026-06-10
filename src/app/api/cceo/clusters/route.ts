// GET /api/cceo/clusters — cluster-meeting recommendations for the clusters
// containing the viewer's portfolio schools (weakest interventions become
// the next meeting's discussion topics). Same engine as the cluster cards:
// clusterMeetingRecommendationsForSchools(directoryRecords(...)).
// ?fy=/?week=/?month= are ignored (recommendations are current-state).

import { requireCceo, ok, type NextAction } from "../_auth";
import { directoryRecords } from "@/lib/school-directory/directory";
import { clusterMeetingRecommendationsForSchools } from "@/lib/cluster/cluster-meeting-recommendations";

export const dynamic = "force-dynamic";

export async function GET() {
  const g = await requireCceo();
  if (g.error) return g.error;
  const { user } = g;

  const schools = directoryRecords(user.staffId, user.role);
  const recommendations = clusterMeetingRecommendationsForSchools(schools);

  const nextActions: NextAction[] = recommendations
    .filter((r) => !r.nextMeeting && r.weakest.length > 0)
    .slice(0, 3)
    .map((r) => ({
      label: `Schedule cluster meeting — ${r.clusterName}`,
      reason: `Weakest area: ${r.weakest[0].area} (avg ${r.weakest[0].average.toFixed(1)}/10) and no next meeting on the books.`,
      href: "/clusters",
    }));

  return ok(
    { count: recommendations.length, recommendations },
    nextActions,
  );
}

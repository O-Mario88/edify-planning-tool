import "server-only";

// Backend-derived cluster gaps — the ClusterGapsBoard's REAL data source.
// Maps /clusters/planning (real clusters, real meeting-slot status derived from
// real cluster activities) into the board's ClusterGap shape, so the board lists
// actual clusters and scheduling from it writes straight to the backend.
// Returns null when the backend is disabled (caller keeps the mock engine).

import { fetchClusterPlanning } from "@/lib/api/surfaces";
import { isBackendEnabled, type BackendUser } from "@/lib/api/backend";
import type { ClusterGap, ClusterMeetingStatus } from "./planning-gaps-mock";

export async function backendClusterGaps(user: BackendUser): Promise<ClusterGap[] | null> {
  if (!isBackendEnabled()) return null;
  const r = await fetchClusterPlanning(user);
  if (!r.live) return null;

  return r.data.map((c) => ({
    id: c.id, // real cluster cuid → live writer resolves it
    clusterName: c.clusterName,
    district: c.district,
    schoolsCount: c.schoolsCount,
    schoolsWithSsa: c.schoolsWithSsa,
    assignedCceo: "—",
    schoolImprovementTraining: c.sit as ClusterMeetingStatus,
    firstMeeting: c.firstMeeting as ClusterMeetingStatus,
    secondMeeting: c.secondMeeting as ClusterMeetingStatus,
    thirdMeeting: c.thirdMeeting as ClusterMeetingStatus,
    gapCategory: c.gapCategory,
  }));
}

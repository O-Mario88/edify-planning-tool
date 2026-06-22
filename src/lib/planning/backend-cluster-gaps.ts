import "server-only";

// Backend-derived cluster gaps — the ClusterGapsBoard's REAL data source.
// Maps /clusters/planning (real clusters, real meeting-slot status derived from
// real cluster activities) into the board's ClusterGap shape, so the board lists
// actual clusters and scheduling from it writes straight to the backend.
// Returns null when the backend is disabled (caller keeps the mock engine).

import { fetchClusterPlanning } from "@/lib/api/surfaces";
import { isBackendEnabled, type BackendUser } from "@/lib/api/backend";
import type { ClusterGap, ClusterMeetingStatus } from "./planning-gaps-mock";

export type BackendClusterGapsResult = { gaps: ClusterGap[] | null; error: string | null };

function mapClusterGaps(r: Awaited<ReturnType<typeof fetchClusterPlanning>>): ClusterGap[] {
  if (!r.live) return [];
  return r.data.map((c) => ({
    id: c.id,
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

/** Full fetch result — use when the caller must distinguish offline from empty. */
export async function fetchBackendClusterGaps(user: BackendUser): Promise<BackendClusterGapsResult> {
  if (!isBackendEnabled()) return { gaps: null, error: null };
  const r = await fetchClusterPlanning(user);
  if (!r.live) return { gaps: null, error: r.error ?? "Backend unreachable" };
  return { gaps: mapClusterGaps(r), error: null };
}

export async function backendClusterGaps(user: BackendUser): Promise<ClusterGap[] | null> {
  const { gaps } = await fetchBackendClusterGaps(user);
  return gaps;
}

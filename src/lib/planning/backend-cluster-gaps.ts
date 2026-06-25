import "server-only";

// Backend-derived cluster gaps — the ClusterGapsBoard's REAL data source.
// Maps /clusters/planning (real clusters, real OPEN-ENDED cadence + SSA +
// coverage signals from the intelligence engine) into the board's
// ClusterGap shape. No 3-meeting cap — backend may return clusters with 0,
// 1, 3, 5, or 10+ completed meetings. Returns null when the backend is
// disabled (caller keeps the mock engine).

import { fetchClusterPlanning } from "@/lib/api/surfaces";
import { isBackendEnabled, type BackendUser } from "@/lib/api/backend";
import type { ClusterGap } from "./planning-gaps-mock";
import type {
  ClusterGapCategory,
  ClusterRecommendation,
} from "@/lib/cluster/cluster-intelligence";
import type { SsaInterventionArea } from "./planning-gaps-mock";

export type BackendClusterGapsResult = { gaps: ClusterGap[] | null; error: string | null };

/** Map a raw backend recommendation category string to the enum. The
 *  backend already produces the canonical key — this is a runtime guard
 *  against drift. */
function safeCategory(raw: string | undefined): ClusterGapCategory {
  const allowed: ClusterGapCategory[] = [
    "no_meetings_this_fy",
    "not_met_this_quarter",
    "schools_need_support",
    "weak_ssa_intervention",
    "ssa_performance_drop",
    "schools_not_visited",
    "schools_not_trained",
    "schools_neither_visit_nor_training",
    "training_needed",
    "follow_up_needed",
    "meeting_due",
    "on_track",
  ];
  return (allowed.includes(raw as ClusterGapCategory) ? raw : "on_track") as ClusterGapCategory;
}

function mapClusterGaps(r: Awaited<ReturnType<typeof fetchClusterPlanning>>): ClusterGap[] {
  if (!r.live) return [];
  return r.data.map((c): ClusterGap => {
    const category = safeCategory(c.gapCategory);
    // Reconstruct the recommendation object from the flat fields the
    // backend sends. The intelligence engine is the source of truth — we
    // don't recompute on the FE, we just unwrap.
    const recommendation: ClusterRecommendation | undefined = c.recommendationHeadline
      ? {
          priority:
            category === "ssa_performance_drop" ? "ssa_drop" :
            category === "weak_ssa_intervention" ? "weak_intervention" :
            category === "schools_not_visited" ? "schools_not_visited" :
            category === "schools_not_trained" ? "schools_not_trained" :
            category === "schools_neither_visit_nor_training" ? "schools_neither" :
            category === "no_meetings_this_fy" ? "no_meetings_this_fy" :
            category === "not_met_this_quarter" ? "no_meeting_this_quarter" :
            "on_track",
          suggestedActivity:
            category === "ssa_performance_drop" || category === "weak_ssa_intervention" ||
            category === "schools_not_trained" || category === "training_needed"
              ? "training"
              : category === "schools_neither_visit_nor_training" || category === "schools_not_visited"
                ? "support_visit"
                : category === "on_track"
                  ? "review"
                  : "meeting",
          suggestedActivityLabel: c.recommendationActivityLabel ?? "Schedule Cluster Activity",
          headline: c.recommendationHeadline,
          reason: c.recommendationReason ?? "",
          schoolsAffected: c.schoolsNeitherVisitNorTraining || c.schoolsNotTrained || c.schoolsNotVisited || c.schoolsCount,
          focusIntervention: (c.recommendationFocusIntervention as SsaInterventionArea | null) ?? undefined,
        }
      : undefined;

    return {
      id: c.id,
      clusterName: c.clusterName,
      district: c.district,
      schoolsCount: c.schoolsCount,
      schoolsWithSsa: c.schoolsWithSsa,
      assignedCceo: "—",
      meetingsThisFy: c.meetingsThisFy,
      meetingsScheduledThisFy: c.meetingsScheduledThisFy,
      trainingsThisFy: c.trainingsThisFy,
      lastMeetingDate: c.lastMeetingDate ?? undefined,
      nextScheduledMeetingDate: c.nextScheduledMeetingDate ?? undefined,
      metThisQuarter: c.metThisQuarter,
      schoolsNotVisited: c.schoolsNotVisited,
      schoolsNotTrained: c.schoolsNotTrained,
      schoolsNeitherVisitNorTraining: c.schoolsNeitherVisitNorTraining,
      gapCategory: category,
      recommendation,
    };
  });
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

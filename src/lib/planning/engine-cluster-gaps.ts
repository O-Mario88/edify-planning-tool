// Engine → planning cluster gaps.
//
// Bridges the real cluster engine (activeClusters + their unlimited
// scheduled/completed meetings) through `computeClusterIntelligence` into
// the `ClusterGap` shape the planning Cluster Gaps board renders. This is
// what makes the board reflect real cluster cadence + SSA + coverage — no
// hardcoded 3-meeting model, no "1st/2nd/3rd meeting" slots.

import {
  activeClusters,
  meetingsForCluster,
  schoolsInCluster,
  type ClusterMeeting,
} from "@/lib/cluster/cluster-core";
import { historyFor } from "@/lib/planning/ssa-performance-mock";
import {
  computeClusterIntelligence,
  type ClusterIntelActivity,
  type ClusterIntelSchool,
} from "@/lib/cluster/cluster-intelligence";
import type {
  ClusterGap,
  ClusterMeetingStatus,
  SsaInterventionArea,
} from "./planning-gaps-mock";

/** Map an activity's lifecycle status to the OPEN-ENDED 3-state vocabulary
 *  the intelligence engine consumes. The board still renders a richer
 *  per-chip status (Scheduled / Rescheduled / Awaiting IA / etc.) for
 *  individual already-scheduled meetings — that's separate from the
 *  cadence count this maps to. */
function intelStatusOf(a: ClusterMeeting): "Completed" | "Scheduled" | "Other" {
  if (a.status === "IA Confirmed" || a.status === "Paid" || a.status === "Closed") return "Completed";
  if (a.status === "Scheduled" || a.status === "Awaiting IA") return "Scheduled";
  return "Other";
}

/** Map an activity kind to the intelligence engine's activity type. */
function intelActivityType(kind: ClusterMeeting["kind"]): ClusterIntelActivity["activityType"] {
  if (kind === "sit") return "school_improvement_training";
  if (kind === "training" || kind === "cluster_training") return "cluster_training";
  if (kind === "follow_up") return "follow_up";
  // first_meeting, second_meeting, third_meeting all collapse to the
  // generic cluster_meeting — the ordinal label is informational only.
  return "cluster_meeting";
}

/** Legacy slot status — kept ONLY so the reschedule drawer can still
 *  surface in-flight meetings tagged with an ordinal slot. New meetings
 *  scheduled through the open-ended drawer don't get a slot. */
function legacyStatusOf(a: ClusterMeeting | undefined): ClusterMeetingStatus | undefined {
  if (!a) return undefined;
  if (a.status === "IA Confirmed" || a.status === "Paid" || a.status === "Closed") return "Completed";
  if (a.status === "Returned") return "Rescheduled";
  return "Scheduled";
}

export function engineClusterGaps(): ClusterGap[] {
  return activeClusters().map((c) => {
    const meetings = meetingsForCluster(c.id);
    const schools = schoolsInCluster(c.id);
    const schoolsWithSsa = schools.filter((s) => s.ssaStatus === "SSA Done").length;

    // Build intelligence inputs. The cluster-core in-memory store only
    // tracks coarse SSA status per school; we enrich with per-intervention
    // current/previous scores from ssa-performance-mock when available so
    // the intelligence engine can compute deltas + the recommendation.
    const intelSchools: ClusterIntelSchool[] = schools.map((s) => {
      const hist = historyFor(s.schoolId);
      const curr = hist[0];
      const prev = hist[1];
      const currScores: Partial<Record<SsaInterventionArea, number>> | undefined = curr
        ? Object.fromEntries(curr.scores.map((sc) => [sc.intervention, sc.score])) as Partial<Record<SsaInterventionArea, number>>
        : undefined;
      const prevScores: Partial<Record<SsaInterventionArea, number>> | undefined = prev
        ? Object.fromEntries(prev.scores.map((sc) => [sc.intervention, sc.score])) as Partial<Record<SsaInterventionArea, number>>
        : undefined;
      // Coverage: the in-memory store doesn't track per-school visit/training
      // attendance directly. Approximate from the cluster's activity list:
      // any IA-confirmed cluster training or visit in the FY counts the
      // school as trained/visited. (The backend-derived gaps replace this
      // with a real per-school join.)
      const hasCompletedTraining = meetings.some(
        (m) => (m.kind === "sit" || m.kind === "training" || m.kind === "cluster_training") &&
               (m.status === "IA Confirmed" || m.status === "Paid" || m.status === "Closed"),
      );
      const hasCompletedMeeting = meetings.some(
        (m) => m.kind !== "sit" && m.kind !== "training" && m.kind !== "cluster_training" &&
               (m.status === "IA Confirmed" || m.status === "Paid" || m.status === "Closed"),
      );
      return {
        schoolId: s.schoolId,
        schoolName: s.schoolName,
        schoolType: s.schoolType === "Core" ? "Core" : "Client",
        hasCurrentFySsa: s.ssaStatus === "SSA Done",
        currentSsa: currScores,
        previousSsa: prevScores,
        visitedThisPeriod: hasCompletedMeeting,   // cluster meetings double as visits
        trainedThisPeriod: hasCompletedTraining,
      };
    });

    const intelActivities: ClusterIntelActivity[] = meetings.map((m) => ({
      id: m.id,
      activityType: intelActivityType(m.kind),
      date: m.date,
      status: intelStatusOf(m),
      teachersTrained: m.teachersCount,
      schoolLeadersTrained: m.schoolLeadersCount,
    }));

    const intel = computeClusterIntelligence({
      schools: intelSchools,
      activities: intelActivities,
    });

    // Find the most-recent legacy-tagged activity for each ordinal slot so
    // the reschedule drawer can still operate on in-flight meetings that
    // were scheduled under the old model.
    const findKind = (kind: ClusterMeeting["kind"]): ClusterMeeting | undefined =>
      [...meetings].reverse().find((m) => m.kind === kind);
    const sitA = findKind("sit");
    const firstA = findKind("first_meeting");
    const secondA = findKind("second_meeting");
    const thirdA = findKind("third_meeting");

    return {
      id: c.id,
      clusterName: c.name,
      district: c.district,
      schoolsCount: schools.length,
      schoolsWithSsa,
      assignedCceo: c.clusterLeaderName ?? c.createdBy,
      partnerFacilitator: c.managedByPartnerName,

      // Open-ended cadence (from the intelligence engine)
      meetingsThisFy: intel.cadence.meetingsThisFy,
      meetingsScheduledThisFy: intel.cadence.meetingsScheduledThisFy,
      trainingsThisFy: intel.cadence.trainingsThisFy,
      lastMeetingDate: intel.cadence.lastMeetingDate,
      nextScheduledMeetingDate: intel.cadence.nextScheduledDate,
      metThisQuarter: intel.cadence.metThisQuarter,
      schoolsNotVisited: intel.coverage.notVisited.length,
      schoolsNotTrained: intel.coverage.notTrained.length,
      schoolsNeitherVisitNorTraining: intel.coverage.neitherVisitNorTraining.length,

      gapCategory: intel.gapCategory,
      recommendation: intel.recommendation,

      // Legacy slot fields — populated only when an ordinal-tagged meeting
      // exists, so the reschedule drawer can still operate on it.
      firstMeeting: legacyStatusOf(firstA),
      secondMeeting: legacyStatusOf(secondA),
      thirdMeeting: legacyStatusOf(thirdA),
      schoolImprovementTraining: legacyStatusOf(sitA),
      firstMeetingDate: firstA?.date,
      firstMeetingProposedBy: firstA?.scheduledBy,
      secondMeetingDate: secondA?.date,
      secondMeetingProposedBy: secondA?.scheduledBy,
      thirdMeetingDate: thirdA?.date,
      thirdMeetingProposedBy: thirdA?.scheduledBy,
      sitDate: sitA?.date,
      sitProposedBy: sitA?.scheduledBy,
    };
  });
}

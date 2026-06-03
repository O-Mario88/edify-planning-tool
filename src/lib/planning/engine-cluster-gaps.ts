// Engine → planning cluster gaps.
//
// Bridges the real cluster engine (activeClusters + their scheduled/completed
// meetings) into the ClusterGap shape the planning Cluster Gaps board renders.
// This is what makes "completing a real cluster meeting reduces a planning gap"
// true: the board now reflects engine truth, not a static mock.

import {
  activeClusters,
  meetingsForCluster,
  schoolsInCluster,
  type ClusterMeeting,
  type ClusterMeetingKind,
} from "@/lib/cluster/cluster-core";
import type { ClusterGap, ClusterMeetingStatus, ClusterGapCategory } from "./planning-gaps-mock";

/** Map an activity's lifecycle status to the board's meeting-status vocabulary. */
function statusOf(a: ClusterMeeting | undefined): ClusterMeetingStatus | null {
  if (!a) return null;
  if (a.status === "IA Confirmed" || a.status === "Paid") return "Completed";
  if (a.status === "Returned") return "Rescheduled";
  return "Scheduled"; // Scheduled / Awaiting IA
}

function findKind(meetings: ClusterMeeting[], kind: ClusterMeetingKind): ClusterMeeting | undefined {
  // The most recent activity of this kind (meetings are date-sorted asc).
  return [...meetings].reverse().find((m) => m.kind === kind);
}

export function engineClusterGaps(): ClusterGap[] {
  return activeClusters().map((c) => {
    const meetings = meetingsForCluster(c.id);
    const schools = schoolsInCluster(c.id);
    const schoolsWithSsa = schools.filter((s) => s.ssaStatus === "SSA Done").length;

    const sitA = findKind(meetings, "sit");
    const firstA = findKind(meetings, "first_meeting");
    const secondA = findKind(meetings, "second_meeting");
    const thirdA = findKind(meetings, "third_meeting");

    const sit: ClusterMeetingStatus = statusOf(sitA) ?? "Missing";
    const first: ClusterMeetingStatus = statusOf(firstA) ?? "Missing";
    // Later meetings aren't "due" until the prior one is completed.
    const second: ClusterMeetingStatus = first === "Completed" ? (statusOf(secondA) ?? "Missing") : "Not Yet Due";
    const third: ClusterMeetingStatus = second === "Completed" ? (statusOf(thirdA) ?? "Missing") : "Not Yet Due";

    // First outstanding gap drives the bucket (SIT first, then meetings in order).
    const gapCategory: ClusterGapCategory =
      sit === "Missing" ? "no_sit"
      : first === "Missing" ? "no_first_meeting"
      : second === "Missing" ? "no_second_meeting"
      : third === "Missing" ? "no_third_meeting"
      : "no_third_meeting";

    return {
      id: c.id,
      clusterName: c.name,
      district: c.district,
      schoolsCount: schools.length,
      schoolsWithSsa,
      assignedCceo: c.clusterLeaderName ?? c.createdBy,
      partnerFacilitator: c.managedByPartnerName,
      firstMeeting: first,
      secondMeeting: second,
      thirdMeeting: third,
      schoolImprovementTraining: sit,
      gapCategory,
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

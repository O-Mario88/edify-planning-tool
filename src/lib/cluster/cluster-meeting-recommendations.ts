// Cluster meeting recommendations — SSA-guided coaching topics per cluster.
//
// The PL spec rule: cluster meetings are guided by SSA averages. For each
// cluster, average all 8 canonical interventions across attached schools,
// take the two weakest, and recommend a discussion topic for each — with
// the reason and the schools affected, so "schedule a cluster meeting"
// is a decision, not a guess.
//
// Sources (all existing engines — no new numbers invented):
//   • cluster-core.ts                     → clusters, schools-in-cluster, meetings
//   • intervention-recommendation.ts      → per-school canonical SSA scores
//   • portfolio/resolveOwner              → scoping clusters to a PL's team
//
// Backend seam: GET /api/pl/cluster-recommendations returns this shape.

import {
  activeClusters,
  schoolsInCluster,
  clusterMeetings,
  CLUSTER_MEETING_LABEL,
  type ClusterRecord,
} from "@/lib/cluster/cluster-core";
import type { IntakeSchool } from "@/lib/intake/intake-mock";
import { recommendInterventionsForSchool } from "@/lib/planning/intervention-recommendation";
import { SSA_INTERVENTIONS } from "@/lib/planning/ssa-performance-mock";
import type { SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";
import { resolveOwner } from "@/lib/portfolio/portfolio";
import { cceosSupervisedBy } from "@/lib/org/supervision";

/** Canonical intervention → recommended cluster discussion topic. */
export const CLUSTER_DISCUSSION_TOPICS: Record<SsaInterventionArea, string> = {
  "Leadership":
    "Strengthening school leadership routines, supervision, teacher accountability, and decision-making.",
  "Teaching & Learning":
    "Improving classroom practice, teacher preparation, and learner engagement.",
  "Christlike Behaviour":
    "Modelling Christ-like character — discipline approaches, staff conduct, and learner formation.",
  "Exposure to the Word of God":
    "Strengthening devotions, chapel, Bible integration, and spiritual life across the school week.",
  "Financial Health":
    "Fees collection discipline, budgeting routines, transparent accounts, and financial planning.",
  "Government Requirements & Compliance":
    "Meeting registration, safety, sanitation, and statutory compliance standards together.",
  "Learning Environment":
    "Creating safe, orderly, print-rich classrooms and improving learning materials.",
  "Education Technology":
    "Practical EdTech adoption — devices, digital content, and teacher confidence with technology.",
};

export type WeakestIntervention = {
  area: SsaInterventionArea;
  /** Cluster average for this intervention (/10, 1dp). */
  average: number;
  topic: string;
  reason: string;
  /** Schools in the cluster scoring below Good (7) on this intervention. */
  schoolsAffected: number;
};

export type ClusterMeetingRecommendation = {
  clusterId: string;
  clusterName: string;
  district: string;
  subCounty?: string;
  managedByPartnerName?: string;
  schools: number;
  schoolsWithSsa: number;
  schoolsMissingSsa: number;
  /** Cluster overall SSA average (/10), null when no school has SSA. */
  overallAverage: number | null;
  /** The two weakest interventions, weakest first. Empty without SSA data. */
  weakest: WeakestIntervention[];
  /** Next scheduled (not yet completed) meeting, if any. */
  nextMeeting?: { kind: string; date: string };
};

function nextMeetingFor(clusterId: string): { kind: string; date: string } | undefined {
  const upcoming = clusterMeetings
    .filter((m) => m.clusterId === clusterId && m.status === "Scheduled")
    .sort((a, b) => (a.date < b.date ? -1 : 1))[0];
  return upcoming
    ? { kind: CLUSTER_MEETING_LABEL[upcoming.kind], date: upcoming.date }
    : undefined;
}

function recommendForCluster(cluster: ClusterRecord): ClusterMeetingRecommendation {
  const schools = schoolsInCluster(cluster.id);
  const perSchool = schools
    .map((s) => recommendInterventionsForSchool(s.schoolId))
    .filter((r) => r.hasSsa);

  // Average each canonical intervention across the cluster's scored schools.
  const sums = new Map<SsaInterventionArea, { sum: number; n: number; below: number }>();
  for (const rec of perSchool) {
    for (const r of rec.all) {
      const cur = sums.get(r.intervention) ?? { sum: 0, n: 0, below: 0 };
      cur.sum += r.score;
      cur.n += 1;
      if (r.score < 7) cur.below += 1;
      sums.set(r.intervention, cur);
    }
  }

  const averages = SSA_INTERVENTIONS.flatMap((area) => {
    const s = sums.get(area);
    if (!s || s.n === 0) return [];
    return [{ area, average: Math.round((s.sum / s.n) * 10) / 10, below: s.below }];
  }).sort((a, b) => a.average - b.average);

  const weakest: WeakestIntervention[] = averages.slice(0, 2).map((w) => ({
    area: w.area,
    average: w.average,
    topic: CLUSTER_DISCUSSION_TOPICS[w.area],
    reason: `Cluster average ${w.average.toFixed(1)}/10 across ${perSchool.length} scored schools — the weakest of the 8 interventions.`,
    schoolsAffected: w.below,
  }));

  const overall =
    averages.length > 0
      ? Math.round((averages.reduce((a, x) => a + x.average, 0) / averages.length) * 10) / 10
      : null;

  return {
    clusterId: cluster.id,
    clusterName: cluster.name,
    district: cluster.district,
    subCounty: cluster.subCounty,
    managedByPartnerName: cluster.managedByPartnerName,
    schools: schools.length,
    schoolsWithSsa: perSchool.length,
    schoolsMissingSsa: schools.length - perSchool.length,
    overallAverage: overall,
    weakest,
    nextMeeting: nextMeetingFor(cluster.id),
  };
}

/**
 * Recommendations for every active cluster, weakest cluster first.
 * Pass a PL staffId to scope to clusters containing at least one school
 * owned by that PL's supervised CCEOs (the PL's team geography).
 */
export function clusterMeetingRecommendations(plStaffId?: string): ClusterMeetingRecommendation[] {
  let pool = activeClusters();

  if (plStaffId) {
    const teamIds = new Set(cceosSupervisedBy(plStaffId).map((s) => s.staffId));
    if (teamIds.size > 0) {
      const scoped = pool.filter((c) =>
        schoolsInCluster(c.id).some((s) => {
          const owner = resolveOwner(s.assignedCceo);
          return owner.status === "matched" && teamIds.has(owner.staffId);
        }),
      );
      // Demo seeds don't always link every cluster to the PL's roster —
      // fall back to the full directory rather than an empty board.
      if (scoped.length > 0) pool = scoped;
    }
  }

  return pool
    .map(recommendForCluster)
    .sort((a, b) => (a.overallAverage ?? 11) - (b.overallAverage ?? 11));
}

/**
 * Recommendations scoped to the clusters CONTAINING the given schools — the
 * CCEO "my clusters / parish fellowship" view (pass the viewer's portfolio
 * from directoryRecords). Demo seeds don't always carry clusterIds yet, so
 * when none of the schools is clustered we fall back to active clusters in
 * the schools' districts (the CCEO's geography) rather than an empty board.
 */
export function clusterMeetingRecommendationsForSchools(
  schools: IntakeSchool[],
): ClusterMeetingRecommendation[] {
  const myClusterIds = new Set(
    schools.map((s) => s.clusterId).filter((id): id is string => !!id),
  );
  let pool = activeClusters().filter((c) => myClusterIds.has(c.id));
  if (pool.length === 0 && schools.length > 0) {
    const districts = new Set(schools.map((s) => s.district.trim().toLowerCase()));
    pool = activeClusters().filter((c) => districts.has(c.district.trim().toLowerCase()));
  }
  return pool
    .map(recommendForCluster)
    .sort((a, b) => (a.overallAverage ?? 11) - (b.overallAverage ?? 11));
}

// Cluster activity, performance & investment mock — drives the
// ClusterActivityProfileDrawer ("View Cluster"). Aggregates from the
// existing single-source data: clusterGaps + schoolGaps +
// ssa-performance-mock + school-activity-mock. Nothing here is
// independently authored; the cluster summary is *derived* so all
// drawers stay perfectly consistent.
//
// Pure client-safe module. Salesforce migration swaps the underlying
// fetchers; every helper below stays the same.

import {
  schoolGaps, CLUSTER_MEETING_SLOT_LABEL,
  type ClusterGap, type SchoolGap, type ClusterMeetingStatus, type ClusterMeetingSlot,
} from "@/lib/planning/planning-gaps-mock";
import {
  historyFor, snapshotFor, statusFor,
  SSA_INTERVENTIONS,
  type SsaStatus,
  type SsaPerformanceRecord,
} from "@/lib/planning/ssa-performance-mock";
import {
  buildSchoolActivitySummary,
  isInCurrentCycle,
  CURRENT_CYCLE,
  type SchoolActivityTimelineItem,
  type SummaryScope,
  type EvidenceStatus,
} from "@/lib/planning/school-activity-mock";

// ────────── Types ──────────

export type ClusterMeetingSummary = {
  id:                  string;
  meetingType:         ClusterMeetingSlot;
  meetingLabel:        string;
  status:              ClusterMeetingStatus;
  scheduledDate?:      string;
  completedDate?:      string;
  participants?:       number;
  schoolsRepresented?: number;
  facilitator?:        string;
  evidenceStatus:      EvidenceStatus;
  cost:                number;
};

export type ClusterTrainingType =
  | "school_improvement_training"
  | "teaching_learning"
  | "leadership"
  | "financial_health"
  | "learning_environment"
  | "compliance"
  | "education_technology"
  | "christlike_behaviour"
  | "word_of_god"
  | "other";

export type ClusterTrainingSummary = {
  id:                 string;
  trainingType:       ClusterTrainingType;
  trainingTitle:      string;
  intervention:       string;
  date:               string;
  facilitator?:       string;
  partnerFacilitator?: string;
  participants:       number;
  schoolsRepresented: number;
  evidenceStatus:     EvidenceStatus;
  cost:               number;
  followUpRequiredSchools?: number;
};

export type ClusterInterventionCoverage = {
  intervention:   string;
  trainingsHeld:  number;
  schoolsReached: number;
  latestTraining?: string;
};

export type ClusterSsaPerformance = {
  /** Per-intervention average across cluster member schools. */
  averages: { intervention: string; score: number; status: SsaStatus }[];
  weakestIntervention?:   { intervention: string; score: number };
  strongestIntervention?: { intervention: string; score: number };
  /** School-by-school SSA snapshot. */
  schools: {
    schoolId:        string;
    schoolName:      string;
    averageSsaScore: number;
    weakestArea?:    string;
    status:          SsaStatus;
  }[];
  /** Year-over-year cluster averages if multiple cycles present. */
  yearlyAverages?: { year: string; average: number }[];
};

export type ClusterSchoolPotential = {
  potentialCoreSchools: {
    schoolId:        string;
    schoolName:      string;
    averageSsaScore: number;
    improvement:     number;
    reasons:         string[];
    recommendedAction: string;
  }[];
  potentialChampionSchools: {
    schoolId:                string;
    schoolName:              string;
    averageSsaScore:         number;
    lowestInterventionScore: number;
    improvement:             number;
    reasons:                 string[];
    recommendedAction:       string;
  }[];
};

export type ClusterCostBreakdown = {
  meetingCost:          number;
  trainingCost:         number;
  partnerFacilitationCost: number;
  staffVisitCost:       number;
  ssaCost:              number;
  resourceProjectCost:  number;
  otherCost:            number;
  totalSpent:           number;
};

export type ClusterEvidenceSummary = {
  complete:                 number;
  missing:                  number;
  awaitingCceoConfirmation: number;
  verifiedByME:             number;
  returnedForCorrection:    number;
  perActivity: {
    id:                 string;
    title:              string;
    evidenceStatus:     EvidenceStatus;
    verificationStatus: string;
  }[];
};

export type ClusterNextAction = {
  title:    string;
  reason:   string;
  ctaLabel: string;
  /** Maps to the cluster gap action handler so callers re-use existing
   *  flows (schedule_first / schedule_sit / etc.). */
  action?:  "schedule_first" | "schedule_second" | "schedule_third" | "schedule_sit"
          | "schedule_ssa" | "schedule_training" | "review_core" | "review_champion";
  /** When action is a school upgrade, schoolId pins which one. */
  schoolId?: string;
};

export type ClusterActivityInvestmentSummary = {
  clusterId:        string;
  clusterName:      string;
  district:         string;
  subCounty?:       string;
  assignedCceo:     string;
  partnerFacilitator?: string;
  operationalCycle: string;
  /** Member schools of the cluster (intersected with schoolGaps). */
  memberSchools:    SchoolGap[];
  totals: {
    schoolsInCluster:         number;
    meetingsHeld:             number;
    meetingsScheduled:        number;
    trainingsHeld:            number;
    ssaCompleted:             number;
    corePotentialSchools:     number;
    championPotentialSchools: number;
    totalSpent:               number;
  };
  meetings:        ClusterMeetingSummary[];
  trainings:       ClusterTrainingSummary[];
  interventionCoverage: ClusterInterventionCoverage[];
  ssaPerformance:  ClusterSsaPerformance;
  schoolPotential: ClusterSchoolPotential;
  costBreakdown:   ClusterCostBreakdown;
  evidenceSummary: ClusterEvidenceSummary;
  /** 0-100 composite. See computeClusterHealth() for the breakdown. */
  healthScore:     number;
  healthBreakdown: { strong: string[]; needsAttention: string[] };
  nextActions:     ClusterNextAction[];
};

// ────────── Categorisation helpers ──────────

function inferTrainingType(intervention?: string): ClusterTrainingType {
  if (!intervention) return "school_improvement_training";
  const i = intervention.toLowerCase();
  if (i.includes("teaching"))         return "teaching_learning";
  if (i.includes("leadership"))       return "leadership";
  if (i.includes("financial"))        return "financial_health";
  if (i.includes("learning environment")) return "learning_environment";
  if (i.includes("compliance") || i.includes("government")) return "compliance";
  if (i.includes("education technology") || i.includes("technology")) return "education_technology";
  if (i.includes("christlike"))       return "christlike_behaviour";
  if (i.includes("word of god"))      return "word_of_god";
  return "school_improvement_training";
}

// ────────── Member-school discovery ──────────

/**
 * Schools belonging to the cluster, by name. The mock encodes
 * membership via SchoolGap.clusterName; the production fetcher will
 * use a real cluster_id FK.
 */
export function memberSchoolsFor(cluster: ClusterGap): SchoolGap[] {
  return schoolGaps.filter((s) => s.clusterName === cluster.clusterName);
}

// ────────── Main summary builder ──────────

export function buildClusterActivitySummary(
  cluster: ClusterGap,
  scope: SummaryScope = "current_cycle",
): ClusterActivityInvestmentSummary {
  const member = memberSchoolsFor(cluster);

  // Aggregate every member school's activity timeline. We rebuild
  // the school summary in the same scope so cycle-vs-all-time stays
  // consistent across both drawers.
  const perSchoolSummaries = member.map((s) =>
    buildSchoolActivitySummary(
      {
        schoolId: s.id, schoolName: s.schoolName,
        district: s.district, subCounty: s.subCounty, parish: s.parish, clusterName: s.clusterName,
      },
      scope,
    ),
  );
  const allItems = perSchoolSummaries.flatMap((s) => s.timeline);

  // ───── Meetings ─────
  const meetings = buildMeetings(cluster, allItems, scope);

  // ───── Trainings ─────
  const trainings = buildTrainings(allItems);

  // ───── Intervention coverage ─────
  const interventionCoverage = buildInterventionCoverage(trainings);

  // ───── SSA performance ─────
  const ssaPerformance = buildSsaPerformance(member);

  // ───── School potential ─────
  const schoolPotential = buildSchoolPotential(member);

  // ───── Cost breakdown ─────
  const costBreakdown = buildCostBreakdown(allItems, meetings);

  // ───── Evidence summary ─────
  const evidenceSummary = buildEvidenceSummary(allItems, meetings);

  // ───── Totals ─────
  const totals = {
    schoolsInCluster:         member.length,
    meetingsHeld:             meetings.filter((m) => m.status === "Completed").length,
    meetingsScheduled:        meetings.filter((m) => m.status === "Scheduled" || m.status === "Rescheduled").length,
    trainingsHeld:            trainings.length,
    ssaCompleted:             member.filter((s) => s.ssaCompleted).length,
    corePotentialSchools:     schoolPotential.potentialCoreSchools.length,
    championPotentialSchools: schoolPotential.potentialChampionSchools.length,
    totalSpent:               costBreakdown.totalSpent,
  };

  // ───── Health score + breakdown ─────
  const { healthScore, healthBreakdown } = computeClusterHealth({
    meetings, trainings, member, ssaPerformance, schoolPotential,
  });

  // ───── Next actions ─────
  const nextActions = buildNextActions({
    cluster, member, meetings, ssaPerformance, schoolPotential,
  });

  return {
    clusterId:           cluster.id,
    clusterName:         cluster.clusterName,
    district:            cluster.district,
    subCounty:           undefined, // cluster gap doesn't carry this yet
    assignedCceo:        cluster.assignedCceo,
    partnerFacilitator:  cluster.partnerFacilitator,
    operationalCycle:    CURRENT_CYCLE,
    memberSchools:       member,
    totals,
    meetings,
    trainings,
    interventionCoverage,
    ssaPerformance,
    schoolPotential,
    costBreakdown,
    evidenceSummary,
    healthScore,
    healthBreakdown,
    nextActions,
  };
}

// ────────── Builders ──────────

function buildMeetings(
  cluster: ClusterGap,
  allItems: SchoolActivityTimelineItem[],
  scope: SummaryScope,
): ClusterMeetingSummary[] {
  const slots: ClusterMeetingSlot[] = ["first", "second", "third", "sit"];
  return slots.map((slot) => {
    const status = (
      slot === "first"  ? cluster.firstMeeting  :
      slot === "second" ? cluster.secondMeeting :
      slot === "third"  ? cluster.thirdMeeting  :
                          cluster.schoolImprovementTraining
    );
    const scheduledDate = (
      slot === "first"  ? cluster.firstMeetingDate  :
      slot === "second" ? cluster.secondMeetingDate :
      slot === "third"  ? cluster.thirdMeetingDate  :
                          cluster.sitDate
    );
    const facilitator = (
      slot === "sit"
        ? (cluster.partnerFacilitator ?? cluster.assignedCceo)
        : cluster.assignedCceo
    );
    // Cost rollup — for completed meetings, take the costAllocationTotal
    // from the FIRST allocated school item (every member sees the same
    // total via allocation maths). Falls back to 0 when no item exists.
    const matchingItem = allItems.find((a) =>
      a.activityType === (slot === "sit" ? "school_improvement_training" : "cluster_meeting")
      && (scope === "current_cycle" ? isInCurrentCycle(a.date) : true)
    );
    const cost = matchingItem?.costAllocationTotal ?? (matchingItem?.cost ?? 0) * (matchingItem?.costAllocationSchoolCount ?? 1);
    return {
      id:             `${cluster.id}-${slot}`,
      meetingType:    slot,
      meetingLabel:   CLUSTER_MEETING_SLOT_LABEL[slot],
      status,
      scheduledDate,
      completedDate:  status === "Completed" ? scheduledDate : undefined,
      participants:   matchingItem ? estimateParticipants(matchingItem) : undefined,
      schoolsRepresented: matchingItem?.costAllocationSchoolCount,
      facilitator,
      evidenceStatus: matchingItem?.evidenceStatus ?? "not_required",
      cost,
    };
  });
}

function estimateParticipants(item: SchoolActivityTimelineItem): number {
  // Mock: rough estimate at 5 participants per school the activity covered.
  return (item.costAllocationSchoolCount ?? 1) * 5;
}

function buildTrainings(allItems: SchoolActivityTimelineItem[]): ClusterTrainingSummary[] {
  // Group SIT/training items across the cluster's member schools. The
  // mock authors them per-school; here we de-dupe by (title + date) so
  // a multi-school training appears once.
  const grouped = new Map<string, SchoolActivityTimelineItem[]>();
  for (const a of allItems) {
    if (a.activityType !== "school_improvement_training" && a.activityType !== "training") continue;
    const key = `${a.title}::${a.date}`;
    const arr = grouped.get(key) ?? [];
    arr.push(a);
    grouped.set(key, arr);
  }
  return Array.from(grouped.entries()).map(([key, items]) => {
    const first = items[0];
    const schoolsRepresented = new Set(items.map((i) => i.schoolId)).size;
    const totalCost = first.costAllocated && first.costAllocationTotal
      ? first.costAllocationTotal
      : items.reduce((sum, i) => sum + i.cost, 0);
    return {
      id:                  `TR-${key}`,
      trainingType:        inferTrainingType(first.ssaInterventionAddressed),
      trainingTitle:       first.title,
      intervention:        first.ssaInterventionAddressed ?? "General improvement",
      date:                first.date,
      facilitator:         first.deliveredByRole === "Partner" ? undefined : first.deliveredByName,
      partnerFacilitator:  first.deliveredByRole === "Partner" ? (first.partnerName ?? first.deliveredByName) : undefined,
      participants:        items.reduce((sum, i) => sum + estimateParticipants(i), 0) || schoolsRepresented * 5,
      schoolsRepresented,
      evidenceStatus:      first.evidenceStatus,
      cost:                totalCost,
      followUpRequiredSchools: first.nextAction ? Math.min(schoolsRepresented, 3) : undefined,
    };
  }).sort((a, b) => b.date.localeCompare(a.date));
}

function buildInterventionCoverage(trainings: ClusterTrainingSummary[]): ClusterInterventionCoverage[] {
  // Always render the full canonical intervention list, even when 0
  // trainings have happened — that gap is exactly what the CCEO/PL
  // wants to see.
  const byIntervention = new Map<string, ClusterTrainingSummary[]>();
  for (const t of trainings) {
    const i = t.intervention;
    const arr = byIntervention.get(i) ?? [];
    arr.push(t);
    byIntervention.set(i, arr);
  }
  return SSA_INTERVENTIONS.map((intervention) => {
    const matches = byIntervention.get(intervention) ?? [];
    const schoolsReached = new Set(matches.flatMap((m) => Array.from({ length: m.schoolsRepresented }, (_, i) => `${m.id}:${i}`))).size;
    const latestTraining = matches.map((m) => m.date).sort().reverse()[0];
    return {
      intervention,
      trainingsHeld:  matches.length,
      schoolsReached: matches.reduce((sum, m) => sum + m.schoolsRepresented, 0) || schoolsReached,
      latestTraining,
    };
  });
}

function buildSsaPerformance(member: SchoolGap[]): ClusterSsaPerformance {
  // Per-school current SSA snapshots.
  const schoolSnaps = member.map((s) => {
    const hist = historyFor(s.id);
    const curr = hist[0];
    if (!curr) {
      return { schoolId: s.id, schoolName: s.schoolName, averageSsaScore: 0, weakestArea: undefined, status: "Critical" as SsaStatus, scoresByArea: new Map<string, number>(), hasCurrent: false };
    }
    const snap = snapshotFor(curr);
    const byArea = new Map<string, number>(curr.scores.map((sc) => [sc.intervention, sc.score]));
    return {
      schoolId: s.id, schoolName: s.schoolName,
      averageSsaScore: curr.averageScore,
      weakestArea: snap.weakest.intervention,
      status: curr.status,
      scoresByArea: byArea,
      hasCurrent: true,
    };
  });

  // Per-intervention averages across schools that completed SSA.
  const withSsa = schoolSnaps.filter((s) => s.hasCurrent);
  const averages = SSA_INTERVENTIONS.map((intervention) => {
    const scores = withSsa.map((s) => s.scoresByArea.get(intervention)).filter((v): v is number => v !== undefined);
    if (scores.length === 0) return { intervention, score: 0, status: "Critical" as SsaStatus };
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length;
    return { intervention, score: round1(avg), status: statusFor(avg) };
  });
  const ranked = [...averages].filter((a) => a.score > 0).sort((a, b) => a.score - b.score);
  const weakestIntervention   = ranked[0] ? { intervention: ranked[0].intervention, score: ranked[0].score } : undefined;
  const strongestIntervention = ranked[ranked.length - 1] ? { intervention: ranked[ranked.length - 1].intervention, score: ranked[ranked.length - 1].score } : undefined;

  // Yearly cluster averages — derived from each school's history.
  const yearMap = new Map<string, number[]>();
  for (const s of member) {
    for (const h of historyFor(s.id)) {
      const arr = yearMap.get(h.operationalCycle) ?? [];
      arr.push(h.averageScore);
      yearMap.set(h.operationalCycle, arr);
    }
  }
  const yearlyAverages = Array.from(yearMap.entries())
    .map(([year, arr]) => ({ year, average: round1(arr.reduce((a, b) => a + b, 0) / arr.length) }))
    .sort((a, b) => a.year.localeCompare(b.year));

  return {
    averages,
    weakestIntervention,
    strongestIntervention,
    schools: schoolSnaps.map((s) => ({
      schoolId: s.schoolId, schoolName: s.schoolName,
      averageSsaScore: s.averageSsaScore,
      weakestArea: s.weakestArea,
      status: s.status,
    })).sort((a, b) => a.averageSsaScore - b.averageSsaScore),
    yearlyAverages: yearlyAverages.length >= 2 ? yearlyAverages : undefined,
  };
}

function buildSchoolPotential(member: SchoolGap[]): ClusterSchoolPotential {
  const potentialCoreSchools: ClusterSchoolPotential["potentialCoreSchools"] = [];
  const potentialChampionSchools: ClusterSchoolPotential["potentialChampionSchools"] = [];

  for (const s of member) {
    if (!s.ssaCompleted) continue;
    const hist = historyFor(s.id);
    const curr = hist[0];
    if (!curr) continue;
    const prev = hist[1];
    const snap = snapshotFor(curr);
    const improvement = prev ? round1(curr.averageScore - prev.averageScore) : 0;
    const leadershipScore = curr.scores.find((sc) => sc.intervention === "Leadership")?.score ?? 0;

    // Core potential — avg ≥6 OR improving ≥+1.5, leadership ≥6.
    if ((curr.averageScore >= 6 || improvement >= 1.5) && leadershipScore >= 6) {
      const reasons: string[] = [];
      if (curr.averageScore >= 6) reasons.push(`Average SSA ${curr.averageScore.toFixed(1)}/10 — at or above core threshold.`);
      if (improvement >= 1.5)     reasons.push(`Improved +${improvement.toFixed(1)} since ${prev?.operationalCycle ?? "baseline"}.`);
      if (leadershipScore >= 6)   reasons.push(`Leadership at ${leadershipScore}/10 — sustained engagement.`);
      potentialCoreSchools.push({
        schoolId:         s.id,
        schoolName:       s.schoolName,
        averageSsaScore:  curr.averageScore,
        improvement,
        reasons,
        recommendedAction: "Review for Core School upgrade.",
      });
    }

    // Champion potential — avg ≥8, no intervention below 7, improved
    // or sustained, teaching & learning + leadership both strong.
    const lowest = Math.min(...curr.scores.map((sc) => sc.score));
    const teaching = curr.scores.find((sc) => sc.intervention === "Teaching & Learning")?.score ?? 0;
    if (curr.averageScore >= 8 && lowest >= 7 && teaching >= 7 && leadershipScore >= 7) {
      const reasons: string[] = [];
      reasons.push(`Average SSA ${curr.averageScore.toFixed(1)}/10.`);
      reasons.push(`Lowest intervention ${lowest}/10 — no weak areas.`);
      if (improvement >= 0) reasons.push("Performance sustained across cycles.");
      potentialChampionSchools.push({
        schoolId:                s.id,
        schoolName:              s.schoolName,
        averageSsaScore:         curr.averageScore,
        lowestInterventionScore: lowest,
        improvement,
        reasons,
        recommendedAction: "Review for Champion school status.",
      });
    }

    // Suppress unused-snap warning when no branch fired.
    void snap;
  }

  return { potentialCoreSchools, potentialChampionSchools };
}

function buildCostBreakdown(
  allItems: SchoolActivityTimelineItem[],
  meetings: ClusterMeetingSummary[],
): ClusterCostBreakdown {
  // Meeting cost — from the per-slot rollup so we don't double-count
  // the allocation share that already appears on each school's items.
  const meetingCost = meetings
    .filter((m) => m.meetingType !== "sit")
    .reduce((sum, m) => sum + m.cost, 0);

  // SIT lives in the meetings array but is conceptually a training.
  const sitCost = meetings.find((m) => m.meetingType === "sit")?.cost ?? 0;

  // Other training cost — sum unique (title+date) trainings.
  const seen = new Set<string>();
  let trainingTotal = sitCost;
  let partnerFacilitationTotal = 0;
  for (const a of allItems) {
    if (a.activityType !== "school_improvement_training" && a.activityType !== "training") continue;
    const key = `${a.title}::${a.date}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const total = a.costAllocated && a.costAllocationTotal ? a.costAllocationTotal : a.cost;
    trainingTotal += total;
    if (a.deliveredByRole === "Partner") partnerFacilitationTotal += total;
  }

  const staffVisitCost = allItems
    .filter((a) => a.activityType === "staff_visit" || a.activityType === "coaching_visit"
      || a.activityType === "follow_up_visit" || a.activityType === "classroom_observation")
    .reduce((sum, a) => sum + a.cost, 0);
  const ssaCost = allItems.filter((a) => a.activityType === "ssa").reduce((sum, a) => sum + a.cost, 0);
  const resourceProjectCost = allItems
    .filter((a) => a.activityType === "resource_delivery" || a.activityType === "project")
    .reduce((sum, a) => sum + a.cost, 0);
  const otherCost = allItems.filter((a) => a.activityType === "partner_visit" || a.activityType === "other")
    .reduce((sum, a) => sum + a.cost, 0);

  const totalSpent = meetingCost + trainingTotal + staffVisitCost + ssaCost + resourceProjectCost + otherCost;

  return {
    meetingCost,
    trainingCost: trainingTotal,
    partnerFacilitationCost: partnerFacilitationTotal,
    staffVisitCost,
    ssaCost,
    resourceProjectCost,
    otherCost,
    totalSpent,
  };
}

function buildEvidenceSummary(
  allItems: SchoolActivityTimelineItem[],
  meetings: ClusterMeetingSummary[],
): ClusterEvidenceSummary {
  // Restrict to items that are cluster-relevant: cluster meetings,
  // trainings, and SIT.
  const relevant = allItems.filter((a) =>
    a.activityType === "cluster_meeting"
    || a.activityType === "school_improvement_training"
    || a.activityType === "training",
  );

  const seen = new Set<string>();
  const perActivity: ClusterEvidenceSummary["perActivity"] = [];
  for (const a of relevant) {
    const key = `${a.title}::${a.date}`;
    if (seen.has(key)) continue;
    seen.add(key);
    perActivity.push({
      id:                 key,
      title:              a.title,
      evidenceStatus:     a.evidenceStatus,
      verificationStatus: a.verificationStatus,
    });
  }

  const summary = {
    complete:                 perActivity.filter((a) => a.evidenceStatus === "complete" || a.evidenceStatus === "verified").length,
    missing:                  perActivity.filter((a) => a.evidenceStatus === "missing" || a.evidenceStatus === "partial").length,
    awaitingCceoConfirmation: perActivity.filter((a) => a.verificationStatus === "awaiting_review").length,
    verifiedByME:             perActivity.filter((a) => a.verificationStatus === "verified" || a.verificationStatus === "counted").length,
    returnedForCorrection:    perActivity.filter((a) => a.evidenceStatus === "returned" || a.verificationStatus === "rejected").length,
    perActivity,
  };

  // Suppress unused-meetings warning — the parameter is reserved for
  // future inclusion of meetings that have no school-side activity
  // record (currently every meeting appears via an allocated item).
  void meetings;

  return summary;
}

// ────────── Cluster health score ──────────

function computeClusterHealth(args: {
  meetings: ClusterMeetingSummary[];
  trainings: ClusterTrainingSummary[];
  member: SchoolGap[];
  ssaPerformance: ClusterSsaPerformance;
  schoolPotential: ClusterSchoolPotential;
}): { healthScore: number; healthBreakdown: { strong: string[]; needsAttention: string[] } } {
  const { meetings, trainings, member, ssaPerformance, schoolPotential } = args;

  const strong: string[] = [];
  const needsAttention: string[] = [];

  // Component scores (each 0-1).
  const meetingsExpected = meetings.filter((m) => m.meetingType !== "sit").length;
  const meetingsDone     = meetings.filter((m) => m.meetingType !== "sit" && m.status === "Completed").length;
  const meetingScore     = meetingsExpected > 0 ? meetingsDone / meetingsExpected : 0;
  if (meetingsDone >= 2)            strong.push(`${meetingsDone} of ${meetingsExpected} cluster meetings completed`);
  if (meetingsDone < meetingsExpected) needsAttention.push(`${meetingsExpected - meetingsDone} cluster meeting${meetingsExpected - meetingsDone === 1 ? "" : "s"} outstanding`);

  const trainingScore = trainings.length === 0 ? 0 : Math.min(1, trainings.length / 4);
  if (trainings.length >= 2) strong.push(`${trainings.length} trainings delivered`);

  const ssaCoverage = member.length === 0 ? 0 : member.filter((s) => s.ssaCompleted).length / member.length;
  if (ssaCoverage === 1)      strong.push("All schools have current SSA");
  else if (ssaCoverage < 0.75) needsAttention.push(`${member.filter((s) => !s.ssaCompleted).length} schools missing SSA`);

  // SSA cluster trend — improving by ≥+0.5 between any two adjacent years.
  let trendScore = 0.5;
  if (ssaPerformance.yearlyAverages && ssaPerformance.yearlyAverages.length >= 2) {
    const ya = ssaPerformance.yearlyAverages;
    const delta = ya[ya.length - 1].average - ya[ya.length - 2].average;
    trendScore = delta >= 0.5 ? 1 : delta >= 0 ? 0.7 : delta >= -0.5 ? 0.3 : 0;
    if (delta >= 0.5) strong.push(`Cluster SSA improving (+${delta.toFixed(1)} vs prior cycle)`);
    if (delta < 0)    needsAttention.push(`Cluster SSA declining ${delta.toFixed(1)} vs prior cycle`);
  }

  // Cluster weakest intervention <5 is a flag.
  if (ssaPerformance.weakestIntervention && ssaPerformance.weakestIntervention.score < 5) {
    needsAttention.push(`${ssaPerformance.weakestIntervention.intervention} averaging ${ssaPerformance.weakestIntervention.score}/10`);
  }
  if (ssaPerformance.strongestIntervention && ssaPerformance.strongestIntervention.score >= 8) {
    strong.push(`${ssaPerformance.strongestIntervention.intervention} averaging ${ssaPerformance.strongestIntervention.score}/10`);
  }

  // School pipeline.
  const pipelineScore = Math.min(1,
    (schoolPotential.potentialCoreSchools.length + schoolPotential.potentialChampionSchools.length) / Math.max(1, member.length / 3),
  );
  if (schoolPotential.potentialCoreSchools.length > 0)
    strong.push(`${schoolPotential.potentialCoreSchools.length} school${schoolPotential.potentialCoreSchools.length === 1 ? "" : "s"} ready for Core review`);
  if (schoolPotential.potentialChampionSchools.length > 0)
    strong.push(`${schoolPotential.potentialChampionSchools.length} school${schoolPotential.potentialChampionSchools.length === 1 ? "" : "s"} ready for Champion review`);

  // Weighted composite — meetings 20, trainings 15, SSA coverage 25,
  // trend 20, pipeline 20.
  const healthScore = Math.round(
    meetingScore * 20 +
    trainingScore * 15 +
    ssaCoverage * 25 +
    trendScore * 20 +
    pipelineScore * 20,
  );

  return { healthScore, healthBreakdown: { strong, needsAttention } };
}

// ────────── Next-actions engine ──────────

function buildNextActions(args: {
  cluster: ClusterGap;
  member: SchoolGap[];
  meetings: ClusterMeetingSummary[];
  ssaPerformance: ClusterSsaPerformance;
  schoolPotential: ClusterSchoolPotential;
}): ClusterNextAction[] {
  const { cluster, member, meetings, ssaPerformance, schoolPotential } = args;
  const out: ClusterNextAction[] = [];

  // Missing meetings — bubble up the next slot.
  const missingFirst  = meetings.find((m) => m.meetingType === "first"  && m.status === "Missing");
  const missingSecond = meetings.find((m) => m.meetingType === "second" && m.status === "Missing");
  const missingThird  = meetings.find((m) => m.meetingType === "third"  && m.status === "Missing");
  if (missingFirst) {
    out.push({ title: "Schedule first cluster meeting", reason: "First cluster meeting is missing — cluster cadence cannot start without it.", ctaLabel: "Schedule meeting", action: "schedule_first" });
  } else if (missingSecond) {
    out.push({ title: "Schedule second cluster meeting", reason: "First meeting completed; second meeting is missing.", ctaLabel: "Schedule meeting", action: "schedule_second" });
  } else if (missingThird) {
    out.push({ title: "Schedule third cluster meeting", reason: "First and second meetings completed; third meeting is missing.", ctaLabel: "Schedule meeting", action: "schedule_third" });
  }

  // Missing SIT.
  const sitMissing = meetings.find((m) => m.meetingType === "sit" && m.status === "Missing");
  if (sitMissing) {
    const noSsa = member.length - member.filter((s) => s.ssaCompleted).length;
    out.push({
      title:  "Schedule School Improvement Training",
      reason: noSsa > 0
        ? `SIT is missing. ${noSsa} schools need SSA first — they will be excluded from this training.`
        : "SIT is missing. All schools in the cluster have current SSA — training can proceed.",
      ctaLabel: "Schedule SIT",
      action:   "schedule_sit",
    });
  }

  // Weakest intervention training gap.
  const weak = ssaPerformance.weakestIntervention;
  if (weak && weak.score < 6) {
    out.push({
      title:  `Schedule ${weak.intervention} training`,
      reason: `Cluster average is ${weak.score}/10 — weakest intervention. Drive shared training.`,
      ctaLabel: "Schedule training",
      action:   "schedule_training",
    });
  }

  // SSA coverage gap.
  const noSsa = member.filter((s) => !s.ssaCompleted);
  if (noSsa.length > 0) {
    out.push({
      title:  `Complete SSA for ${noSsa.length} school${noSsa.length === 1 ? "" : "s"}`,
      reason: "Schools without current SSA cannot be included in cluster training planning.",
      ctaLabel: "View schools",
      action:   "schedule_ssa",
    });
  }

  // Core upgrade reviews.
  for (const c of schoolPotential.potentialCoreSchools.slice(0, 2)) {
    out.push({
      title:    `Review ${c.schoolName} for Core School upgrade`,
      reason:   c.reasons.join(" "),
      ctaLabel: "Review",
      action:   "review_core",
      schoolId: c.schoolId,
    });
  }
  // Champion upgrade reviews.
  for (const c of schoolPotential.potentialChampionSchools.slice(0, 2)) {
    out.push({
      title:    `Review ${c.schoolName} for Champion status`,
      reason:   c.reasons.join(" "),
      ctaLabel: "Review",
      action:   "review_champion",
      schoolId: c.schoolId,
    });
  }

  // Suppress unused-cluster warning if no actions branch.
  void cluster;

  return out;
}

// ────────── Tiny helpers ──────────

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

// Re-export status classifier so the drawer's pills can colour
// without yet another import path.
export { statusFor as ssaStatusFor };

// Re-export so the drawer can read the SSA record type without
// importing from ssa-performance-mock directly when it only needs
// the cluster surface.
export type { SsaPerformanceRecord };

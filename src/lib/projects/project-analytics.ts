// Project impact analytics (the deferred analytics block).
//
// Project impact = Reach + Verified Delivery + Intervention Improvement +
// Overall 8-intervention SSA + Donor-Ready. Rules: never count planned
// activities as impact; dedupe schools/learners; keep the project mapped to
// its SSA intervention; separate assigned / reached / verified / donor-ready.

import {
  projectById,
  schoolProjectMemberships,
  type SpecialProject,
} from "@/lib/special-projects-mock";
import { intakeSchools, type IntakeSchool } from "@/lib/intake/intake-mock";
import { SSA_INTERVENTIONS } from "@/lib/planning/ssa-performance-mock";
import type { SsaInterventionArea } from "@/lib/planning/planning-gaps-mock";
import { ssaForSchool } from "./project-school-ssa";
import { activitiesForProject, type ProjectActivity } from "./project-activities";
import type { FunnelStage, HeatmapRow, DrilldownRecord, DataQualityScore } from "@/lib/analytics/types";

export type ReachMetric = {
  /** assigned ⊇ reached ⊇ verified ⊇ donorReady */
  assigned: number;
  reached: number;
  verified: number;
  donorReady: number;
  records: DrilldownRecord[]; // assigned schools, flagged by furthest stage reached
};

export type ProjectAnalyticsSnapshot = {
  projectId: string;
  projectName: string;
  intervention: SsaInterventionArea;
  // Reach
  schools: ReachMetric;
  teachersTrained: { total: number; verified: number };
  schoolLeadersTrained: { total: number; verified: number };
  learners: { impacted: number; schoolsContributing: number; schoolsMissingEnrollment: number };
  districtsCovered: number;
  regionsCovered: number;
  clustersCovered: number;
  // Delivery
  delivery: {
    trainings: number;
    followUps: number;
    assessments: number;
    staffActivities: number;
    partnerActivities: number;
    evidenceVerified: number;
    iaConfirmed: number;
  };
  // Linked-intervention improvement
  improvement: {
    baselineAvg: number;
    latestAvg: number;
    change: number;
    improved: number;
    declined: number;
    noChange: number;
    noComparison: number;
  };
  // General 8-intervention SSA
  generalSsa: {
    interventions: string[];
    averages: Record<string, number | undefined>;
    best?: { intervention: string; score: number };
    worst?: { intervention: string; score: number };
    heatmap: HeatmapRow[]; // rows by district
    trend: { period: string; baseline: number; latest: number };
  };
  funnel: FunnelStage[];
  dataQuality: { score: DataQualityScore; warnings: string[] };
};

function rec(school: IntakeSchool, status: string, value?: number, contributes = true): DrilldownRecord {
  return {
    id: school.schoolId,
    entityType: "school",
    title: school.schoolName,
    subtitle: `${school.district}${school.cluster ? ` · ${school.cluster}` : ""}`,
    schoolId: school.schoolId,
    district: school.district,
    status,
    value,
    contributesToCount: contributes,
  };
}

const round1 = (n: number) => Math.round(n * 10) / 10;

export function computeProjectAnalytics(projectId: string): ProjectAnalyticsSnapshot | undefined {
  const project = projectById(projectId);
  if (!project) return undefined;
  const intervention = project.primaryInterventionId;

  const assignedIds = schoolProjectMemberships
    .filter((m) => m.projectId === projectId && m.status === "Active")
    .map((m) => m.schoolId);
  const schools = assignedIds
    .map((id) => intakeSchools.find((s) => s.schoolId === id))
    .filter((s): s is IntakeSchool => Boolean(s));

  const allActs = activitiesForProject(projectId);
  const actsBySchool = (id: string) => allActs.filter((a) => a.schoolId === id);
  const isCompleted = (a: ProjectActivity) => a.status === "Completed";

  // ── Reach (per-school furthest stage) ──
  const reachedSet = new Set<string>();
  const verifiedSet = new Set<string>();
  const donorSet = new Set<string>();
  for (const s of schools) {
    const acts = actsBySchool(s.schoolId);
    if (acts.some(isCompleted)) reachedSet.add(s.schoolId);
    if (acts.some((a) => a.iaVerificationStatus === "Confirmed")) verifiedSet.add(s.schoolId);
    if (acts.some((a) => a.iaVerificationStatus === "Confirmed" && a.salesforceActivityId && a.evidenceStatus === "Verified"))
      donorSet.add(s.schoolId);
  }
  const reachStatus = (id: string) =>
    donorSet.has(id) ? "Donor-ready" : verifiedSet.has(id) ? "Verified" : reachedSet.has(id) ? "Reached" : "Assigned (not reached)";
  const schoolsMetric: ReachMetric = {
    assigned: schools.length,
    reached: reachedSet.size,
    verified: verifiedSet.size,
    donorReady: donorSet.size,
    records: schools.map((s) => rec(s, reachStatus(s.schoolId), undefined, reachedSet.has(s.schoolId))),
  };

  // ── Teachers / leaders (completed trainings only) ──
  const completedTrainings = allActs.filter((a) => a.activityType === "Project Training" && isCompleted(a));
  const sumBy = (sel: (a: ProjectActivity) => number, filter: (a: ProjectActivity) => boolean) =>
    completedTrainings.filter(filter).reduce((acc, a) => acc + sel(a), 0);
  const teachersTrained = {
    total: sumBy((a) => a.teachersTrained ?? 0, () => true),
    verified: sumBy((a) => a.teachersTrained ?? 0, (a) => Boolean(a.attendanceVerified)),
  };
  const schoolLeadersTrained = {
    total: sumBy((a) => a.schoolLeadersTrained ?? 0, () => true),
    verified: sumBy((a) => a.schoolLeadersTrained ?? 0, (a) => Boolean(a.attendanceVerified)),
  };

  // ── Learners (unique reached schools' latest enrollment) ──
  const reachedSchools = schools.filter((s) => reachedSet.has(s.schoolId));
  const learners = {
    impacted: reachedSchools.reduce((a, s) => a + (s.enrollment ?? 0), 0),
    schoolsContributing: reachedSchools.filter((s) => s.enrollment != null).length,
    schoolsMissingEnrollment: reachedSchools.filter((s) => s.enrollment == null).length,
  };
  const districtsCovered = new Set(reachedSchools.map((s) => s.district)).size;
  const regionsCovered = new Set(reachedSchools.map((s) => s.region)).size;
  const clustersCovered = new Set(reachedSchools.map((s) => s.cluster).filter(Boolean)).size;

  // ── Delivery ──
  const completed = allActs.filter(isCompleted);
  const delivery = {
    trainings: completed.filter((a) => a.activityType === "Project Training").length,
    followUps: completed.filter((a) => a.activityType === "Project Follow-Up Visit").length,
    assessments: completed.filter((a) => a.activityType === "Project Assessment").length,
    staffActivities: completed.filter((a) => a.deliveryType === "staff").length,
    partnerActivities: completed.filter((a) => a.deliveryType === "partner").length,
    evidenceVerified: completed.filter((a) => a.evidenceStatus === "Verified").length,
    iaConfirmed: completed.filter((a) => a.iaVerificationStatus === "Confirmed").length,
  };

  // ── Linked-intervention improvement ──
  let improved = 0, declined = 0, noChange = 0, noComparison = 0;
  let bSum = 0, lSum = 0, bothN = 0;
  for (const s of schools) {
    const ssa = ssaForSchool(s.schoolId);
    const b = ssa?.baseline[intervention];
    const l = ssa?.current[intervention];
    if (b === undefined || l === undefined) { noComparison++; continue; }
    bSum += b; lSum += l; bothN++;
    if (l > b) improved++; else if (l < b) declined++; else noChange++;
  }
  const improvement = {
    baselineAvg: bothN ? round1(bSum / bothN) : 0,
    latestAvg: bothN ? round1(lSum / bothN) : 0,
    change: bothN ? round1((lSum - bSum) / bothN) : 0,
    improved, declined, noChange, noComparison,
  };

  // ── General 8-intervention SSA ──
  const ssaSchools = schools.map((s) => ssaForSchool(s.schoolId)).filter((x): x is NonNullable<typeof x> => Boolean(x));
  const averages: Record<string, number | undefined> = {};
  for (const area of SSA_INTERVENTIONS) {
    if (!ssaSchools.length) { averages[area] = undefined; continue; }
    averages[area] = round1(ssaSchools.reduce((a, r) => a + r.current[area], 0) / ssaSchools.length);
  }
  const scored = SSA_INTERVENTIONS.map((a) => ({ intervention: a as string, score: averages[a] }))
    .filter((x): x is { intervention: string; score: number } => x.score !== undefined);
  const best = scored.length ? scored.reduce((m, x) => (x.score > m.score ? x : m)) : undefined;
  const worst = scored.length ? scored.reduce((m, x) => (x.score < m.score ? x : m)) : undefined;

  // Heatmap rows by district (avg current score per intervention).
  const byDistrict = new Map<string, IntakeSchool[]>();
  for (const s of schools) {
    if (!ssaForSchool(s.schoolId)) continue;
    const list = byDistrict.get(s.district) ?? [];
    list.push(s); byDistrict.set(s.district, list);
  }
  const heatmap: HeatmapRow[] = [...byDistrict.entries()].map(([district, list]) => {
    const scores: Record<string, number | undefined> = {};
    for (const area of SSA_INTERVENTIONS) {
      const rs = list.map((s) => ssaForSchool(s.schoolId)!).map((r) => r.current[area]);
      scores[area] = rs.length ? round1(rs.reduce((a, b) => a + b, 0) / rs.length) : undefined;
    }
    return { key: district, label: district, scores };
  });
  const overallBaseline = ssaSchools.length
    ? round1(ssaSchools.reduce((a, r) => a + SSA_INTERVENTIONS.reduce((x, i) => x + r.baseline[i], 0) / 8, 0) / ssaSchools.length)
    : 0;
  const overallLatest = ssaSchools.length
    ? round1(ssaSchools.reduce((a, r) => a + SSA_INTERVENTIONS.reduce((x, i) => x + r.current[i], 0) / 8, 0) / ssaSchools.length)
    : 0;

  // ── Funnel ──
  const trainedSet = new Set(schools.filter((s) => actsBySchool(s.schoolId).some((a) => a.activityType === "Project Training" && isCompleted(a))).map((s) => s.schoolId));
  const followedSet = new Set(schools.filter((s) => actsBySchool(s.schoolId).some((a) => a.activityType === "Project Follow-Up Visit" && isCompleted(a))).map((s) => s.schoolId));
  const assessedSet = new Set(schools.filter((s) => actsBySchool(s.schoolId).some((a) => a.activityType === "Project Assessment" && isCompleted(a))).map((s) => s.schoolId));
  const improvedSet = new Set(schools.filter((s) => { const ssa = ssaForSchool(s.schoolId); return ssa && ssa.current[intervention] > ssa.baseline[intervention]; }).map((s) => s.schoolId));
  const stageRecords = (set: Set<string>, label: string) => schools.filter((s) => set.has(s.schoolId)).map((s) => rec(s, label));
  const funnel: FunnelStage[] = [
    { key: "assigned",  label: "Assigned",   count: schools.length,  records: schools.map((s) => rec(s, "Assigned")) },
    { key: "reached",   label: "Reached",    count: reachedSet.size,  records: stageRecords(reachedSet, "Reached") },
    { key: "trained",   label: "Trained",    count: trainedSet.size,  records: stageRecords(trainedSet, "Trained") },
    { key: "followed",  label: "Followed up", count: followedSet.size, records: stageRecords(followedSet, "Followed up") },
    { key: "assessed",  label: "Assessed",   count: assessedSet.size, records: stageRecords(assessedSet, "Assessed") },
    { key: "improved",  label: "Improved",   count: improvedSet.size, records: stageRecords(improvedSet, "Improved") },
  ];

  // ── Data quality ──
  const warnings: string[] = [];
  if (learners.schoolsMissingEnrollment > 0) warnings.push(`Learners impacted may be undercounted — ${learners.schoolsMissingEnrollment} reached school(s) missing enrollment.`);
  if (improvement.noComparison > 0) warnings.push(`${improvement.noComparison} school(s) missing baseline or latest SSA for ${intervention}.`);
  const missingSf = completed.filter((a) => !a.salesforceActivityId).length;
  if (missingSf > 0) warnings.push(`${missingSf} completed activity(ies) missing a Salesforce ID.`);
  const iaPending = completed.filter((a) => a.iaVerificationStatus !== "Confirmed").length;
  if (iaPending > 0) warnings.push(`${iaPending} completed activity(ies) not yet IA-confirmed.`);
  const attMissing = completedTrainings.filter((a) => a.teachersTrained == null).length;
  if (attMissing > 0) warnings.push(`${attMissing} completed training(s) missing attendance breakdown.`);
  const score: DataQualityScore =
    warnings.length === 0 ? "Excellent" : warnings.length <= 1 ? "Good" : warnings.length <= 3 ? "Needs Attention" : "Critical";

  return {
    projectId,
    projectName: project.projectName,
    intervention,
    schools: schoolsMetric,
    teachersTrained,
    schoolLeadersTrained,
    learners,
    districtsCovered,
    regionsCovered,
    clustersCovered,
    delivery,
    improvement,
    generalSsa: {
      interventions: [...SSA_INTERVENTIONS],
      averages,
      best,
      worst,
      heatmap,
      trend: { period: project.financialYear, baseline: overallBaseline, latest: overallLatest },
    },
    funnel,
    dataQuality: { score, warnings },
  };
}

export type { SpecialProject };

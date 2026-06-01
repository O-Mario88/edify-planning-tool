// The analytics truth-layer engine.
//
// computeAnalytics(input) → AnalyticsSnapshot computed from the workflow record
// mocks, scoped by FY-cycle tag + quarter + geography. Every metric carries its
// definition, planned/completed/verified/donor-ready breakdown, drilldown
// records, and a data-quality verdict. PURE & client-safe — the server page
// passes in an already-role-scoped record set; this never imports server-only
// modules.

import type { FilterSelection } from "@/lib/filters/types";
import { rawActivities, type SchoolActivityTimelineItem, ACTIVITY_TYPE_LABEL } from "@/lib/planning/school-activity-mock";
import { trainingParticipantMock } from "@/lib/analytics/sources/training-participant-mock";
import { latestEnrollmentFor } from "@/lib/analytics/sources/school-enrollment-history-mock";
import { examPerformanceMock } from "@/lib/analytics/sources/exam-performance-mock";
import { mscMock } from "@/lib/analytics/sources/msc-mock";
import { historyFor, SSA_INTERVENTIONS } from "@/lib/planning/ssa-performance-mock";
import { analyticsSchoolById } from "./school-directory";
import { isCompleted, isVerified, isDonorReady, isPaid } from "./status-maps";
import { selectedFyId, selectedCycleTag, selectedQuarterRange, schoolInGeoScope, dateInRange } from "./scope";
import { computePeriodTarget } from "@/lib/targets/period-target";
import { fyTargetForRole } from "@/lib/targets/role-targets";
import { engineNowIso } from "@/lib/clock";
import type {
  AnalyticsMetric, AnalyticsSnapshot, DrilldownRecord, FunnelStage, HeatmapRow, TrendPoint, DataQuality,
} from "./types";

export type ComputeInput = {
  selection: FilterSelection;
  /** Role used for the FY target (CCEO 560 / PL 280). */
  role?: string;
  scopeLabel?: string;
  now?: string;
};

const VERIFIED_TRAINING = new Set(["MeVerified", "CceoConfirmed"]);

function monthOf(iso: string): string {
  return iso.slice(0, 7);
}

export function computeAnalytics(input: ComputeInput): AnalyticsSnapshot {
  const now = input.now ?? engineNowIso();
  const { selection } = input;
  const fyId = selectedFyId(selection, now);
  const cycleTag = selectedCycleTag(selection, now);
  const qRange = selectedQuarterRange(selection, now);

  // ── Scope the record sets ──
  const acts = rawActivities.filter(
    (a) => a.operationalCycle === cycleTag && schoolInGeoScope(a.schoolId, selection) && dateInRange(a.date, qRange),
  );
  const participants = trainingParticipantMock.filter(
    (p) => p.fy === cycleTag && schoolInGeoScope(p.schoolId, selection) && dateInRange(p.date, qRange),
  );
  const exams = examPerformanceMock.filter(
    (e) => e.fy === cycleTag && schoolInGeoScope(e.schoolId, selection) && dateInRange(e.examDate, qRange),
  );
  const stories = mscMock.filter(
    (m) => m.fy === cycleTag && schoolInGeoScope(m.schoolId, selection) && dateInRange(m.submittedAt, qRange),
  );

  // ── Reach: distinct reached schools (activities ∪ verified trainings) ──
  type ReachAgg = { completed: boolean; verified: boolean; donorReady: boolean };
  const reach = new Map<string, ReachAgg>();
  const touch = (schoolId: string, patch: Partial<ReachAgg>) => {
    const cur = reach.get(schoolId) ?? { completed: false, verified: false, donorReady: false };
    reach.set(schoolId, { completed: cur.completed || !!patch.completed, verified: cur.verified || !!patch.verified, donorReady: cur.donorReady || !!patch.donorReady });
  };
  for (const a of acts) touch(a.schoolId, { completed: isCompleted(a), verified: isVerified(a), donorReady: isDonorReady(a) });
  for (const p of participants) {
    const v = VERIFIED_TRAINING.has(p.evidenceStatus);
    touch(p.schoolId, { completed: true, verified: v, donorReady: p.evidenceStatus === "MeVerified" });
  }

  const reachedIds = [...reach.keys()];
  const schoolRecord = (schoolId: string, note?: string): DrilldownRecord => {
    const s = analyticsSchoolById(schoolId);
    return {
      id: schoolId, entityType: "school",
      title: s?.schoolName ?? schoolId,
      subtitle: [s?.district, note].filter(Boolean).join(" · ") || undefined,
      schoolId, district: s?.district, contributesToCount: true,
    };
  };

  const reachBreakdown = {
    planned: reachedIds.length,
    completed: reachedIds.filter((id) => reach.get(id)!.completed).length,
    verified: reachedIds.filter((id) => reach.get(id)!.verified).length,
    donorReady: reachedIds.filter((id) => reach.get(id)!.donorReady).length,
  };

  // ── Learners impacted: latest enrollment over reached schools (dedup) ──
  let learners = 0;
  let missingEnrollment = 0;
  const learnerRecords: DrilldownRecord[] = [];
  for (const id of reachedIds) {
    const enr = latestEnrollmentFor(id);
    const s = analyticsSchoolById(id);
    if (enr) {
      learners += enr.enrollmentValue;
      learnerRecords.push({ id, entityType: "school", title: s?.schoolName ?? id, subtitle: `${enr.enrollmentValue} learners · ${enr.source} · ${enr.enrollmentDate}`, schoolId: id, district: s?.district, value: enr.enrollmentValue, contributesToCount: true });
    } else {
      missingEnrollment += 1;
      learnerRecords.push({ id, entityType: "school", title: s?.schoolName ?? id, subtitle: "No enrollment on record", schoolId: id, district: s?.district, contributesToCount: false });
    }
  }

  // ── Teachers / school leaders trained: dedup by identityKey ──
  const verifiedParticipants = participants.filter((p) => VERIFIED_TRAINING.has(p.evidenceStatus));
  const distinctByType = (type: string) => {
    const seen = new Map<string, (typeof verifiedParticipants)[number]>();
    for (const p of verifiedParticipants) if (p.participantType === type && !seen.has(p.identityKey)) seen.set(p.identityKey, p);
    return [...seen.values()];
  };
  const teachers = distinctByType("Teacher");
  const leaders = distinctByType("SchoolLeader");
  const participantRecords = (list: typeof verifiedParticipants): DrilldownRecord[] =>
    list.map((p) => ({ id: p.id, entityType: "training", title: p.participantName, subtitle: `${analyticsSchoolById(p.schoolId)?.schoolName ?? p.schoolId} · ${p.date}`, schoolId: p.schoolId, date: p.date, contributesToCount: true }));

  // ── Geography coverage ──
  const reachedSchools = reachedIds.map((id) => analyticsSchoolById(id)).filter(Boolean);
  const districts = [...new Set(reachedSchools.map((s) => s!.district))];
  const clusters = [...new Set(reachedSchools.map((s) => s!.clusterName).filter(Boolean) as string[])];

  // ── Activity pipeline funnel ──
  const stage = (key: string, label: string, pred: (a: SchoolActivityTimelineItem) => boolean): FunnelStage => {
    const rows = acts.filter(pred);
    return { key, label, count: rows.length, records: rows.map((a) => ({ id: a.id, entityType: "activity", title: a.title, subtitle: `${ACTIVITY_TYPE_LABEL[a.activityType]} · ${analyticsSchoolById(a.schoolId)?.schoolName ?? a.schoolId} · ${a.date}`, schoolId: a.schoolId, date: a.date, status: a.verificationStatus, contributesToCount: true })) };
  };
  const pipeline: FunnelStage[] = [
    stage("planned", "Planned", () => true),
    stage("completed", "Completed", isCompleted),
    stage("verified", "IA Verified", isVerified),
    stage("paid", "Paid", isPaid),
  ];

  // ── SSA: latest snapshot per reached school (state, not period-bound) ──
  const interventions = SSA_INTERVENTIONS as readonly string[];
  const latestSnaps = reachedIds
    .map((id) => historyFor(id)[0])
    .filter(Boolean);
  const areaTotals = new Map<string, { sum: number; n: number }>();
  for (const rec of latestSnaps) {
    for (const sc of rec.scores) {
      const t = areaTotals.get(sc.intervention) ?? { sum: 0, n: 0 };
      t.sum += sc.score; t.n += 1; areaTotals.set(sc.intervention, t);
    }
  }
  const areaAvg = (a: string): number | undefined => {
    const t = areaTotals.get(a);
    return t && t.n > 0 ? Math.round((t.sum / t.n) * 10) / 10 : undefined;
  };
  const scoredAreas = interventions.map((a) => ({ a, v: areaAvg(a) })).filter((x) => x.v !== undefined) as { a: string; v: number }[];
  const best = scoredAreas.slice().sort((x, y) => y.v - x.v)[0];
  const worst = scoredAreas.slice().sort((x, y) => x.v - y.v)[0];

  let improved = 0, declined = 0;
  for (const id of reachedIds) {
    const h = historyFor(id);
    if (h.length >= 2 && h[0].averageScore !== h[1].averageScore) {
      if (h[0].averageScore > h[1].averageScore) improved += 1; else declined += 1;
    }
  }

  // SSA heatmap rows by district.
  const heatRows: HeatmapRow[] = districts.map((d) => {
    const ids = reachedSchools.filter((s) => s!.district === d).map((s) => s!.schoolId);
    const snaps = ids.map((id) => historyFor(id)[0]).filter(Boolean);
    const scores: Record<string, number | undefined> = {};
    for (const a of interventions) {
      let sum = 0, n = 0;
      for (const rec of snaps) { const sc = rec.scores.find((x) => x.intervention === a); if (sc) { sum += sc.score; n += 1; } }
      scores[a] = n > 0 ? Math.round((sum / n) * 10) / 10 : undefined;
    }
    return { key: d, label: d, scores };
  });

  // ── Trend: completed activities by month within the cycle ──
  const byMonth = new Map<string, number>();
  for (const a of acts.filter(isCompleted)) byMonth.set(monthOf(a.date), (byMonth.get(monthOf(a.date)) ?? 0) + 1);
  const trend: TrendPoint[] = [...byMonth.entries()].sort((x, y) => x[0].localeCompare(y[0])).map(([period, value]) => ({ period, value }));

  // ── Exam + MSC headline counts ──
  const examCollected = exams.filter((e) => e.collected);
  const examImproved = examCollected.filter((e) => e.prevScore !== undefined && e.score > e.prevScore).length;
  const examDeclined = examCollected.filter((e) => e.prevScore !== undefined && e.score < e.prevScore).length;
  const mscDonorReady = stories.filter((m) => m.status === "DonorReady").length;

  // ── Target context for the completed-activities headline ──
  const completedCount = pipeline[1].count;
  const fyTarget = fyTargetForRole(input.role ?? "CCEO");
  const pt = computePeriodTarget({ fyTarget, selectedFy: fyId, selectedQuarter: selection.quarter, achieved: completedCount, now });

  // ── Data quality ──
  const dqNotes: string[] = [];
  if (missingEnrollment > 0) dqNotes.push(`Learners impacted may be undercounted — ${missingEnrollment} reached school${missingEnrollment === 1 ? "" : "s"} missing enrollment.`);
  const examMissing = exams.filter((e) => !e.collected).length;
  if (examMissing > 0) dqNotes.push(`${examMissing} school${examMissing === 1 ? "" : "s"} missing exam results.`);
  const noSf = acts.filter((a) => (a.evidenceStatus === "complete" || a.evidenceStatus === "verified") && !isCompleted(a)).length;
  if (noSf > 0) dqNotes.push(`${noSf} activit${noSf === 1 ? "y" : "ies"} have evidence but no valid Salesforce ID (not counted complete).`);
  const dataQuality: DataQuality = { level: dqNotes.length === 0 ? "ok" : "caveat", notes: dqNotes };

  // ── Assemble metrics ──
  const metric = (
    key: string, label: string, group: AnalyticsMetric["group"], value: number, definition: string,
    breakdown: AnalyticsMetric["breakdown"], records: DrilldownRecord[], source: AnalyticsMetric["source"] = "derived", dq: DataQuality = { level: "ok", notes: [] },
  ): AnalyticsMetric => ({ key, label, group, value, definition, source, breakdown, records, dataQuality: dq });

  const zero = { planned: 0, completed: 0, verified: 0, donorReady: 0 };
  const metrics: AnalyticsMetric[] = [
    metric("schoolsReached", "Schools Reached", "reach", reachBreakdown.completed,
      "Unique schools with ≥1 qualifying completed/verified activity in the selected scope (verified = IA-verified; donor-ready = in Salesforce + IA-verified).",
      reachBreakdown, reachedIds.map((id) => schoolRecord(id))),
    metric("learnersImpacted", "Learners Impacted", "impact", learners,
      "Sum of latest valid enrollment over unique reached schools (counted once per school; no multiplication by activity count).",
      { ...zero, completed: learners }, learnerRecords, "estimated", { level: missingEnrollment > 0 ? "caveat" : "ok", notes: missingEnrollment > 0 ? [`${missingEnrollment} reached schools missing enrollment`] : [] }),
    metric("teachersTrained", "Teachers Trained", "reach", teachers.length,
      "Unique teacher participants (dedup by identityKey) from verified training records in scope.",
      { ...zero, completed: teachers.length, verified: teachers.length }, participantRecords(teachers)),
    metric("schoolLeadersTrained", "School Leaders Trained", "reach", leaders.length,
      "Unique school-leader participants (head/deputy/director/SLT, dedup by identityKey) from verified training records.",
      { ...zero, completed: leaders.length, verified: leaders.length }, participantRecords(leaders)),
    metric("districtsCovered", "Districts Covered", "geography", districts.length,
      "Distinct districts with ≥1 reached school in scope.",
      { ...zero, completed: districts.length }, districts.map((d) => ({ id: d, entityType: "school", title: d, contributesToCount: true }))),
    metric("clustersCovered", "Clusters Covered", "geography", clusters.length,
      "Distinct clusters with ≥1 reached school in scope.",
      { ...zero, completed: clusters.length }, clusters.map((c) => ({ id: c, entityType: "cluster", title: c, contributesToCount: true }))),
    {
      ...metric("activitiesCompleted", "Activities Completed", "pipeline", completedCount,
        "Activities with evidence complete AND a valid Salesforce ID (the Salesforce completion gate).",
        { planned: pipeline[0].count, completed: pipeline[1].count, verified: pipeline[2].count, donorReady: acts.filter(isDonorReady).length }, pipeline[1].records),
      target: { expectedCumulative: pt.expectedCumulative, paceStatus: pt.paceStatus, gapToExpected: pt.gapToExpected },
    },
    metric("ssaImproved", "Schools Improved (SSA)", "ssa", improved,
      "Reached schools whose latest SSA average exceeds the previous SSA.",
      { ...zero, completed: improved }, [], "derived"),
    metric("ssaDeclined", "Schools Declined (SSA)", "ssa", declined,
      "Reached schools whose latest SSA average is below the previous SSA.",
      { ...zero, completed: declined }, []),
    metric("examImproved", "Exam — Improved", "impact", examImproved,
      "Schools whose collected exam score exceeds the previous year.",
      { ...zero, completed: examImproved }, examCollected.map((e) => ({ id: e.id, entityType: "school", title: analyticsSchoolById(e.schoolId)?.schoolName ?? e.schoolId, subtitle: `${e.score} (was ${e.prevScore ?? "—"})`, schoolId: e.schoolId, value: e.score, contributesToCount: e.prevScore !== undefined && e.score > e.prevScore }))),
    metric("mscDonorReady", "MSC Stories — Donor-Ready", "impact", mscDonorReady,
      "Most-Significant-Change stories that reached the Donor-Ready workflow state.",
      { ...zero, donorReady: mscDonorReady }, stories.map((m) => ({ id: m.id, entityType: "school", title: m.title, subtitle: `${m.district} · ${m.status}`, schoolId: m.schoolId, district: m.district, status: m.status, contributesToCount: m.status === "DonorReady" }))),
  ];

  void best; void worst; void examDeclined; // surfaced via heatmap / future cards

  return {
    scopeLabel: input.scopeLabel ?? "All in scope",
    fyId,
    cycleTag,
    metrics,
    pipeline,
    ssaHeatmap: { interventions: [...interventions], rows: heatRows },
    trend,
    dataQuality,
  };
}

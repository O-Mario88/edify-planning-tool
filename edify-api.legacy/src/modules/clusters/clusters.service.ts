import { BadRequestException, ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { ClusterType, Prisma } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { AuditService } from '../../common/audit/audit.service';
import { ScopeService } from '../../common/scope/scope.service';
import { ReadinessService } from '../../common/readiness/readiness.service';
import { DomainEventService } from '../../common/realtime/domain-events.service';
import { permissionsForRole, PERMISSIONS } from '../../common/rbac/permissions';
import { AuthUser } from '../../common/auth/auth-user';
import { CreateClusterDto, CreateClusterFromSchoolDto } from './dto/cluster.dto';

@Injectable()
export class ClustersService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
    private readonly scope: ScopeService,
    private readonly readiness: ReadinessService,
    private readonly events: DomainEventService,
  ) {}

  // ── Lists ─────────────────────────────────────────────────────────
  async list(user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const where: Prisma.ClusterWhereInput = { deletedAt: null, status: { in: ['active', 'needs_review'] } };
    if (!scope.countryScope && !scope.canViewSummaryOnly) {
      where.districtId = { in: scope.districtIds.length ? scope.districtIds : ['__none__'] };
    }
    const rows = await this.prisma.cluster.findMany({
      where, orderBy: { name: 'asc' }, take: 1000, // safety bound on payload
      include: {
        district: { select: { name: true } },
        subCounty: { select: { name: true } },
        coveredSubCounties: { include: { subCounty: { select: { id: true, name: true } } } },
        schools: { where: { deletedAt: null }, select: { currentFySsaStatus: true } },
        _count: { select: { schools: true } },
      },
    });
    return rows.map((c) => ({
      id: c.id, name: c.name, clusterType: c.clusterType, status: c.status,
      district: c.district ? { name: c.district.name } : null,
      subCounty: c.subCounty ? { name: c.subCounty.name } : null,
      subCountyName: c.subCountyName, responsibleStaffId: c.responsibleStaffId,
      clusterLeaderName: c.clusterLeaderName, clusterLeaderPhone: c.clusterLeaderPhone,
      subCounties: c.coveredSubCounties.map((x) => x.subCounty.name),
      subCountyIds: c.coveredSubCounties.map((x) => x.subCountyId),
      schoolCount: c._count.schools,
      schoolsWithSsa: c.schools.filter((s) => s.currentFySsaStatus === 'done').length,
      _count: c._count,
    }));
  }

  /** The cluster's school roster (§12). */
  async clusterSchools(clusterId: string, user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const cluster = await this.prisma.cluster.findUnique({ where: { id: clusterId } });
    if (!cluster) throw new NotFoundException('Cluster not found');
    if (!scope.countryScope && !scope.canViewSummaryOnly && !scope.districtIds.includes(cluster.districtId)) throw new ForbiddenException('Cluster outside your scope');
    const schools = await this.prisma.school.findMany({
      where: { clusterId, deletedAt: null }, take: 500, // a cluster roster is small; bound anyway
      include: {
        subCounty: { select: { name: true } },
        accountOwner: { include: { user: { select: { name: true } } } },
        ssaRecords: { where: { deletedAt: null }, orderBy: { dateOfSsa: 'desc' }, take: 1, include: { scores: true } },
      },
      orderBy: { name: 'asc' },
    });

    // Per-school weakest SSA intervention (lowest-scoring area on the latest SSA),
    // plus a cluster-wide common weak intervention = the intervention with the
    // lowest AVERAGE score across all schools (the area the whole cluster shares).
    const clusterTotals = new Map<string, { sum: number; n: number }>();
    const weakestOf = (scores: { intervention: string; score: number }[]): { area: string; score: number } | null => {
      if (!scores.length) return null;
      const w = scores.reduce((a, b) => (b.score < a.score ? b : a));
      return { area: w.intervention, score: w.score };
    };
    for (const s of schools) {
      for (const sc of s.ssaRecords[0]?.scores ?? []) {
        const t = clusterTotals.get(sc.intervention) ?? { sum: 0, n: 0 };
        t.sum += sc.score; t.n += 1; clusterTotals.set(sc.intervention, t);
      }
    }
    let commonWeakIntervention: { area: string; avgScore: number } | null = null;
    for (const [area, t] of clusterTotals) {
      const avg = t.sum / t.n;
      if (!commonWeakIntervention || avg < commonWeakIntervention.avgScore) {
        commonWeakIntervention = { area, avgScore: Math.round(avg * 10) / 10 };
      }
    }

    return {
      cluster: { id: cluster.id, name: cluster.name, status: cluster.status, type: cluster.clusterType },
      count: schools.length,
      commonWeakIntervention,
      schools: schools.map((s) => ({
        schoolId: s.schoolId, name: s.name, schoolType: s.schoolType, subCounty: s.subCounty?.name,
        phone: s.schoolPhone ?? s.primaryContactPhone ?? null,
        primaryContact: s.primaryContactName ?? null,
        accountOwner: s.accountOwner?.user.name, ssaStatus: s.currentFySsaStatus, planningReadiness: s.planningReadiness,
        latestSsa: s.ssaRecords[0]?.averageScore ?? null,
        weakestIntervention: weakestOf(s.ssaRecords[0]?.scores ?? []),
        stage: this.readiness.stageFor(s),
      })),
    };
  }

  /** Sub-counties with NO active cluster + their unclustered school counts (the
   *  default cluster-creation list, §9). */
  async subCountiesWithoutClusters(user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const districtFilter: Prisma.SubCountyWhereInput = (!scope.countryScope && !scope.canViewSummaryOnly)
      ? { districtId: { in: scope.districtIds.length ? scope.districtIds : ['__none__'] } } : {};
    const subs = await this.prisma.subCounty.findMany({
      where: { ...districtFilter, clusters: { none: { deletedAt: null, status: 'active' } } }, take: 1000,
      include: { district: { select: { name: true } }, _count: { select: { schools: { where: { deletedAt: null, clusterStatus: 'unclustered' } } } } },
      orderBy: [{ district: { name: 'asc' } }, { name: 'asc' }],
    });
    return subs.map((s) => ({ subCountyId: s.id, subCounty: s.name, district: s.district.name, districtId: s.districtId, unclusteredSchools: s._count.schools }));
  }

  /** Per-cluster planning intelligence, derived from REAL cluster activities
   *  with NO 3-meeting cap. A cluster may have 0, 1, 3, 5, 10+ completed
   *  meetings. The intelligence engine classifies each cluster by signal
   *  (cadence, SSA, coverage) — never by ordinal meeting position. */
  async clusterPlanning(user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const where: Prisma.ClusterWhereInput = { deletedAt: null, status: 'active' };
    if (!scope.countryScope && !scope.canViewSummaryOnly) where.districtId = { in: scope.districtIds.length ? scope.districtIds : ['__none__'] };

    const clusters = await this.prisma.cluster.findMany({
      where, take: 1000, orderBy: { name: 'asc' },
      include: {
        district: { select: { name: true } },
        subCounty: { select: { name: true } },
        _count: { select: { schools: true } },
        schools: { where: { deletedAt: null }, select: { id: true, currentFySsaStatus: true } },
        activities: {
          // Exclude cancelled/rejected/deferred work — those don't count
          // toward cadence.
          where: {
            deletedAt: null,
            activityType: { in: ['cluster_meeting', 'cluster_training', 'school_improvement_training'] },
            status: { notIn: ['cancelled', 'rejected', 'deferred', 'not_planned'] },
          },
          select: {
            activityType: true, status: true, scheduledDate: true,
            plannedMonth: true, rescheduleCount: true, clusterSlot: true,
          },
          orderBy: [{ scheduledDate: 'asc' }, { plannedMonth: 'asc' }],
        },
      },
    });

    const DONE = new Set([
      'completed', 'evidence_uploaded', 'evidence_accepted',
      'salesforce_id_required', 'awaiting_ia_verification', 'ia_verified',
      'accountant_confirmed',
    ]);
    const SCHEDULED = new Set(['scheduled', 'in_progress', 'planned']);
    const now = new Date();
    const quarterStart = new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1);

    return clusters.map((c) => {
      const schoolsWithSsa = c.schools.filter((s) => s.currentFySsaStatus === 'done').length;
      const schoolsCount = c._count.schools;

      // Open-ended cadence — count, don't slot. Trainings include both
      // cluster_training and school_improvement_training.
      const meetings = c.activities.filter((a) => a.activityType === 'cluster_meeting');
      const trainings = c.activities.filter(
        (a) => a.activityType === 'cluster_training' || a.activityType === 'school_improvement_training',
      );
      const completedMeetings = meetings.filter((m) => DONE.has(m.status));
      const scheduledMeetings = meetings.filter((m) => SCHEDULED.has(m.status));
      const completedTrainings = trainings.filter((t) => DONE.has(t.status));

      const meetingDates = completedMeetings
        .map((m) => m.scheduledDate)
        .filter((d): d is Date => d !== null && d !== undefined)
        .sort((a, b) => a.getTime() - b.getTime());
      const lastMeetingDate = meetingDates[meetingDates.length - 1];
      const upcomingDates = c.activities
        .filter((a) => SCHEDULED.has(a.status))
        .map((a) => a.scheduledDate)
        .filter((d): d is Date => d !== null && d !== undefined && d.getTime() >= now.getTime())
        .sort((a, b) => a.getTime() - b.getTime());
      const nextScheduled = upcomingDates[0];

      const metThisQuarter = completedMeetings.some(
        (m) => m.scheduledDate && m.scheduledDate.getTime() >= quarterStart.getTime(),
      );

      // Coverage — the backend doesn't yet track per-school visit/training
      // attendance directly here; conservative approximation: if the
      // cluster has any completed training, no schools are "untrained" via
      // this signal. The FE intelligence engine carries the same shape,
      // so the planning category lights up the same way once richer
      // per-school join data is wired. (Tracking issue: ED-CL-INTEL-1.)
      const schoolsNotVisited = scheduledMeetings.length === 0 && completedMeetings.length === 0 ? schoolsCount : 0;
      const schoolsNotTrained = completedTrainings.length === 0 ? schoolsCount : 0;
      const schoolsNeitherVisitNorTraining = Math.min(schoolsNotVisited, schoolsNotTrained);

      // Intelligence-driven planning category.
      const manyThreshold = Math.max(2, Math.ceil(schoolsCount * 0.25));
      let gapCategory:
        | 'no_meetings_this_fy' | 'not_met_this_quarter' | 'schools_need_support'
        | 'weak_ssa_intervention' | 'ssa_performance_drop' | 'schools_not_visited'
        | 'schools_not_trained' | 'schools_neither_visit_nor_training' | 'training_needed'
        | 'follow_up_needed' | 'meeting_due' | 'on_track';
      let recommendationHeadline: string | null = null;
      let recommendationReason: string | null = null;
      let recommendationActivityLabel: string | null = null;

      if (schoolsNeitherVisitNorTraining >= manyThreshold && schoolsCount > 0) {
        gapCategory = 'schools_neither_visit_nor_training';
        recommendationHeadline = `Urgent: ${schoolsNeitherVisitNorTraining} schools without visit or training`;
        recommendationReason = `${schoolsNeitherVisitNorTraining} of ${schoolsCount} schools in this cluster have received neither a visit nor a training this period.`;
        recommendationActivityLabel = 'Schedule Urgent Cluster Support';
      } else if (schoolsNotTrained >= manyThreshold && schoolsCount > 0) {
        gapCategory = 'schools_not_trained';
        recommendationHeadline = `${schoolsNotTrained} schools have not been trained`;
        recommendationReason = `Schedule cluster training to reach ${schoolsNotTrained} schools that haven't participated in any training this period.`;
        recommendationActivityLabel = 'Schedule Cluster Training';
      } else if (completedMeetings.length === 0 && scheduledMeetings.length === 0) {
        gapCategory = 'no_meetings_this_fy';
        recommendationHeadline = 'Cluster has not met this fiscal year';
        recommendationReason = 'Schedule a cluster meeting to establish the planning rhythm for this FY.';
        recommendationActivityLabel = 'Schedule Cluster Meeting';
      } else if (!metThisQuarter) {
        gapCategory = 'not_met_this_quarter';
        const daysAgo = lastMeetingDate
          ? Math.floor((now.getTime() - lastMeetingDate.getTime()) / (1000 * 60 * 60 * 24))
          : null;
        recommendationHeadline = 'Cluster has not met this quarter';
        recommendationReason = daysAgo !== null
          ? `Last cluster meeting was ${daysAgo} days ago. Schedule a cluster meeting to maintain cadence.`
          : 'Schedule a cluster meeting to maintain cadence.';
        recommendationActivityLabel = 'Schedule Cluster Meeting';
      } else if (completedTrainings.length === 0) {
        gapCategory = 'training_needed';
        recommendationHeadline = 'Cluster has no completed trainings';
        recommendationReason = 'Schedule cluster training aligned to the weakest SSA intervention.';
        recommendationActivityLabel = 'Schedule Cluster Training';
      } else if (schoolsCount - schoolsWithSsa > 0) {
        gapCategory = 'schools_need_support';
        recommendationHeadline = `${schoolsCount - schoolsWithSsa} schools need SSA support`;
        recommendationReason = 'Schedule a follow-up meeting or training to bring missing-SSA schools into the cluster plan.';
        recommendationActivityLabel = 'Schedule Cluster Meeting';
      } else {
        gapCategory = 'on_track';
        recommendationHeadline = 'Cluster is on track';
        recommendationReason = 'Cadence, SSA coverage, and training are within thresholds.';
        recommendationActivityLabel = 'Review Cluster';
      }

      // Legacy slot status — derived ONLY for ordinal-tagged meetings still
      // present in the activity history (so the FE reschedule drawer can
      // operate on them). New meetings have no clusterSlot and don't get a
      // slot status.
      const slotOf = (a?: { status: string; rescheduleCount: number }): string | undefined => {
        if (!a) return undefined;
        if (DONE.has(a.status)) return 'Completed';
        if (a.rescheduleCount > 0) return 'Rescheduled';
        if (SCHEDULED.has(a.status)) return 'Scheduled';
        return 'Other';
      };
      const sitAct = c.activities.find((a) => a.clusterSlot === 'sit');
      const firstAct = c.activities.find((a) => a.clusterSlot === 'first_meeting');
      const secondAct = c.activities.find((a) => a.clusterSlot === 'second_meeting');
      const thirdAct = c.activities.find((a) => a.clusterSlot === 'third_meeting');

      return {
        id: c.id, clusterName: c.name,
        district: c.district?.name ?? '', subCounty: c.subCounty?.name ?? c.subCountyName ?? '',
        schoolsCount, schoolsWithSsa,

        meetingsThisFy: completedMeetings.length,
        meetingsScheduledThisFy: scheduledMeetings.length,
        trainingsThisFy: completedTrainings.length,
        lastMeetingDate: lastMeetingDate ? lastMeetingDate.toISOString().slice(0, 10) : null,
        nextScheduledMeetingDate: nextScheduled ? nextScheduled.toISOString().slice(0, 10) : null,
        metThisQuarter,
        schoolsNotVisited,
        schoolsNotTrained,
        schoolsNeitherVisitNorTraining,

        gapCategory,
        recommendationHeadline,
        recommendationReason,
        recommendationActivityLabel,
        recommendationFocusIntervention: null as string | null,

        // Optional legacy slot fields — only set when an ordinal-tagged
        // meeting still exists.
        sit: slotOf(sitAct),
        firstMeeting: slotOf(firstAct),
        secondMeeting: slotOf(secondAct),
        thirdMeeting: slotOf(thirdAct),
      };
    });
  }

  /** Single-cluster intelligence — the cluster detail page reads from this
   *  endpoint for the full SSA performance + coverage + cadence breakdown.
   *  Same shape as the in-memory `computeClusterIntelligence` so the FE can
   *  swap between mock and live without a separate adapter. */
  async clusterIntelligence(clusterId: string, user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const cluster = await this.prisma.cluster.findUnique({
      where: { id: clusterId },
      include: {
        district: { select: { name: true } },
        subCounty: { select: { name: true } },
        coveredSubCounties: { include: { subCounty: { select: { name: true } } } },
      },
    });
    if (!cluster) throw new NotFoundException('Cluster not found');
    if (!scope.countryScope && !scope.canViewSummaryOnly && !scope.districtIds.includes(cluster.districtId))
      throw new ForbiddenException('Cluster outside your scope');

    const [schools, activities] = await Promise.all([
      this.prisma.school.findMany({
        where: { clusterId, deletedAt: null }, take: 500,
        include: {
          ssaRecords: { where: { deletedAt: null }, orderBy: { dateOfSsa: 'desc' }, take: 2, include: { scores: true } },
        },
        orderBy: { name: 'asc' },
      }),
      this.prisma.activity.findMany({
        where: {
          clusterId, deletedAt: null,
          activityType: { in: ['cluster_meeting', 'cluster_training', 'school_improvement_training'] },
          status: { notIn: ['cancelled', 'rejected', 'deferred', 'not_planned'] },
        },
        select: {
          id: true, activityType: true, status: true,
          scheduledDate: true, rescheduleCount: true,
          teachersAttended: true, leadersAttended: true,
        },
        orderBy: { scheduledDate: 'asc' },
      }),
    ]);

    const DONE = new Set([
      'completed', 'evidence_uploaded', 'evidence_accepted',
      'salesforce_id_required', 'awaiting_ia_verification', 'ia_verified',
      'accountant_confirmed',
    ]);
    const SCHEDULED = new Set(['scheduled', 'in_progress', 'planned']);
    const now = new Date();
    const quarterStart = new Date(now.getFullYear(), Math.floor(now.getMonth() / 3) * 3, 1);

    // Per-school current + previous SSA + coarse visit/training flags
    type Sch = (typeof schools)[number];
    const schoolRow = (s: Sch) => {
      const curr = s.ssaRecords[0];
      const prev = s.ssaRecords[1];
      const currScores: Record<string, number> = {};
      for (const sc of curr?.scores ?? []) currScores[sc.intervention] = sc.score;
      const prevScores: Record<string, number> = {};
      for (const sc of prev?.scores ?? []) prevScores[sc.intervention] = sc.score;
      const visitedThisPeriod = false;   // placeholder until visit join lands
      const trainedThisPeriod = false;
      return {
        schoolId: s.schoolId, schoolName: s.name,
        schoolType: (s.schoolType ?? 'client'),
        hasCurrentFySsa: s.currentFySsaStatus === 'done',
        currentSsa: currScores, previousSsa: prevScores,
        visitedThisPeriod, trainedThisPeriod,
        latestSsa: curr?.averageScore ?? null,
        weakestIntervention: curr?.scores?.length
          ? curr.scores.reduce((w, sc) => sc.score < w.score ? sc : w).intervention
          : null,
      };
    };
    const schoolRows = schools.map(schoolRow);

    // Cadence (open-ended)
    const completedMeetings = activities.filter((a) => a.activityType === 'cluster_meeting' && DONE.has(a.status));
    const scheduledMeetings = activities.filter((a) => a.activityType === 'cluster_meeting' && SCHEDULED.has(a.status));
    const trainings = activities.filter((a) => (a.activityType === 'cluster_training' || a.activityType === 'school_improvement_training') && DONE.has(a.status));
    const completedDates = completedMeetings.map((a) => a.scheduledDate).filter((d): d is Date => !!d).sort((a, b) => a.getTime() - b.getTime());
    const lastMeetingDate = completedDates[completedDates.length - 1];
    const upcomingDates = activities
      .filter((a) => SCHEDULED.has(a.status))
      .map((a) => a.scheduledDate)
      .filter((d): d is Date => !!d && d.getTime() >= now.getTime())
      .sort((a, b) => a.getTime() - b.getTime());
    const nextScheduled = upcomingDates[0];
    const metThisQuarter = completedMeetings.some((m) => m.scheduledDate && m.scheduledDate.getTime() >= quarterStart.getTime());

    // Per-intervention performance
    const SSA_KEYS = [
      'teaching_and_learning', 'financial_health', 'christlike_behaviour',
      'exposure_to_word_of_god', 'government_requirements_and_compliance',
      'leadership', 'education_technology', 'learning_environment',
    ] as const;
    const round1 = (n: number) => Math.round(n * 10) / 10;
    const statusFor = (s: number) => s >= 9 ? 'Strong' : s >= 7 ? 'Good' : s >= 5 ? 'Needs Support' : 'Critical';
    const performance = SSA_KEYS.map((k) => {
      const currs = schoolRows.map((s) => s.currentSsa[k]).filter((n): n is number => typeof n === 'number');
      const prevs = schoolRows.map((s) => s.previousSsa[k]).filter((n): n is number => typeof n === 'number');
      const avg = currs.length ? round1(currs.reduce((a, b) => a + b, 0) / currs.length) : 0;
      const prevAvg = prevs.length ? round1(prevs.reduce((a, b) => a + b, 0) / prevs.length) : undefined;
      return {
        intervention: k, averageScore: avg,
        schoolsAssessed: currs.length,
        schoolsMissingSsa: schoolRows.filter((s) => !s.hasCurrentFySsa).length,
        previousAverage: prevAvg,
        delta: prevAvg !== undefined ? round1(avg - prevAvg) : undefined,
        status: statusFor(avg),
      };
    });

    const assessed = performance.filter((p) => p.schoolsAssessed > 0);
    const averageSsaScore = assessed.length ? round1(assessed.reduce((s, p) => s + p.averageScore, 0) / assessed.length) : 0;
    const weakest = [...assessed].sort((a, b) => a.averageScore - b.averageScore)[0] ?? null;
    const strongest = [...assessed].sort((a, b) => b.averageScore - a.averageScore)[0] ?? null;

    const improved = performance
      .filter((p) => p.delta !== undefined && p.delta >= 0.5)
      .map((p) => ({
        intervention: p.intervention,
        previousAverage: p.previousAverage!, latestAverage: p.averageScore,
        improvement: p.delta!, schoolsImproved: schoolRows.filter((s) => {
          const c = s.currentSsa[p.intervention];
          const pr = s.previousSsa[p.intervention];
          return typeof c === 'number' && typeof pr === 'number' && c - pr >= 0.5;
        }).length,
      }))
      .sort((a, b) => b.improvement - a.improvement);
    const declined = performance
      .filter((p) => p.delta !== undefined && p.delta <= -0.5)
      .map((p) => ({
        intervention: p.intervention,
        previousAverage: p.previousAverage!, latestAverage: p.averageScore,
        drop: round1(Math.abs(p.delta!)),
        schoolsDeclined: schoolRows.filter((s) => {
          const c = s.currentSsa[p.intervention];
          const pr = s.previousSsa[p.intervention];
          return typeof c === 'number' && typeof pr === 'number' && pr - c >= 0.5;
        }).length,
      }))
      .sort((a, b) => b.drop - a.drop);

    const notVisited = schoolRows.filter((s) => !s.visitedThisPeriod);
    const notTrained = schoolRows.filter((s) => !s.trainedThisPeriod);
    const neitherVisitNorTraining = schoolRows.filter((s) => !s.visitedThisPeriod && !s.trainedThisPeriod);

    return {
      cluster: {
        id: cluster.id, name: cluster.name,
        district: cluster.district?.name ?? null,
        subCounties: cluster.coveredSubCounties.map((x) => x.subCounty.name),
        clusterType: cluster.clusterType, clusterLeaderName: cluster.clusterLeaderName,
      },
      schools: schoolRows,
      cadence: {
        meetingsThisFy: completedMeetings.length,
        meetingsScheduledThisFy: scheduledMeetings.length,
        trainingsThisFy: trainings.length,
        totalActivitiesThisFy: completedMeetings.length + scheduledMeetings.length + trainings.length,
        lastMeetingDate: lastMeetingDate ? lastMeetingDate.toISOString().slice(0, 10) : null,
        nextScheduledDate: nextScheduled ? nextScheduled.toISOString().slice(0, 10) : null,
        metThisQuarter,
        teachersTrained: activities.reduce((sum, a) => sum + (a.teachersAttended ?? 0), 0),
        schoolLeadersTrained: activities.reduce((sum, a) => sum + (a.leadersAttended ?? 0), 0),
      },
      coverage: {
        total: schoolRows.length,
        withCurrentFySsa: schoolRows.filter((s) => s.hasCurrentFySsa).length,
        missingSsa: schoolRows.filter((s) => !s.hasCurrentFySsa).length,
        notVisitedCount: notVisited.length,
        notTrainedCount: notTrained.length,
        neitherVisitNorTrainingCount: neitherVisitNorTraining.length,
      },
      ssaPerformance: performance, averageSsaScore,
      weakestIntervention: weakest,
      strongestIntervention: strongest,
      improved, declined,
    };
  }

  // Shared include so cluster recommendations / eligibility carry the covered
  // sub-county set + leader contact the directory drawer needs.
  private readonly clusterCardInclude = {
    district: { select: { name: true } },
    subCounty: { select: { name: true } },
    coveredSubCounties: { include: { subCounty: { select: { name: true } } } },
    _count: { select: { schools: true } },
  } as const;

  /** Eligibility: same sub-county (cluster COVERS it) → same district (→ region
   *  needs override). A cluster is "same sub-county" iff the school's sub-county
   *  is in its covered set. */
  async recommendations(schoolId: string, user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const school = await this.prisma.school.findFirst({ where: { schoolId, deletedAt: null, ...this.scope.schoolWhere(scope) }, include: { subCounty: true } });
    if (!school) throw new NotFoundException('School not found or outside scope');
    const base = { deletedAt: null, status: 'active' as const };
    const [sameSubRaw, sameDistrictRaw] = await Promise.all([
      school.subCountyId
        ? this.prisma.cluster.findMany({
            where: { ...base, OR: [{ subCountyId: school.subCountyId }, { coveredSubCounties: { some: { subCountyId: school.subCountyId } } }] },
            include: this.clusterCardInclude,
          })
        : Promise.resolve([]),
      this.prisma.cluster.findMany({ where: { ...base, districtId: school.districtId }, include: this.clusterCardInclude }),
    ]);
    const card = (c: (typeof sameSubRaw)[number]) => ({
      id: c.id, name: c.name, district: c.district?.name, status: c.status, clusterType: c.clusterType,
      subCounty: c.subCounty?.name ?? c.subCountyName,
      subCounties: c.coveredSubCounties.map((x) => x.subCounty.name),
      clusterLeaderName: c.clusterLeaderName, clusterLeaderPhone: c.clusterLeaderPhone,
      schoolCount: c._count.schools, _count: c._count,
    });
    const sameSub = sameSubRaw.map(card);
    const sameSubIds = new Set(sameSub.map((c) => c.id));
    // District alternatives exclude the same-sub-county ones (already eligible).
    const sameDistrict = sameDistrictRaw.map(card).filter((c) => !sameSubIds.has(c.id));
    return {
      schoolId, district: school.districtId, subCounty: school.subCounty?.name,
      sameSubCounty: sameSub, sameDistrict,
      canCreate: scope.permissions.includes(PERMISSIONS.CLUSTER_ASSIGN),
      hint: sameSub.length === 0 && school.subCountyId ? `No eligible cluster exists for this school's sub-county (${school.subCounty?.name}). Create one.` : undefined,
    };
  }

  /** Flat eligible-cluster list for a school (§5 assignment drawer). */
  async eligibleForSchool(schoolId: string, user: AuthUser) {
    const r = await this.recommendations(schoolId, user);
    return {
      schoolId, subCounty: r.subCounty,
      eligible: r.sameSubCounty, districtAlternatives: r.sameDistrict,
      canCreate: r.canCreate, hint: r.hint,
    };
  }

  // ── Create (one OR MORE sub-counties, §4/§5) ──────────────────────
  async create(dto: CreateClusterDto, user: AuthUser) {
    const district = await this.prisma.district.findUnique({ where: { id: dto.districtId } });
    if (!district || district.regionId !== dto.regionId) throw new BadRequestException('district does not belong to region');
    const scope = await this.scope.resolveUserScope(user);
    if (!scope.countryScope && !scope.districtIds.includes(dto.districtId)) throw new ForbiddenException('District outside your scope');

    // The covered sub-county set: prefer subCountyIds[], fall back to subCountyId.
    const subCountyIds = [...new Set(
      dto.subCountyIds?.length ? dto.subCountyIds : dto.subCountyId ? [dto.subCountyId] : [],
    )];
    if (subCountyIds.length === 0) throw new BadRequestException('At least one sub-county is required');
    const subs = await this.prisma.subCounty.findMany({ where: { id: { in: subCountyIds } } });
    if (subs.length !== subCountyIds.length) throw new BadRequestException('Unknown sub-county');
    for (const sc of subs) if (sc.districtId !== dto.districtId) throw new BadRequestException('sub-county does not belong to district');
    const primary = subs.find((s) => s.id === subCountyIds[0])!;

    // Sub-county uniqueness (§10): one active cluster per sub-county by default —
    // checked across BOTH the legacy primary column and the coverage join, so a
    // multi-sub-county cluster can't overlap an existing one.
    let needsReview = false;
    const taken = await this.prisma.subCounty.findMany({
      where: {
        id: { in: subCountyIds },
        OR: [
          { clusters: { some: { deletedAt: null, status: 'active' } } },
          { clusterLinks: { some: { cluster: { deletedAt: null, status: 'active' } } } },
        ],
      },
      select: { id: true, name: true },
    });
    if (taken.length) {
      const canOverride = permissionsForRole(user.activeRole).includes(PERMISSIONS.CLUSTER_OVERRIDE);
      if (!canOverride || !dto.overrideReason?.trim()) {
        await this.audit.log({ action: 'cluster.createBlocked', subjectKind: 'SubCounty', subjectId: taken[0].id, actorId: user.userId, actorRole: user.activeRole, payload: { reason: 'sub-county already has an active cluster', taken: taken.map((t) => t.name) } });
        throw new BadRequestException(`${taken.map((t) => t.name).join(', ')} already ${taken.length > 1 ? 'have' : 'has'} an active cluster. Provide an override reason (requires permission) to add another.`);
      }
      needsReview = true;
    }

    let cluster;
    try {
      cluster = await this.prisma.cluster.create({
        data: {
          name: dto.name, regionId: dto.regionId, districtId: dto.districtId,
          subCountyId: primary.id, subCountyName: primary.name,
          clusterLeaderName: dto.clusterLeaderName?.trim() || undefined,
          clusterLeaderPhone: dto.clusterLeaderPhone?.trim() || undefined,
          clusterType: dto.clusterType ?? ClusterType.mixed,
          status: needsReview ? 'needs_review' : 'active',
          overrideReason: needsReview ? dto.overrideReason : undefined, responsibleStaffId: dto.responsibleStaffId,
          coveredSubCounties: { create: subCountyIds.map((id) => ({ subCountyId: id })) },
        },
      });
    } catch (e) {
      // Race backstop: the partial unique index rejected a concurrent 2nd active
      // cluster for the primary sub-county.
      if (e instanceof Prisma.PrismaClientKnownRequestError && e.code === 'P2002') {
        throw new BadRequestException('This sub-county already has an active cluster.');
      }
      throw e;
    }
    await this.audit.log({ action: needsReview ? 'cluster.createOverride' : 'cluster.create', subjectKind: 'Cluster', subjectId: cluster.id, actorId: user.userId, actorRole: user.activeRole, payload: { name: dto.name, subCountyIds, districtId: dto.districtId, overrideReason: dto.overrideReason } });
    return cluster;
  }

  /** Create a cluster from a selected school — prefills geography + auto-assigns. */
  async createFromSchool(dto: CreateClusterFromSchoolDto, user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const school = await this.prisma.school.findFirst({ where: { schoolId: dto.schoolId, deletedAt: null, ...this.scope.schoolWhere(scope) } });
    if (!school) throw new NotFoundException('School not found or outside scope');
    const cluster = await this.create({
      name: dto.name, regionId: school.regionId, districtId: school.districtId, subCountyId: school.subCountyId ?? undefined,
      clusterType: dto.clusterType, overrideReason: dto.overrideReason,
    }, user);
    try {
      const assigned = await this.assignSchool(dto.schoolId, cluster.id, undefined, user);
      return { cluster, assignment: assigned };
    } catch (e) {
      // Compensate: don't leave an orphan cluster occupying the sub-county slot.
      await this.prisma.cluster.update({ where: { id: cluster.id }, data: { deletedAt: new Date(), status: 'inactive' } });
      throw e;
    }
  }

  // ── Assign (the bridge to planning) ───────────────────────────────
  async assignSchool(schoolId: string, clusterId: string, reason: string | undefined, user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const school = await this.prisma.school.findFirst({ where: { schoolId, deletedAt: null, ...this.scope.schoolWhere(scope) } });
    if (!school) throw new NotFoundException('School not found or outside your scope');
    const cluster = await this.prisma.cluster.findUnique({ where: { id: clusterId } });
    if (!cluster || cluster.deletedAt) throw new NotFoundException('Cluster not found');
    // Scope the cluster too (H4) — a scoped role can't assign into out-of-scope clusters.
    if (!scope.countryScope && !scope.districtIds.includes(cluster.districtId)) throw new ForbiddenException('Cluster is outside your scope');
    // Geography must match — district AND the cluster's COVERED sub-county set
    // (§4/§5/§10/§11). A school is eligible iff its sub-county is one the cluster
    // covers (single- or multi-sub-county). Backend-enforced, not just UI.
    if (cluster.districtId !== school.districtId) throw new BadRequestException('Cluster and school are in different districts');
    const coveredLinks = await this.prisma.clusterSubCounty.findMany({ where: { clusterId }, select: { subCountyId: true } });
    const coveredIds = coveredLinks.length ? coveredLinks.map((c) => c.subCountyId) : cluster.subCountyId ? [cluster.subCountyId] : [];
    if (coveredIds.length && school.subCountyId && !coveredIds.includes(school.subCountyId)) {
      throw new BadRequestException("This cluster does not cover the school's sub-county");
    }

    const previousClusterId = school.clusterId;
    await this.prisma.schoolClusterAssignment.upsert({
      where: { schoolId_clusterId: { schoolId: school.id, clusterId } },
      update: { assignedBy: user.userId }, create: { schoolId: school.id, clusterId, assignedBy: user.userId },
    });
    await this.prisma.school.update({ where: { id: school.id }, data: { clusterId, clusterStatus: 'clustered' } });
    // Recompute planning readiness — the bridge to the planning lists (§16).
    const { planningReadiness, stage } = await this.readiness.recompute(school.id);

    await this.audit.log({
      action: previousClusterId && previousClusterId !== clusterId ? 'cluster.moveSchool' : 'cluster.assignSchool',
      subjectKind: 'School', subjectId: school.id, actorId: user.userId, actorRole: user.activeRole,
      payload: { clusterId, previousClusterId, subCountyId: school.subCountyId, districtId: school.districtId, reason, planningReadiness },
    });
    // Handoff: tell the school's account owner it's clustered and (if SSA-complete)
    // ready to plan — the bridge from the directory into their planning board.
    const ownerUserId = await this.events.userForStaff(school.accountOwnerId);
    if (ownerUserId && ownerUserId !== user.userId) {
      await this.events.emit({
        type: 'SchoolClustered',
        actorId: user.userId, actorRole: user.activeRole, subjectKind: 'School', subjectId: school.id,
        payload: { clusterId, planningReadiness },
        notify: [{
          recipientId: ownerUserId,
          title: 'School clustered — ready to plan',
          body: `${school.name} is now in a cluster${planningReadiness === 'ready' ? ' and ready for SSA-led planning.' : '.'}`,
          contextType: 'school', contextId: school.schoolId,
          actionRequired: planningReadiness === 'ready', priority: 'normal',
        }],
        liveUserIds: [user.userId, ownerUserId],
      });
    }
    return { ok: true, schoolId, clusterId, previousClusterId, planningReadiness, stage };
  }
}

import { BadRequestException, ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { Prisma, School } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { ScopeService } from '../../common/scope/scope.service';
import { ReadinessService } from '../../common/readiness/readiness.service';
import { AuthUser } from '../../common/auth/auth-user';
import { CreatePlanDto, DraftActivityDto } from './dto/plans.dto';
import { ActivitiesService } from '../activities/activities.service';
import { AssignSchoolVisitToPartnerDto, ScheduleClusterTrainingDto, ScheduleSchoolVisitDto } from './dto/planning-workflow.dto';

const APPROVER_ROLES = new Set(['CountryProgramLead', 'CountryDirector', 'Admin']);

// Readable labels for the 8 canonical SSA interventions — mirrors SsaService so
// planning-board recommendations and the SSA drawer never disagree on copy.
const INTERVENTION_LABEL: Record<string, string> = {
  teaching_and_learning: 'Teaching & Learning',
  financial_health: 'Financial Health',
  christlike_behaviour: 'Christ-like Behaviour',
  exposure_to_word_of_god: 'Exposure to the Word of God',
  government_requirements: 'Government Requirements',
  leadership: 'Leadership',
  education_technology: 'Education Technology',
  learning_environment: 'Learning Environment',
};

type Filters = { regionId?: string; districtId?: string; subCountyId?: string; fy?: string };

// A school leaves the "ready to plan" gap once it has an ACTIVE activity
// (planned through accountant-confirmed) — it now lives on the owner's My Plan,
// not the planning gap board. Terminal/returned states don't count. Shared by
// the setup board and the plan-builder feed so both agree on "unplanned".
const NO_ACTIVE_PLAN: Prisma.SchoolWhereInput = {
  activities: {
    none: {
      deletedAt: null,
      status: {
        in: [
          'planned', 'scheduled', 'rescheduled', 'assigned_to_partner', 'partner_scheduled',
          'in_progress', 'evidence_uploaded', 'evidence_accepted',
          'salesforce_id_required', 'awaiting_ia_verification', 'ia_verified',
          'accountant_confirmed',
        ] as never,
      },
    },
  },
};

// A school row with the latest SSA + its scores attached (planning include shape).
type SchoolWithSsa = School & {
  subCounty?: { name: string } | null;
  accountOwner?: { user: { name: string } } | null;
  ssaRecords?: { scores: { intervention: string; score: number }[] }[];
};

// The two weakest interventions from a school's latest SSA — the SSA-driven
// recommendation that planning consumes. Deterministic tie-break (score, then
// intervention name) so it ALWAYS matches SsaService.recommendationForSchool.
export type WeakestArea = { intervention: string; label: string; score: number };

// Planning consumes the School Directory + cluster status. Unclustered schools
// only appear in "Not Yet Clustered"; clustered-no-SSA in "Clustered, SSA
// Required"; clustered+SSA in "Ready to Plan" / Core Planning. This is the
// bridge from cluster assignment to planning.
@Injectable()
export class PlanningService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly scope: ScopeService,
    private readonly readiness: ReadinessService,
    private readonly activities: ActivitiesService,
  ) {}

  private async baseWhere(user: AuthUser, f: Filters): Promise<Prisma.SchoolWhereInput> {
    const scope = await this.scope.resolveUserScope(user);
    const where: Prisma.SchoolWhereInput = { deletedAt: null, ...this.scope.schoolWhere(scope) };
    if (f.regionId) where.regionId = f.regionId;
    if (f.districtId) where.districtId = f.districtId;
    if (f.subCountyId) where.subCountyId = f.subCountyId;
    return where;
  }

  /** The two weakest interventions from a school's latest SSA, or [] when none. */
  private weakestFor(s: SchoolWithSsa): WeakestArea[] {
    const scores = s.ssaRecords?.[0]?.scores;
    if (!scores || !scores.length) return [];
    return [...scores]
      .sort((a, b) => a.score - b.score || a.intervention.localeCompare(b.intervention))
      .slice(0, 2)
      .map((x) => ({ intervention: x.intervention, label: INTERVENTION_LABEL[x.intervention] ?? x.intervention, score: x.score }));
  }

  private item(s: SchoolWithSsa) {
    // Weakest areas are only meaningful when the current-FY SSA is complete —
    // suppress stale prior-year scores on the not-clustered / SSA-missing buckets.
    const weakest = s.currentFySsaStatus === 'done' ? this.weakestFor(s) : [];
    return {
      schoolId: s.schoolId, name: s.name, schoolType: s.schoolType, districtId: s.districtId,
      subCounty: s.subCounty?.name, owner: s.accountOwner?.user.name, ssaStatus: s.currentFySsaStatus,
      planningReadiness: s.planningReadiness, stage: this.readiness.stageFor(s),
      // SSA-driven recommendation — the two weakest interventions (present only
      // once a current-FY SSA exists, i.e. the readyToPlan / core buckets).
      weakest,
      weakestArea: weakest[0]?.label ?? null,
      secondWeakArea: weakest[1]?.label ?? null,
    };
  }

  /** The planning setup buckets (§13/§15) — each consumes cluster + SSA status. */
  async setup(user: AuthUser, f: Filters, sample = 8) {
    const base = await this.baseWhere(user, f);
    const buckets: { key: string; label: string; where: Prisma.SchoolWhereInput }[] = [
      { key: 'notYetClustered', label: 'Not Yet Clustered', where: { ...base, clusterStatus: { in: ['unclustered', 'needs_review'] } } },
      { key: 'clusteredSsaRequired', label: 'Clustered Schools Missing SSA', where: { ...base, clusterStatus: 'clustered', currentFySsaStatus: { in: ['not_done', 'partner_assigned'] } } },
      { key: 'sitScheduledSsaMissing', label: 'SIT Scheduled, SSA Missing', where: { ...base, clusterStatus: 'clustered', currentFySsaStatus: 'scheduled' } },
      { key: 'readyToPlan', label: 'SSA Complete, Ready to Plan', where: { ...base, ...NO_ACTIVE_PLAN, clusterStatus: 'clustered', currentFySsaStatus: 'done', schoolType: { not: 'core' } } },
      { key: 'coreSchoolPlanning', label: 'Core School Planning', where: { ...base, ...NO_ACTIVE_PLAN, clusterStatus: 'clustered', currentFySsaStatus: 'done', schoolType: 'core' } },
    ];
    const include = {
      subCounty: { select: { name: true } },
      accountOwner: { include: { user: { select: { name: true } } } },
      // Latest SSA + scores so SSA-complete buckets carry the two weakest
      // interventions inline (no per-school recommendation round-trip).
      ssaRecords: { where: { deletedAt: null }, orderBy: { dateOfSsa: 'desc' as const }, take: 1, include: { scores: true } },
    } as const;
    return Promise.all(buckets.map(async (b) => {
      const [count, items] = await this.prisma.$transaction([
        this.prisma.school.count({ where: b.where }),
        this.prisma.school.findMany({ where: b.where, take: sample, orderBy: { name: 'asc' }, include }),
      ]);
      return { key: b.key, label: b.label, count, items: items.map((s) => this.item(s)) };
    }));
  }

  /** Core School Planning accordion sections (§14) — visit/training gaps derived
   *  from completed core activities. Each school lands in its NEXT-needed bucket. */
  async corePlanning(user: AuthUser, f: Filters) {
    const base = await this.baseWhere(user, f);
    const cores = await this.prisma.school.findMany({
      where: { ...base, schoolType: 'core' },
      include: {
        subCounty: { select: { name: true } }, accountOwner: { include: { user: { select: { name: true } } } },
        activities: { where: { deletedAt: null, activityType: { in: ['core_visit', 'core_training'] } }, select: { activityType: true, status: true } },
        ssaRecords: { where: { deletedAt: null }, orderBy: { dateOfSsa: 'desc' }, take: 1 },
      },
    });

    const sections: Record<string, { label: string; schools: unknown[] }> = {
      missingSsa: { label: 'Core Schools Missing SSA', schools: [] },
      ready: { label: 'Core Schools Ready for Planning', schools: [] },
      missingVisit1: { label: 'Missing Visit 1', schools: [] }, missingVisit2: { label: 'Missing Visit 2', schools: [] },
      missingVisit3: { label: 'Missing Visit 3', schools: [] }, missingVisit4: { label: 'Missing Visit 4', schools: [] },
      missingTraining1: { label: 'Missing Training 1', schools: [] }, missingTraining2: { label: 'Missing Training 2', schools: [] },
      missingTraining3: { label: 'Missing Training 3', schools: [] }, missingTraining4: { label: 'Missing Training 4', schools: [] },
      fullPackage: { label: 'Full Core Package Complete', schools: [] },
      potentialChampion: { label: 'Potential Champion Schools', schools: [] },
    };

    for (const s of cores) {
      const visits = s.activities.filter((a) => a.activityType === 'core_visit' && a.status === 'completed').length;
      const trainings = s.activities.filter((a) => a.activityType === 'core_training' && a.status === 'completed').length;
      const latest = s.ssaRecords[0];
      const ssaCurrent = s.currentFySsaStatus === 'done';
      const card = {
        schoolId: s.schoolId, name: s.name, district: s.districtId, subCounty: s.subCounty?.name,
        cluster: s.clusterId ? 'clustered' : 'unclustered', owner: s.accountOwner?.user.name,
        ssaStatus: s.currentFySsaStatus, latestSsa: latest?.averageScore ?? null,
        visitProgress: `${visits}/4`, trainingProgress: `${trainings}/4`,
        nextAction: !ssaCurrent ? 'Upload SSA' : visits < 4 ? `Schedule Visit ${visits + 1}` : trainings < 4 ? `Schedule Training ${trainings + 1}` : 'Follow-Up SSA',
      };

      if (!ssaCurrent || !s.clusterId) { sections.missingSsa.schools.push(card); continue; }
      if (visits === 0 && trainings === 0) sections.ready.schools.push(card);
      if (visits < 4) sections[`missingVisit${visits + 1}` as keyof typeof sections].schools.push(card);
      if (trainings < 4) sections[`missingTraining${trainings + 1}` as keyof typeof sections].schools.push(card);
      if (visits >= 4 && trainings >= 4) {
        sections.fullPackage.schools.push(card);
        if ((latest?.averageScore ?? 0) >= 8) sections.potentialChampion.schools.push(card);
      }
    }

    return Object.entries(sections).map(([key, v]) => ({ key, label: v.label, count: v.schools.length, schools: v.schools }));
  }

  /** Plan-builder feed: the role-scoped, clustered + current-FY-SSA, not-yet-
   *  planned schools — ranked weakest-first — plus the clusters they belong to
   *  with live SSA averages and dominant weaknesses. This is the live data
   *  source that replaces the frontend's mock `plan-builder-engine` arrays. */
  async planBuilder(user: AuthUser, f: Filters) {
    const base = await this.baseWhere(user, f);
    const where: Prisma.SchoolWhereInput = {
      ...base, ...NO_ACTIVE_PLAN, clusterStatus: 'clustered', currentFySsaStatus: 'done',
    };
    const rows = await this.prisma.school.findMany({
      where, take: 400, orderBy: { name: 'asc' },
      include: {
        district: { select: { name: true } },
        cluster: { select: { id: true, name: true } },
        subCounty: { select: { name: true } },
        accountOwner: { include: { user: { select: { name: true } } } },
        ssaRecords: { where: { deletedAt: null }, orderBy: { dateOfSsa: 'desc' }, take: 1, include: { scores: true } },
      },
    });

    const schools = rows.map((s) => {
      const weakest = this.weakestFor(s as unknown as SchoolWithSsa);
      return {
        schoolId: s.schoolId, name: s.name, schoolType: s.schoolType,
        district: s.district?.name ?? '', clusterId: s.clusterId, cluster: s.cluster?.name ?? '',
        subCounty: s.subCounty?.name ?? null, owner: s.accountOwner?.user.name ?? null,
        ssaScore: s.ssaRecords[0]?.averageScore ?? null,
        weakest, weakestArea: weakest[0]?.label ?? null, secondWeakArea: weakest[1]?.label ?? null,
        planningReadiness: s.planningReadiness, stage: this.readiness.stageFor(s),
      };
    });
    // Weakest-first: lowest average SSA leads, missing average sinks to the end.
    schools.sort((a, b) => (a.ssaScore ?? 99) - (b.ssaScore ?? 99) || a.name.localeCompare(b.name));

    // Group the same live rows into cluster recommendations — avg SSA + the
    // dominant (lowest-average) intervention across the cluster's schools.
    type Group = { id: string; name: string; district: string; count: number; scores: number[]; weak: Map<string, { sum: number; n: number; label: string }> };
    const byCluster = new Map<string, Group>();
    for (const s of rows) {
      if (!s.clusterId || !s.cluster) continue;
      const g = byCluster.get(s.clusterId) ?? { id: s.clusterId, name: s.cluster.name, district: s.district?.name ?? '', count: 0, scores: [] as number[], weak: new Map<string, { sum: number; n: number; label: string }>() };
      g.count += 1;
      const latest = s.ssaRecords[0];
      if (latest?.averageScore != null) g.scores.push(Number(latest.averageScore));
      for (const sc of latest?.scores ?? []) {
        const e = g.weak.get(sc.intervention) ?? { sum: 0, n: 0, label: INTERVENTION_LABEL[sc.intervention] ?? sc.intervention };
        e.sum += sc.score; e.n += 1; g.weak.set(sc.intervention, e);
      }
      byCluster.set(s.clusterId, g);
    }
    const clusters = [...byCluster.values()].map((g) => {
      const averageSsa = g.scores.length ? Math.round((g.scores.reduce((a, b) => a + b, 0) / g.scores.length) * 10) / 10 : null;
      let weakest: { intervention: string; label: string; avg: number } | null = null;
      for (const [intervention, e] of g.weak) {
        const avg = e.sum / e.n;
        if (!weakest || avg < weakest.avg) weakest = { intervention, label: e.label, avg: Math.round(avg * 10) / 10 };
      }
      return { clusterId: g.id, clusterName: g.name, district: g.district, schoolCount: g.count, averageSsa, weakest };
    }).sort((a, b) => (a.averageSsa ?? 99) - (b.averageSsa ?? 99));

    return { schools, clusters };
  }

  /** Recalculate a single school's readiness on demand (admin/IA/CD). */
  recompute(schoolId: string) {
    return this.prisma.school.findUnique({ where: { schoolId }, select: { id: true } }).then((s) => {
      if (!s) throw new Error('not found');
      return this.readiness.recompute(s.id);
    });
  }

  // ─── Monthly plan lifecycle (plan-as-list: create → submit → approve) ───

  private actData(a: DraftActivityDto) {
    return {
      kind: a.kind, title: a.title, weekOfMonth: a.weekOfMonth ?? 1,
      scheduledDate: a.scheduledDate, schoolId: a.schoolId, estCostCents: a.estCostCents ?? 0,
      interventionArea: a.interventionArea, deliveryType: a.deliveryType, partnerName: a.partnerName,
    };
  }

  private async recomputePlanTotal(planId: string) {
    const rows = await this.prisma.monthlyPlanActivity.findMany({ where: { monthlyPlanId: planId }, select: { estCostCents: true } });
    const total = rows.reduce((s, r) => s + r.estCostCents, 0);
    await this.prisma.monthlyPlan.update({ where: { id: planId }, data: { totalCostCents: total } });
  }

  /** Create (or return the existing) draft plan for the caller's month, with any seed activities. */
  async createPlan(user: AuthUser, dto: CreatePlanDto) {
    const ownerStaffId = user.staffProfileId;
    if (!ownerStaffId) throw new BadRequestException('No staff profile for this user.');
    const acts = dto.activities ?? [];
    const total = acts.reduce((s, a) => s + (a.estCostCents ?? 0), 0);
    const plan = await this.prisma.monthlyPlan.upsert({
      where: { monthIso_ownerStaffId: { monthIso: dto.monthIso, ownerStaffId } },
      update: acts.length ? { totalCostCents: { increment: total }, activities: { create: acts.map((a) => this.actData(a)) } } : {},
      create: {
        monthIso: dto.monthIso, ownerStaffId, ownerName: user.name, status: 'draft', totalCostCents: total,
        activities: { create: acts.map((a) => this.actData(a)) },
      },
      include: { activities: true },
    });
    return plan;
  }

  private async ownedPlanOr403(user: AuthUser, planId: string) {
    const plan = await this.prisma.monthlyPlan.findUnique({ where: { id: planId } });
    if (!plan) throw new NotFoundException('Plan not found');
    if (plan.ownerStaffId !== user.staffProfileId && user.activeRole !== 'Admin') throw new ForbiddenException('Not your plan');
    return plan;
  }

  async addActivity(user: AuthUser, planId: string, a: DraftActivityDto) {
    await this.ownedPlanOr403(user, planId);
    const act = await this.prisma.monthlyPlanActivity.create({ data: { monthlyPlanId: planId, ...this.actData(a) } });
    await this.recomputePlanTotal(planId);
    return act;
  }

  async submitPlan(user: AuthUser, planId: string) {
    await this.ownedPlanOr403(user, planId);
    return this.prisma.monthlyPlan.update({ where: { id: planId }, data: { status: 'submitted', submittedAt: new Date(), returnedReason: null } });
  }

  async approvePlan(user: AuthUser, planId: string) {
    if (!APPROVER_ROLES.has(user.activeRole)) throw new ForbiddenException('Only a Program Lead / CD can approve.');
    const plan = await this.prisma.monthlyPlan.findUnique({ where: { id: planId } });
    if (!plan) throw new NotFoundException('Plan not found');
    return this.prisma.monthlyPlan.update({ where: { id: planId }, data: { status: 'approved', approvedAt: new Date(), approvedById: user.userId } });
  }

  async returnPlan(user: AuthUser, planId: string, reason: string) {
    if (!APPROVER_ROLES.has(user.activeRole)) throw new ForbiddenException('Only a Program Lead / CD can return.');
    const plan = await this.prisma.monthlyPlan.findUnique({ where: { id: planId } });
    if (!plan) throw new NotFoundException('Plan not found');
    return this.prisma.monthlyPlan.update({ where: { id: planId }, data: { status: 'returned', returnedReason: reason } });
  }

  /** Own plans (everyone) + the approval queue (approvers see all submitted/approved). */
  async listPlans(user: AuthUser) {
    const isApprover = APPROVER_ROLES.has(user.activeRole);
    const where: Prisma.MonthlyPlanWhereInput = isApprover
      ? { OR: [{ ownerStaffId: user.staffProfileId ?? '__none__' }, { status: { in: ['submitted', 'approved', 'returned', 'active'] } }] }
      : { ownerStaffId: user.staffProfileId ?? '__none__' };
    const plans = await this.prisma.monthlyPlan.findMany({
      where, orderBy: { updatedAt: 'desc' }, take: 200,
      include: { _count: { select: { activities: true } } },
    });
    return plans.map((p) => ({
      id: p.id, monthIso: p.monthIso, ownerStaffId: p.ownerStaffId, ownerName: p.ownerName,
      status: p.status, totalCostCents: p.totalCostCents, activityCount: p._count.activities,
      submittedAt: p.submittedAt, approvedAt: p.approvedAt, returnedReason: p.returnedReason,
      updatedAt: p.updatedAt,
    }));
  }

  async getPlan(user: AuthUser, planId: string) {
    const plan = await this.prisma.monthlyPlan.findUnique({ where: { id: planId }, include: { activities: { orderBy: { weekOfMonth: 'asc' } } } });
    if (!plan) throw new NotFoundException('Plan not found');
    const isApprover = APPROVER_ROLES.has(user.activeRole);
    if (plan.ownerStaffId !== user.staffProfileId && !isApprover) throw new ForbiddenException('Not visible to you');
    return plan;
  }

  // ── Operational planning workflow (school visits + partner assign + cluster training) ──

  /** Schedule a school visit for staff — trainings are NOT allowed here. */
  async scheduleSchoolVisit(user: AuthUser, dto: ScheduleSchoolVisitDto) {
    return this.activities.create({
      activityType: 'school_visit',
      schoolId: dto.schoolId,
      fy: dto.fy,
      quarter: dto.quarter,
      plannedMonth: dto.plannedMonth,
      plannedWeek: dto.plannedWeek,
      scheduledDate: dto.scheduledDate,
      responsibleStaffId: dto.responsibleStaffId,
      deliveryType: 'staff',
    }, user);
  }

  /** Assign a school visit to a partner — appears in Partner Planning + staff My Plan. */
  async assignSchoolVisitToPartner(user: AuthUser, dto: AssignSchoolVisitToPartnerDto) {
    return this.activities.create({
      activityType: 'school_visit',
      schoolId: dto.schoolId,
      fy: dto.fy,
      quarter: dto.quarter,
      plannedMonth: dto.plannedMonth,
      plannedWeek: dto.plannedWeek,
      assignedPartnerId: dto.assignedPartnerId,
      responsibleStaffId: dto.responsibleStaffId ?? user.staffProfileId ?? undefined,
      deliveryType: 'partner',
    }, user);
  }

  /** Schedule cluster training / SIT / meeting — the ONLY path for trainings. */
  async scheduleClusterTraining(user: AuthUser, dto: ScheduleClusterTrainingDto) {
    const allowed: string[] = ['training', 'school_improvement_training', 'cluster_training', 'core_training', 'cluster_meeting'];
    if (!allowed.includes(dto.activityType)) {
      throw new BadRequestException('Only training and cluster-meeting activity types may be scheduled through a cluster.');
    }
    const isPartner = dto.deliveryType === 'partner' || !!dto.assignedPartnerId;
    return this.activities.create({
      activityType: dto.activityType,
      clusterId: dto.clusterId,
      fy: dto.fy,
      quarter: dto.quarter,
      plannedMonth: dto.plannedMonth,
      plannedWeek: dto.plannedWeek,
      scheduledDate: dto.scheduledDate,
      clusterSlot: dto.clusterSlot,
      assignedPartnerId: dto.assignedPartnerId,
      deliveryType: isPartner ? 'partner' : 'staff',
    }, user);
  }
}

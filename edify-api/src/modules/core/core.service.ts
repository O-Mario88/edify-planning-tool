import {
  BadRequestException, ForbiddenException, Injectable, NotFoundException,
} from '@nestjs/common';
import { EdifyRole, Prisma, SsaIntervention } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { ScopeService } from '../../common/scope/scope.service';
import { AuditService } from '../../common/audit/audit.service';
import { AuthUser } from '../../common/auth/auth-user';
import { SsaService } from '../ssa/ssa.service';
import { UploadFollowUpSsaDto } from './dto/core.dto';
import {
  ALL_INTERVENTIONS, CORE_SSA_THRESHOLD, INTERVENTION_LABEL, interventionsFromScores, VISITS_TARGET, TRAININGS_TARGET,
} from './core-interventions';
import { computeImpact, scoresFromSsaRows } from './core-impact';

import { computePlanProgress, recomputeCounters } from './core-progress';

const VERIFY_ROLES = new Set<EdifyRole>(['ImpactAssessment', 'CountryDirector', 'CountryProgramLead', 'CCEO', 'Admin']);
const ONBOARD_ROLES = new Set<EdifyRole>(['CountryDirector', 'CountryProgramLead', 'ImpactAssessment', 'Admin']);
const ASSIGN_ROLES = new Set<EdifyRole>(['CCEO', 'CountryProgramLead', 'Admin']);
const EXEC_ROLES = new Set<EdifyRole>(['CCEO', 'CountryProgramLead', 'PartnerAdmin', 'PartnerFieldOfficer', 'Admin']);
const REVIEW_ROLES = new Set<EdifyRole>(['CCEO', 'CountryProgramLead', 'CountryDirector', 'ProjectCoordinator', 'Admin']);
const IA_ROLES = new Set<EdifyRole>(['ImpactAssessment', 'Admin']);
const PL_ROLES = new Set<EdifyRole>(['CountryProgramLead', 'Admin']);
const ACCT_ROLES = new Set<EdifyRole>(['ProgramAccountant', 'Admin']);

const CHAMPION_FLOW: Partial<Record<string, { roles: Set<EdifyRole>; next: string; schoolType?: 'champion' }>> = {
  'Potential Champion': { roles: IA_ROLES, next: 'Under Review' },
  'Under Review': { roles: IA_ROLES, next: 'IA Verified' },
  'IA Verified': { roles: PL_ROLES, next: 'PL Recommended' },
  'PL Recommended': { roles: new Set(['CountryDirector', 'Admin']), next: 'CD Approved' },
  'CD Approved': { roles: new Set(['CountryDirector', 'Admin']), next: 'Verified Champion', schoolType: 'champion' },
  'Verified Champion': { roles: new Set(['CountryDirector', 'Admin']), next: 'Champion Mentor School' },
};

type PlanWithRelations = Prisma.CorePlanGetPayload<{
  include: {
    slots: true;
    profile: true;
    onboarding: true;
  };
}>;

type StoredInterventionJson = { area: SsaIntervention; label: string; rank: number; baselineScore: number };

type SchoolCardContext = {
  name: string;
  schoolId: string;
  accountOwnerNameRaw?: string | null;
  district?: { name: string } | null;
  cluster?: { name: string } | null;
  accountOwner?: { user?: { name: string } | null } | null;
};

@Injectable()
export class CoreService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly scope: ScopeService,
    private readonly audit: AuditService,
    private readonly ssa: SsaService,
  ) {}

  private assertRole(user: AuthUser, allowed: Set<EdifyRole>) {
    if (!allowed.has(user.activeRole)) throw new ForbiddenException('Your role cannot perform this action.');
  }

  private async schoolInScope(schoolId: string, user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const school = await this.prisma.school.findFirst({
      where: { schoolId, deletedAt: null, ...this.scope.schoolWhere(scope) },
      include: {
        district: { select: { name: true } },
        region: { select: { name: true } },
        cluster: { select: { name: true } },
        accountOwner: { include: { user: { select: { name: true } } } },
      },
    });
    if (!school) throw new NotFoundException('School not found or outside your scope');
    return school;
  }

  /** Potential Core candidates — client schools with latest SSA avg ≥ 7.5. */
  async listCandidates(user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const schools = await this.prisma.school.findMany({
      where: {
        deletedAt: null,
        schoolType: { in: ['client', 'potential_core'] },
        ...this.scope.schoolWhere(scope),
      },
      include: {
        district: { select: { name: true } },
        region: { select: { name: true } },
        cluster: { select: { name: true } },
        accountOwner: { include: { user: { select: { name: true } } } },
        ssaRecords: {
          where: { deletedAt: null },
          orderBy: { dateOfSsa: 'desc' },
          take: 1,
          include: { scores: true },
        },
      },
      take: 500,
    });

    const verifications = await this.prisma.coreCandidateVerification.findMany({
      where: { schoolId: { in: schools.map((s) => s.schoolId) } },
    });
    const verBySchool = new Map(verifications.map((v) => [v.schoolId, v]));
    const onboarded = new Set(
      (await this.prisma.corePlan.findMany({ select: { schoolId: true } })).map((p) => p.schoolId),
    );

    return schools
      .filter((s) => {
        if (onboarded.has(s.schoolId)) return false;
        const latest = s.ssaRecords[0];
        return latest && (latest.averageScore ?? 0) >= CORE_SSA_THRESHOLD;
      })
      .map((s) => {
        const latest = s.ssaRecords[0]!;
        const sorted = [...latest.scores].sort((a, b) => a.score - b.score);
        const v = verBySchool.get(s.schoolId);
        let candidateStatus = 'Candidate';
        if (v?.status === 'Verified Potential Core') candidateStatus = 'Verified Potential Core';
        else if (v?.status === 'Rejected') candidateStatus = 'Rejected Candidate';
        else if (v) candidateStatus = 'Verification Submitted';
        return {
          schoolId: s.schoolId,
          schoolName: s.name,
          district: s.district?.name ?? '',
          region: s.region?.name ?? '',
          cluster: s.cluster?.name ?? undefined,
          accountOwnerName: s.accountOwner?.user?.name ?? s.accountOwnerNameRaw ?? undefined,
          enrollment: s.enrollment ?? undefined,
          currentSchoolType: s.schoolType,
          ssaRecordId: latest.id,
          fy: latest.fy,
          averageScore: latest.averageScore ?? 0,
          bestInterventions: [...latest.scores].sort((a, b) => b.score - a.score).slice(0, 2)
            .map((x) => ({ area: INTERVENTION_LABEL[x.intervention], score: x.score })),
          weakestInterventions: sorted.slice(0, 2)
            .map((x) => ({ area: INTERVENTION_LABEL[x.intervention], score: x.score })),
          candidateStatus,
          verificationId: v?.verificationId,
          recommendedOnboardingMonth: 'October',
          recommendedOnboardingFy: latest.fy,
        };
      });
  }

  async verifyCandidate(user: AuthUser, schoolId: string, verificationId: string, comments?: string) {
    this.assertRole(user, VERIFY_ROLES);
    const vid = verificationId?.trim() ?? '';
    if (vid.length < 3) throw new BadRequestException('Verification ID is required.');
    const school = await this.schoolInScope(schoolId, user);
    const latest = await this.prisma.ssaRecord.findFirst({
      where: { schoolId: school.id, deletedAt: null },
      orderBy: { dateOfSsa: 'desc' },
    });
    if (!latest || (latest.averageScore ?? 0) < CORE_SSA_THRESHOLD) {
      throw new BadRequestException('School does not have a qualifying SSA on record.');
    }
    const existing = await this.prisma.coreCandidateVerification.findUnique({ where: { schoolId } });
    if (existing) throw new BadRequestException('This school was already verified or rejected.');

    await this.prisma.coreCandidateVerification.create({
      data: {
        schoolId,
        ssaRecordId: latest.id,
        verificationId: vid,
        verifiedById: user.userId,
        verifiedByName: user.name,
        status: 'Verified Potential Core',
        comments,
      },
    });
    if (school.schoolType === 'client') {
      await this.prisma.school.update({ where: { id: school.id }, data: { schoolType: 'potential_core' } });
    }
    await this.audit.log({
      action: 'core.candidateVerified', subjectKind: 'School', subjectId: school.id,
      actorId: user.userId, actorRole: user.activeRole, payload: { verificationId: vid },
    });
    return { ok: true, schoolId };
  }

  async rejectCandidate(user: AuthUser, schoolId: string, reason: string) {
    this.assertRole(user, ONBOARD_ROLES);
    if ((reason?.trim() ?? '').length < 5) throw new BadRequestException('A reason of at least 5 characters is required.');
    const school = await this.schoolInScope(schoolId, user);
    const latest = await this.prisma.ssaRecord.findFirst({
      where: { schoolId: school.id, deletedAt: null },
      orderBy: { dateOfSsa: 'desc' },
    });
    if (!latest) throw new NotFoundException('No SSA on record for this school.');
    const existing = await this.prisma.coreCandidateVerification.findUnique({ where: { schoolId } });
    if (existing) throw new BadRequestException('This school was already verified or rejected.');

    await this.prisma.coreCandidateVerification.create({
      data: {
        schoolId,
        ssaRecordId: latest.id,
        verificationId: '—',
        verifiedById: user.userId,
        verifiedByName: user.name,
        status: 'Rejected',
        comments: reason.trim(),
      },
    });
    await this.audit.log({
      action: 'core.candidateRejected', subjectKind: 'School', subjectId: school.id,
      actorId: user.userId, actorRole: user.activeRole, payload: { reason: reason.trim() },
    });
    return { ok: true, schoolId };
  }

  /** Onboard a verified candidate → Core plan + 8 slots + profile. */
  async onboard(user: AuthUser, schoolId: string, reason?: string) {
    this.assertRole(user, ONBOARD_ROLES);
    const school = await this.schoolInScope(schoolId, user);
    if (school.schoolType === 'core') throw new BadRequestException('School is already a Core school.');
    const verification = await this.prisma.coreCandidateVerification.findUnique({ where: { schoolId } });
    if (!verification || verification.status !== 'Verified Potential Core') {
      throw new BadRequestException('School must be verified as Potential Core before onboarding.');
    }
    const existingPlan = await this.prisma.corePlan.findUnique({ where: { schoolId } });
    if (existingPlan) throw new BadRequestException('A core plan already exists for this school.');

    const baseline = await this.prisma.ssaRecord.findUnique({
      where: { id: verification.ssaRecordId },
      include: { scores: true },
    });
    if (!baseline) throw new NotFoundException('Baseline SSA record not found.');

    const interventions = interventionsFromScores(
      baseline.scores.map((s) => ({ intervention: s.intervention, score: s.score })),
    );
    const planId = `cplan-${schoolId}`;
    const now = new Date();
    const fy = baseline.fy;

    await this.prisma.$transaction(async (tx) => {
      await tx.school.update({ where: { id: school.id }, data: { schoolType: 'core' } });
      await tx.corePlan.create({
        data: {
          id: planId,
          schoolId,
          fy,
          status: 'Active',
          baselineSsaRecordId: baseline.id,
          baselineAverage: baseline.averageScore ?? undefined,
          followUpAverage: undefined,
          interventions: interventions as unknown as Prisma.InputJsonValue,
          createdById: user.userId,
          createdByName: user.name,
        },
      });
      await tx.coreSchoolProfile.create({
        data: {
          id: `cprof-${schoolId}`,
          schoolId,
          corePlanId: planId,
          coreStartFy: fy,
          championStatus: 'Not Eligible',
        },
      });
      await tx.coreSchoolOnboarding.create({
        data: {
          schoolId,
          corePlanId: planId,
          fy,
          previousSchoolType: school.schoolType,
          baselineSsaRecordId: baseline.id,
          baselineAverageScore: baseline.averageScore ?? 0,
          onboardedById: user.userId,
          onboardedByName: user.name,
          onboardingReason: reason?.trim() || 'Verified Potential Core — onboarded.',
        },
      });
      for (const type of ['visit', 'training'] as const) {
        for (let n = 1; n <= 4; n++) {
          const inter = interventions[(n - 1) % interventions.length];
          await tx.coreActivitySlot.create({
            data: {
              id: `cslot-${schoolId}-${type[0]}${n}`,
              corePlanId: planId,
              schoolId,
              intervention: inter.label,
              activityType: type,
              sequenceNumber: n,
              status: 'Not Planned',
              owner: 'unassigned',
            },
          });
        }
      }
    });

    await this.audit.log({
      action: 'core.schoolOnboarded', subjectKind: 'CorePlan', subjectId: planId,
      actorId: user.userId, actorRole: user.activeRole,
      payload: { schoolId, baselineAverage: baseline.averageScore, fy },
    });
    return { ok: true, schoolId, planId };
  }

  /** Role-scoped core plan board (planning console). */
  async listPlans(user: AuthUser) {
    const scope = await this.scope.resolveUserScope(user);
    const schoolWhere = this.scope.schoolWhere(scope);
    const plans = await this.prisma.corePlan.findMany({
      where: {
        slots: { some: {} },
        ...(scope.countryScope || scope.canViewSummaryOnly
          ? {}
          : { schoolId: { in: (await this.prisma.school.findMany({ where: { deletedAt: null, ...schoolWhere }, select: { schoolId: true } })).map((s) => s.schoolId) } }),
      },
      include: {
        slots: true,
        profile: true,
        onboarding: true,
      },
      orderBy: { updatedAt: 'desc' },
      take: 200,
    });

    const schoolIds = plans.map((p) => p.schoolId);
    const schools = await this.prisma.school.findMany({
      where: { schoolId: { in: schoolIds } },
      include: {
        district: { select: { name: true } },
        cluster: { select: { name: true } },
        accountOwner: { include: { user: { select: { name: true } } } },
      },
    });
    const schoolById = new Map(schools.map((s) => [s.schoolId, s]));

    const cards = await Promise.all(plans.map(async (p) => this.mapPlanCard(p, schoolById.get(p.schoolId))));
    return cards;
  }

  /** Full lifecycle detail for one core school. */
  async getDetail(user: AuthUser, schoolId: string) {
    await this.schoolInScope(schoolId, user);
    const plan = await this.prisma.corePlan.findUnique({
      where: { schoolId },
      include: { slots: true, profile: true, onboarding: true },
    });
    const school = await this.prisma.school.findUnique({
      where: { schoolId },
      include: {
        district: { select: { name: true } },
        region: { select: { name: true } },
        cluster: { select: { name: true } },
        accountOwner: { include: { user: { select: { name: true } } } },
      },
    });
    if (!school) throw new NotFoundException('School not found');

    const verification = await this.prisma.coreCandidateVerification.findUnique({ where: { schoolId } });
    let baselineSsa = plan?.baselineSsaRecordId
      ? await this.prisma.ssaRecord.findUnique({ where: { id: plan.baselineSsaRecordId }, include: { scores: true } })
      : null;
    let followUpSsa = plan?.followUpSsaRecordId
      ? await this.prisma.ssaRecord.findUnique({ where: { id: plan.followUpSsaRecordId }, include: { scores: true } })
      : null;

    const interventions = (plan?.interventions as StoredInterventionJson[] | null) ?? [];
    const progress = plan ? computePlanProgress(plan.slots) : undefined;
    const impactRaw = plan && baselineSsa && followUpSsa
      ? computeImpact(
        scoresFromSsaRows(baselineSsa.scores),
        scoresFromSsaRows(followUpSsa.scores),
        baselineSsa.averageScore ?? 0,
        followUpSsa.averageScore ?? 0,
        interventions.map((i) => ({ area: i.area, label: i.label, rank: i.rank, baselineScore: i.baselineScore })),
      )
      : undefined;
    const impact = impactRaw && plan && baselineSsa && followUpSsa
      ? {
        id: `cimp-${plan.id}`,
        corePlanId: plan.id,
        schoolId,
        baselineSSARecordId: baselineSsa.id,
        followUpSSARecordId: followUpSsa.id,
        ...impactRaw,
      }
      : undefined;

    const timeline: { at: string; label: string; detail?: string }[] = [];
    if (verification) timeline.push({ at: verification.verifiedAt.toISOString(), label: `Verified — ${verification.status}`, detail: `SSA Verification ID ${verification.verificationId}` });
    if (plan?.onboarding) timeline.push({ at: plan.onboarding.onboardedAt.toISOString(), label: 'Onboarded as Core', detail: `Baseline SSA ${plan.onboarding.baselineAverageScore.toFixed(1)}` });
    if (plan) timeline.push({ at: plan.createdAt.toISOString(), label: 'Core plan created', detail: '4 priority interventions · 4 visits + 4 trainings' });
    for (const s of plan?.slots ?? []) {
      if (s.completedAt) timeline.push({ at: s.completedAt.toISOString(), label: `${s.activityType === 'visit' ? 'Visit' : 'Training'} ${s.sequenceNumber} completed`, detail: s.salesforceId ? `Salesforce ${s.salesforceId}` : undefined });
    }
    if (followUpSsa) timeline.push({ at: followUpSsa.dateOfSsa.toISOString(), label: 'Follow-Up SSA recorded', detail: `Average ${(followUpSsa.averageScore ?? 0).toFixed(1)}` });
    if (impact) timeline.push({ at: impact.computedAt, label: `Impact measured — ${impact.impactStatus}`, detail: `${impact.averageChange >= 0 ? '+' : ''}${impact.averageChange} avg SSA` });
    timeline.sort((a, b) => a.at.localeCompare(b.at));

    return {
      schoolId,
      schoolName: school.name,
      district: school.district?.name ?? '',
      region: school.region?.name ?? '',
      cluster: school.cluster?.name ?? undefined,
      owner: school.accountOwner?.user?.name ?? school.accountOwnerNameRaw ?? undefined,
      enrollment: school.enrollment ?? undefined,
      isCore: school.schoolType === 'core' || school.schoolType === 'champion',
      profile: plan?.profile ? {
        id: plan.profile.id,
        schoolId,
        activeCorePlanId: plan.id,
        coreStartFy: plan.profile.coreStartFy,
        championStatus: plan.profile.championStatus,
        status: plan.profile.status,
      } : undefined,
      onboarding: plan?.onboarding ? {
        id: plan.onboarding.id,
        schoolId,
        fy: plan.onboarding.fy,
        previousSchoolType: plan.onboarding.previousSchoolType,
        newSchoolType: 'Core',
        baselineSSARecordId: plan.onboarding.baselineSsaRecordId,
        baselineAverageScore: plan.onboarding.baselineAverageScore,
        onboardedById: plan.onboarding.onboardedById,
        onboardedByName: plan.onboarding.onboardedByName,
        onboardedAt: plan.onboarding.onboardedAt.toISOString(),
        onboardingReason: plan.onboarding.onboardingReason ?? undefined,
        status: plan.onboarding.status,
      } : undefined,
      verification: verification ? {
        id: verification.id,
        schoolId,
        ssaRecordId: verification.ssaRecordId,
        verificationId: verification.verificationId,
        verifiedById: verification.verifiedById,
        verifiedByName: verification.verifiedByName,
        verifiedAt: verification.verifiedAt.toISOString(),
        status: verification.status as 'Verified Potential Core' | 'Rejected',
        comments: verification.comments ?? undefined,
      } : undefined,
      plan: plan ? this.mapPlan(plan) : undefined,
      progress,
      baseline: baselineSsa ? this.mapSsaSnapshot(baselineSsa, 'baseline') : undefined,
      followUp: followUpSsa ? this.mapSsaSnapshot(followUpSsa, 'followup') : undefined,
      impact,
      interventions: interventions.map((i, idx) => ({
        id: `cint-${schoolId}-${idx + 1}`,
        corePlanId: plan!.id,
        intervention: i.label,
        baselineScore: i.baselineScore,
        priorityRank: i.rank as 1 | 2 | 3 | 4,
        selectedById: plan!.createdById ?? '',
        selectedAt: plan!.createdAt.toISOString(),
      })),
      visits: (plan?.slots ?? []).filter((s) => s.activityType === 'visit').sort((a, b) => a.sequenceNumber - b.sequenceNumber).map((s) => this.mapSlot(s)),
      trainings: (plan?.slots ?? []).filter((s) => s.activityType === 'training').sort((a, b) => a.sequenceNumber - b.sequenceNumber).map((s) => this.mapSlot(s)),
      timeline,
      areas: ALL_INTERVENTIONS.map((a) => INTERVENTION_LABEL[a]),
    };
  }

  async slotAction(user: AuthUser, slotId: string, action: string, body: Record<string, unknown> = {}) {
    const slot = await this.prisma.coreActivitySlot.findUnique({ where: { id: slotId }, include: { corePlan: { include: { slots: true } } } });
    if (!slot) throw new NotFoundException('Core slot not found');
    await this.schoolInScope(slot.schoolId, user);

    const patch: Prisma.CoreActivitySlotUpdateInput = {};
    switch (action) {
      case 'assign':
        this.assertRole(user, ASSIGN_ROLES);
        patch.owner = (body.owner as string) ?? 'myself';
        patch.assignedStaffName = body.ownerName as string | undefined;
        patch.assignedPartnerId = body.partnerId as string | undefined;
        patch.assignedPartnerName = body.ownerName as string | undefined;
        patch.scheduledMonth = body.monthLabel as string | undefined;
        patch.scheduledWeek = body.week as number | undefined;
        patch.scheduledFor = body.monthLabel ? `${body.monthLabel}${body.week ? ` · Wk ${body.week}` : ''}` : undefined;
        patch.status = patch.owner === 'partner' ? 'Assigned to Partner' : body.monthLabel ? 'Scheduled' : 'Planned';
        break;
      case 'schedule':
        this.assertRole(user, ASSIGN_ROLES);
        patch.status = 'Scheduled';
        patch.scheduledMonth = body.monthLabel as string;
        patch.scheduledWeek = body.week as number;
        patch.scheduledFor = `${body.monthLabel} · Wk ${body.week}`;
        break;
      case 'start':
        this.assertRole(user, EXEC_ROLES);
        patch.status = 'In Progress';
        break;
      case 'evidence':
        this.assertRole(user, EXEC_ROLES);
        if (!(body.evidenceUri as string)?.trim()) throw new BadRequestException('Evidence URI is required.');
        patch.status = 'Evidence Uploaded';
        patch.evidenceUri = body.evidenceUri as string;
        patch.evidenceNotes = body.notes as string | undefined;
        break;
      case 'acceptEvidence':
        this.assertRole(user, REVIEW_ROLES);
        if (slot.status !== 'Evidence Uploaded') throw new BadRequestException('Slot is not awaiting evidence review.');
        patch.status = 'Evidence Accepted';
        break;
      case 'returnEvidence':
        this.assertRole(user, REVIEW_ROLES);
        patch.status = 'In Progress';
        patch.evidenceNotes = `Returned: ${body.reason}`;
        break;
      case 'complete': {
        this.assertRole(user, EXEC_ROLES);
        const sf = ((body.salesforceId as string) ?? '').trim();
        if (!sf) throw new BadRequestException('Salesforce ID is required.');
        const prefix = slot.activityType === 'visit' ? 'SVE' : 'TS';
        if (!sf.toUpperCase().startsWith(prefix)) {
          throw new BadRequestException(`${slot.activityType === 'visit' ? 'Visit' : 'Training'} Salesforce IDs must start with ${prefix}.`);
        }
        if (slot.assignedPartnerId && slot.status !== 'Evidence Accepted') {
          throw new BadRequestException('Partner evidence must be accepted before completion.');
        }
        patch.salesforceId = sf;
        patch.teachers = body.teachers as number | undefined;
        patch.leaders = body.leaders as number | undefined;
        patch.participants = body.participants as number | undefined;
        patch.status = 'Awaiting IA Verification';
        patch.iaVerificationStatus = 'Pending';
        if (user.activeRole === 'CCEO' && slot.activityType === 'visit') patch.plVerificationStatus = 'Pending';
        break;
      }
      case 'plVerify':
        this.assertRole(user, PL_ROLES);
        patch.plVerificationStatus = 'Verified';
        break;
      case 'iaVerify':
        this.assertRole(user, IA_ROLES);
        if (slot.status !== 'Awaiting IA Verification') throw new BadRequestException('Slot is not awaiting IA verification.');
        if (slot.plVerificationStatus === 'Pending') throw new BadRequestException('PL sign-off is required first.');
        patch.status = 'Completed';
        patch.iaVerificationStatus = 'Verified';
        patch.completedAt = new Date();
        if (slot.assignedPartnerId) patch.accountantStatus = 'Pending';
        break;
      case 'return':
        this.assertRole(user, IA_ROLES);
        patch.status = 'Returned';
        patch.returnedReason = body.reason as string;
        break;
      case 'accountantConfirm':
        this.assertRole(user, ACCT_ROLES);
        patch.accountantStatus = 'Confirmed';
        break;
      default:
        throw new BadRequestException(`Unknown slot action: ${action}`);
    }

    await this.prisma.coreActivitySlot.update({ where: { id: slotId }, data: patch });
    const plan = await this.prisma.corePlan.findUnique({ where: { id: slot.corePlanId }, include: { slots: true } });
    if (plan) {
      const counters = recomputeCounters(plan.slots);
      let status = plan.status;
      if (counters.visitsCompleted >= VISITS_TARGET && counters.trainingsCompleted >= TRAININGS_TARGET && plan.slots.every((s) => s.status === 'Completed')) {
        status = plan.followUpSsaRecordId ? 'Impact Measured' : 'Completed Pending Follow-Up SSA';
      } else if (counters.visitsCompleted + counters.trainingsCompleted > 0) {
        status = 'In Progress';
      }
      await this.prisma.corePlan.update({
        where: { id: plan.id },
        data: { ...counters, status },
      });
    }

    await this.audit.log({
      action: `core.slot.${action}`, subjectKind: 'CoreActivitySlot', subjectId: slotId,
      actorId: user.userId, actorRole: user.activeRole,
    });
    return { ok: true, slotId };
  }

  async scheduleFollowUp(user: AuthUser, planId: string, assignee: string, monthLabel: string, week?: number) {
    this.assertRole(user, new Set([...ASSIGN_ROLES, ...EXEC_ROLES]));
    const plan = await this.prisma.corePlan.findUnique({ where: { id: planId }, include: { slots: true } });
    if (!plan) throw new NotFoundException('Core plan not found');
    const progress = computePlanProgress(plan.slots);
    if (!progress.readyForFollowUpSSA) throw new BadRequestException('Core package is not complete yet.');
    await this.prisma.corePlan.update({
      where: { id: planId },
      data: {
        status: 'Follow-Up SSA Scheduled',
        followUpAssignee: assignee,
        followUpScheduledFor: `${monthLabel}${week ? ` · Wk ${week}` : ''}`,
      },
    });
    return { ok: true, planId };
  }

  async uploadFollowUpSsa(user: AuthUser, planId: string, dto: UploadFollowUpSsaDto) {
    this.assertRole(user, IA_ROLES);
    const plan = await this.prisma.corePlan.findUnique({ where: { id: planId }, include: { profile: true, slots: true } });
    if (!plan) throw new NotFoundException('Core plan not found');
    if (plan.followUpSsaRecordId) throw new BadRequestException('Follow-up SSA already recorded.');
    const progress = computePlanProgress(plan.slots);
    if (!progress.readyForFollowUpSSA) throw new BadRequestException('Core package must be complete before follow-up SSA.');

    const record = await this.ssa.upload({
      schoolId: plan.schoolId,
      dateOfSsa: dto.dateOfSsa ?? new Date().toISOString(),
      scores: dto.scores,
    }, user);

    const baseline = plan.baselineSsaRecordId
      ? await this.prisma.ssaRecord.findUnique({ where: { id: plan.baselineSsaRecordId }, include: { scores: true } })
      : null;
    const interventions = (plan.interventions as StoredInterventionJson[] | null) ?? [];
    const impact = baseline
      ? computeImpact(
        scoresFromSsaRows(baseline.scores),
        scoresFromSsaRows(record.scores),
        baseline.averageScore ?? 0,
        record.averageScore ?? 0,
        interventions.map((i) => ({ area: i.area, label: i.label, rank: i.rank, baselineScore: i.baselineScore })),
      )
      : null;

    await this.prisma.corePlan.update({
      where: { id: planId },
      data: {
        followUpSsaRecordId: record.id,
        followUpAverage: record.averageScore ?? undefined,
        status: impact?.championCandidate ? 'Champion Candidate' : 'Impact Measured',
      },
    });
    if (plan.profile && impact?.championCandidate) {
      await this.prisma.coreSchoolProfile.update({
        where: { id: plan.profile.id },
        data: { championStatus: 'Potential Champion' },
      });
    }

    await this.audit.log({
      action: 'core.followUpSsaUploaded', subjectKind: 'CorePlan', subjectId: planId,
      actorId: user.userId, actorRole: user.activeRole,
      payload: { averageChange: impact?.averageChange, championCandidate: impact?.championCandidate },
    });
    return { ok: true, planId, averageChange: impact?.averageChange ?? 0, championCandidate: !!impact?.championCandidate };
  }

  async advanceChampion(user: AuthUser, schoolId: string) {
    const plan = await this.prisma.corePlan.findUnique({ where: { schoolId }, include: { profile: true } });
    if (!plan?.profile) throw new NotFoundException('Core profile not found.');
    const step = CHAMPION_FLOW[plan.profile.championStatus];
    if (!step) throw new BadRequestException('No further champion transition available.');
    this.assertRole(user, step.roles);

    await this.prisma.coreSchoolProfile.update({
      where: { id: plan.profile.id },
      data: { championStatus: step.next },
    });
    if (step.schoolType === 'champion') {
      const school = await this.prisma.school.findUnique({ where: { schoolId } });
      if (school) await this.prisma.school.update({ where: { id: school.id }, data: { schoolType: 'champion' } });
      await this.prisma.corePlan.update({ where: { id: plan.id }, data: { status: 'Champion Verified' } });
    }
    await this.audit.log({
      action: 'core.championAdvanced', subjectKind: 'School', subjectId: schoolId,
      actorId: user.userId, actorRole: user.activeRole, payload: { to: step.next },
    });
    return { ok: true, schoolId, status: step.next };
  }

  // ── mappers ────────────────────────────────────────────────────────

  private mapPlan(plan: PlanWithRelations) {
    const counters = recomputeCounters(plan.slots);
    return {
      id: plan.id,
      schoolId: plan.schoolId,
      fy: plan.fy,
      baselineSSARecordId: plan.baselineSsaRecordId ?? '',
      followUpSSARecordId: plan.followUpSsaRecordId ?? undefined,
      status: plan.status,
      visitsTarget: plan.visitsTarget,
      trainingsTarget: plan.trainingsTarget,
      visitsCompleted: counters.visitsCompleted,
      trainingsCompleted: counters.trainingsCompleted,
      packageCompletionPercent: counters.packageCompletionPercent,
      followUpScheduledFor: plan.followUpScheduledFor ?? undefined,
      followUpAssignee: plan.followUpAssignee ?? undefined,
      createdById: plan.createdById ?? '',
      createdByName: plan.createdByName ?? '',
      createdAt: plan.createdAt.toISOString(),
      updatedAt: plan.updatedAt.toISOString(),
    };
  }

  private mapSlot(s: Prisma.CoreActivitySlotGetPayload<object>) {
    return {
      id: s.id,
      corePlanId: s.corePlanId,
      schoolId: s.schoolId,
      intervention: s.intervention,
      activityType: s.activityType as 'visit' | 'training',
      sequenceNumber: s.sequenceNumber as 1 | 2 | 3 | 4,
      status: s.status,
      owner: s.owner,
      assignedStaffId: s.assignedStaffId ?? undefined,
      assignedStaffName: s.assignedStaffName ?? undefined,
      assignedPartnerId: s.assignedPartnerId ?? undefined,
      assignedPartnerName: s.assignedPartnerName ?? undefined,
      activityId: s.activityId ?? undefined,
      plVerificationStatus: s.plVerificationStatus as 'Pending' | 'Verified' | undefined,
      scheduledFor: s.scheduledFor ?? undefined,
      scheduledMonth: s.scheduledMonth ?? undefined,
      scheduledWeek: s.scheduledWeek ?? undefined,
      evidenceUri: s.evidenceUri ?? undefined,
      evidenceNotes: s.evidenceNotes ?? undefined,
      salesforceId: s.salesforceId ?? undefined,
      teachers: s.teachers ?? undefined,
      leaders: s.leaders ?? undefined,
      participants: s.participants ?? undefined,
      iaVerificationStatus: s.iaVerificationStatus as 'Pending' | 'Verified' | 'Rejected' | undefined,
      accountantStatus: s.accountantStatus as 'Pending' | 'Confirmed' | undefined,
      returnedReason: s.returnedReason ?? undefined,
      completedAt: s.completedAt?.toISOString(),
      createdAt: s.createdAt.toISOString(),
      updatedAt: s.updatedAt.toISOString(),
    };
  }

  private mapSsaSnapshot(
    rec: Prisma.SsaRecordGetPayload<{ include: { scores: true } }>,
    kind: 'baseline' | 'followup' | 'candidate',
  ) {
    const scores: Record<string, number> = {};
    for (const s of rec.scores) scores[INTERVENTION_LABEL[s.intervention]] = s.score;
    return {
      id: rec.id,
      schoolId: '',
      kind,
      fy: rec.fy,
      date: rec.dateOfSsa.toISOString().slice(0, 10),
      scores,
      average: rec.averageScore ?? 0,
    };
  }

  private async mapPlanCard(plan: PlanWithRelations, school?: SchoolCardContext | null) {
    const progress = computePlanProgress(plan.slots);
    let impact;
    if (plan.baselineSsaRecordId && plan.followUpSsaRecordId) {
      const [baseline, followUp] = await Promise.all([
        this.prisma.ssaRecord.findUnique({ where: { id: plan.baselineSsaRecordId }, include: { scores: true } }),
        this.prisma.ssaRecord.findUnique({ where: { id: plan.followUpSsaRecordId }, include: { scores: true } }),
      ]);
      const interventions = (plan.interventions as StoredInterventionJson[] | null) ?? [];
      if (baseline && followUp) {
        impact = computeImpact(
          scoresFromSsaRows(baseline.scores),
          scoresFromSsaRows(followUp.scores),
          baseline.averageScore ?? 0,
          followUp.averageScore ?? 0,
          interventions.map((i) => ({ area: i.area, label: i.label, rank: i.rank, baselineScore: i.baselineScore })),
        );
      }
    }
    const interventions = (plan.interventions as StoredInterventionJson[] | null) ?? [];
    return {
      plan: this.mapPlan(plan),
      schoolName: school?.name ?? plan.schoolId,
      district: school?.district?.name ?? '—',
      cluster: school?.cluster?.name ?? undefined,
      owner: school?.accountOwner?.user?.name ?? school?.accountOwnerNameRaw ?? undefined,
      baselineAverage: plan.baselineAverage ?? 0,
      championStatus: plan.profile?.championStatus ?? 'Not Eligible',
      progress,
      interventions: interventions.map((i, idx) => ({
        id: `cint-${plan.schoolId}-${idx + 1}`,
        corePlanId: plan.id,
        intervention: i.label,
        baselineScore: i.baselineScore,
        priorityRank: i.rank as 1 | 2 | 3 | 4,
        selectedById: plan.createdById ?? '',
        selectedAt: plan.createdAt.toISOString(),
      })),
      slots: plan.slots.map((s) => this.mapSlot(s)),
      impact,
    };
  }
}

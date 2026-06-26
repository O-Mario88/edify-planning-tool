import { BadRequestException, ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../../prisma/prisma.service';
import { AuditService } from '../../common/audit/audit.service';
import { DomainEventService, type NotifySpec } from '../../common/realtime/domain-events.service';
import { ScopeService } from '../../common/scope/scope.service';
import { AuthUser } from '../../common/auth/auth-user';

const PL_ROLES = new Set(['CountryProgramLead', 'CountryDirector', 'Admin']);

@Injectable()
export class PlReviewService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
    private readonly events: DomainEventService,
    private readonly scope: ScopeService,
  ) {}

  async queue(user: AuthUser) {
    if (!PL_ROLES.has(user.activeRole)) throw new ForbiddenException('PL review queue is for Program Leads and Directors');
    const scope = await this.scope.resolveUserScope(user);
    const schoolWhere = scope.countryScope ? {} : this.scope.schoolWhere(scope);
    const schools = await this.prisma.school.findMany({ where: { deletedAt: null, ...schoolWhere }, select: { id: true } });
    const schoolIds = schools.map((s) => s.id);

    const items = await this.prisma.activity.findMany({
      where: {
        deletedAt: null,
        status: 'submitted_to_pl',
        OR: [
          { schoolId: { in: schoolIds.length ? schoolIds : ['__none__'] } },
          { clusterId: { not: null } },
        ],
      },
      orderBy: { updatedAt: 'desc' },
      take: 100,
      include: {
        school: { select: { schoolId: true, name: true } },
        cluster: { select: { name: true } },
        responsibleStaff: { select: { user: { select: { name: true } } } },
        evidence: { where: { quarantined: false }, select: { id: true, kind: true, status: true, originalName: true } },
      },
    });

    return { items };
  }

  async confirm(id: string, user: AuthUser) {
    if (!PL_ROLES.has(user.activeRole)) throw new ForbiddenException('Only a Program Lead may confirm');
    const a = await this.prisma.activity.findUnique({ where: { id } });
    if (!a) throw new NotFoundException('Activity not found');
    if (a.status !== 'submitted_to_pl') throw new BadRequestException('Activity is not awaiting PL review');
    if (!a.salesforceActivityId) throw new BadRequestException('Activity Code is required before PL confirmation');
    if (a.evidenceStatus !== 'accepted' && a.evidenceStatus !== 'uploaded') {
      throw new BadRequestException('Evidence must be uploaded before PL confirmation');
    }

    const updated = await this.prisma.activity.update({
      where: { id },
      data: {
        status: 'awaiting_ia_verification',
        plReviewedAt: new Date(),
        plReviewedBy: user.userId,
        plReviewNote: null,
        evidenceStatus: a.evidenceStatus === 'uploaded' ? 'accepted' : a.evidenceStatus,
      },
    });

    await this.audit.log({
      action: 'activity.pl_confirmed', subjectKind: 'Activity', subjectId: id,
      actorId: user.userId, actorRole: user.activeRole,
    });

    const iaUserIds = await this.events.usersWithRole('ImpactAssessment');
    const notify: NotifySpec[] = iaUserIds.map((rid) => ({
      recipientId: rid,
      title: `${a.salesforceActivityId} ready for IA verification`,
      body: 'A CCEO completion was confirmed by the Program Lead.',
      targetRoute: '/queue',
      actionRequired: true,
      priority: 'high' as const,
    }));
    await this.events.emit({
      type: 'PLReviewConfirmed',
      actorId: user.userId, actorRole: user.activeRole, subjectKind: 'Activity', subjectId: id,
      notify,
      liveUserIds: [user.userId, ...iaUserIds],
    });

    return updated;
  }

  async return(id: string, reason: string, user: AuthUser) {
    if (!PL_ROLES.has(user.activeRole)) throw new ForbiddenException('Only a Program Lead may return');
    if (!reason?.trim() || reason.trim().length < 5) throw new BadRequestException('A return reason is required');
    const a = await this.prisma.activity.findUnique({ where: { id } });
    if (!a) throw new NotFoundException('Activity not found');
    if (a.status !== 'submitted_to_pl') throw new BadRequestException('Activity is not awaiting PL review');

    const updated = await this.prisma.activity.update({
      where: { id },
      data: {
        status: 'returned_by_pl',
        plReviewNote: reason.trim(),
        plReviewedAt: new Date(),
        plReviewedBy: user.userId,
      },
    });

    await this.audit.log({
      action: 'activity.pl_returned', subjectKind: 'Activity', subjectId: id,
      actorId: user.userId, actorRole: user.activeRole, payload: { reason: reason.trim() },
    });

    const staffUserId = a.responsibleStaffId ? await this.events.userForStaff(a.responsibleStaffId) : null;
    if (staffUserId) {
      await this.events.emit({
        type: 'PLReviewReturned',
        actorId: user.userId, actorRole: user.activeRole, subjectKind: 'Activity', subjectId: id,
        notify: [{
          recipientId: staffUserId,
          title: 'Activity returned for correction',
          body: reason.trim(),
          targetRoute: '/my-plan',
          actionRequired: true,
          priority: 'high' as const,
        }],
        liveUserIds: [user.userId, staffUserId],
      });
    }

    return updated;
  }
}

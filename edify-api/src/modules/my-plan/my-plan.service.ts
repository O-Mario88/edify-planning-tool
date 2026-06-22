import { Injectable } from '@nestjs/common';
import { PrismaService } from '../../prisma/prisma.service';
import { ScopeService } from '../../common/scope/scope.service';
import { AuthUser } from '../../common/auth/auth-user';
import { getOperationalFY, getQuarterForDate } from '../../common/fy/fy.util';
import { costForActivity, RateCard } from '../budget/costing';

export type MyPlanPeriod = 'week' | 'month' | 'quarter' | 'fy';

const ACTIVE = [
  'planned', 'scheduled', 'rescheduled', 'assigned_to_partner', 'partner_scheduled',
  'in_progress', 'completion_started', 'evidence_uploaded', 'evidence_accepted',
  'salesforce_id_required', 'submitted_to_pl', 'returned_by_pl', 'awaiting_ia_verification',
  'returned', 'deferred',
] as const;

@Injectable()
export class MyPlanService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly scope: ScopeService,
  ) {}

  private weekOf(d: Date): number {
    const start = new Date(d.getFullYear(), 0, 1);
    return Math.ceil(((d.getTime() - start.getTime()) / 86400000 + start.getDay() + 1) / 7);
  }

  private periodKey(a: { scheduledDate: Date | null; plannedWeek?: number | null; fy: string; quarter: string }, period: MyPlanPeriod, now: Date): string {
    if (period === 'fy') return a.fy;
    if (period === 'quarter') return `${a.fy}:${a.quarter}`;
    const d = a.scheduledDate ?? now;
    if (period === 'month') return `${a.fy}:${d.getMonth() + 1}`;
    return `${a.fy}:W${a.plannedWeek ?? this.weekOf(d)}`;
  }

  async get(user: AuthUser, opts: { period?: MyPlanPeriod; fy?: string } = {}) {
    const period = opts.period ?? 'month';
    const fy = opts.fy ?? getOperationalFY();
    const now = new Date();
    if (!user.staffProfileId) return { live: true, period, fy, groups: [], summary: { total: 0, costCents: 0 } };

    const rates: RateCard = {};
    for (const r of await this.prisma.costSetting.findMany({ select: { key: true, unitCost: true } })) {
      rates[r.key] = r.unitCost;
    }

    const activities = await this.prisma.activity.findMany({
      where: {
        deletedAt: null,
        responsibleStaffId: user.staffProfileId,
        fy,
        status: { in: [...ACTIVE] as never },
      },
      orderBy: [{ scheduledDate: 'asc' }, { createdAt: 'desc' }],
      include: {
        school: { select: { schoolId: true, name: true, district: { select: { name: true } } } },
        cluster: { select: { name: true } },
        assignedPartner: { select: { name: true } },
        scheduleCostLines: true,
      },
    });

    const rows = activities.map((a) => {
      const cost = a.estCostCents > 0
        ? { amount: a.estCostCents, costMissing: a.costMissing }
        : costForActivity({ activityType: a.activityType, deliveryType: a.deliveryType }, rates);
      return {
        id: a.id,
        activityType: a.activityType,
        status: a.status,
        evidenceStatus: a.evidenceStatus,
        deliveryType: a.deliveryType,
        scheduledDate: a.scheduledDate,
        plannedWeek: a.plannedWeek,
        plannedMonth: a.plannedMonth,
        quarter: a.quarter,
        fy: a.fy,
        school: a.school,
        cluster: a.cluster,
        partner: a.assignedPartner,
        salesforceActivityId: a.salesforceActivityId,
        estCostCents: cost.amount,
        costMissing: 'costMissing' in cost ? cost.costMissing : a.costMissing,
        rescheduleCount: a.rescheduleCount,
        periodKey: this.periodKey(a, period, now),
        canReschedule: !['completed', 'cancelled', 'ia_verified', 'accountant_confirmed'].includes(a.status),
        canComplete: ['planned', 'scheduled', 'rescheduled', 'partner_scheduled', 'in_progress', 'completion_started', 'evidence_uploaded', 'evidence_accepted', 'salesforce_id_required'].includes(a.status),
        completionUnlocked: ['completion_started', 'in_progress', 'evidence_uploaded', 'evidence_accepted', 'salesforce_id_required', 'submitted_to_pl', 'awaiting_ia_verification'].includes(a.status),
      };
    });

    const currentKey = this.periodKey({ scheduledDate: now, fy, quarter: getQuarterForDate(now), plannedWeek: this.weekOf(now) }, period, now);
    const groups = new Map<string, typeof rows>();
    for (const r of rows) {
      const k = r.periodKey;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k)!.push(r);
    }

    return {
      live: true,
      period,
      fy,
      currentKey,
      summary: {
        total: rows.length,
        costCents: rows.reduce((s, r) => s + r.estCostCents, 0),
        partnerPlanned: rows.filter((r) => r.deliveryType === 'partner').length,
      },
      groups: Array.from(groups.entries())
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, items]) => ({ key, label: key, items, isCurrent: key === currentKey })),
      items: rows,
    };
  }
}

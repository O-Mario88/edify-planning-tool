import { BadRequestException, Injectable } from '@nestjs/common';
import { ActivityStatus, Prisma } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { ScopeService, UserScope } from '../../common/scope/scope.service';
import { AuthUser } from '../../common/auth/auth-user';
import { getOperationalFY, getQuarterForDate, type Quarter } from '../../common/fy/fy.util';
import { AuditService } from '../../common/audit/audit.service';
import { costForActivity, RateCard, CostableActivity, resolveActivityCost, type SnapshotCostLine } from './costing';

// ── Budget = the schedule, costed ────────────────────────────────────────────
// There is NO manual budget building for program activities. The budget is the
// caller's scheduled activities, each auto-costed from the CD rate card, rolled
// up to week / month / quarter / year. Weekly = "what you need next; the
// monthly roll-up is the country fund request. Busy/slow months fall straight
// out of the monthly distribution (spec §11–§14).

// Statuses that represent committed/planned work that needs funding. Anything
// cancelled/rejected/not-yet-planned is excluded from the budget.
const BUDGETABLE_STATUSES: ActivityStatus[] = [
  ActivityStatus.planned,
  ActivityStatus.scheduled,
  ActivityStatus.rescheduled,
  ActivityStatus.assigned_to_partner,
  ActivityStatus.partner_scheduled,
  ActivityStatus.in_progress,
  ActivityStatus.completion_started,
  ActivityStatus.evidence_uploaded,
  ActivityStatus.evidence_accepted,
  ActivityStatus.salesforce_id_required,
  ActivityStatus.submitted_to_pl,
  ActivityStatus.returned_by_pl,
  ActivityStatus.awaiting_ia_verification,
  ActivityStatus.ia_verified,
  ActivityStatus.accountant_confirmed,
  ActivityStatus.completed,
];

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const QMONTHS: Record<Quarter, number[]> = { Q1: [10, 11, 12], Q2: [1, 2, 3], Q3: [4, 5, 6], Q4: [7, 8, 9] };

const VISIT_TYPES = new Set([
  'school_visit', 'follow_up_visit', 'coaching_visit', 'in_school_support', 'core_visit',
]);
const TRAINING_TYPES = new Set(['training', 'school_improvement_training', 'core_training']);

type BudgetLens = 'week' | 'month' | 'quarter' | 'year';

const ROLE_SHORT: Record<string, string> = {
  CCEO: 'CCEO',
  CountryProgramLead: 'PL',
  CountryDirector: 'CD',
  ImpactAssessment: 'IA',
  ProgramAccountant: 'Accountant',
  RegionalVicePresident: 'RVP',
  Admin: 'Admin',
};

@Injectable()
export class BudgetService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly scope: ScopeService,
    private readonly audit: AuditService,
  ) {}

  // ── Rate card ──────────────────────────────────────────────────────────────

  /** The full rate card (CD-owned). Visible to anyone who can plan. */
  async listCostSettings() {
    const rows = await this.prisma.costSetting.findMany({ orderBy: { key: 'asc' } });
    return {
      settings: rows.map((r) => ({
        id: r.id,
        key: r.key,
        label: r.label,
        unitCost: r.unitCost,
        fy: r.fy,
        version: r.version,
        updatedAt: r.updatedAt,
      })),
      count: rows.length,
    };
  }

  /** CD upserts a single rate by key. Guarded by COST_SETTINGS_MANAGE at the
   *  controller — this is the only way official costs are set. */
  async upsertCostSetting(user: AuthUser, body: { key?: string; label?: string; unitCost?: number; fy?: string; reason?: string }) {
    const key = (body.key ?? '').trim();
    if (!key) throw new BadRequestException('key is required');
    if (typeof body.unitCost !== 'number' || body.unitCost < 0)
      throw new BadRequestException('unitCost must be a non-negative number');
    const label = (body.label ?? key).trim();

    // Versioned register: bump the version on a real rate change and append an
    // immutable history row (old→new, who, when, why). Past budgets keep their
    // snapshotted ActivityBudgetLine.unitCost, so they never change retroactively.
    const existing = await this.prisma.costSetting.findUnique({ where: { key } });
    const changed = !existing || existing.unitCost !== body.unitCost;
    const version = existing ? existing.version + (changed ? 1 : 0) : 1;

    const saved = await this.prisma.costSetting.upsert({
      where: { key },
      create: { key, label, unitCost: body.unitCost, fy: body.fy ?? null, version: 1, createdBy: user.userId },
      update: { label, unitCost: body.unitCost, version, ...(body.fy !== undefined ? { fy: body.fy } : {}) },
    });

    if (changed) {
      await this.prisma.costSettingHistory.create({
        data: {
          key, label, oldUnitCost: existing?.unitCost ?? null, newUnitCost: body.unitCost,
          version, fy: saved.fy, changedByUserId: user.userId, reason: body.reason?.trim() || null,
        },
      });
      await this.audit.log({
        action: 'costRegister.rateChanged', subjectKind: 'CostSetting', subjectId: saved.id,
        actorId: user.userId, actorRole: user.activeRole,
        payload: { key, oldUnitCost: existing?.unitCost ?? null, newUnitCost: body.unitCost, version, reason: body.reason ?? null },
      });
    }
    return { ok: true, setting: { id: saved.id, key: saved.key, label: saved.label, unitCost: saved.unitCost, version: saved.version } };
  }

  /** Versioned change history for one rate (or the whole register). */
  async costSettingHistory(key?: string) {
    const rows = await this.prisma.costSettingHistory.findMany({
      where: key ? { key } : {}, orderBy: { changedAt: 'desc' }, take: 200,
    });
    return { history: rows, count: rows.length };
  }

  private async rateCard(): Promise<RateCard> {
    const rows = await this.prisma.costSetting.findMany({ select: { key: true, unitCost: true } });
    const card: RateCard = {};
    for (const r of rows) card[r.key] = r.unitCost;
    return card;
  }

  /** Cost preview for the scheduling drawer — the exact lines + total the CD
   *  rate card (Country Cost Register) produces for an activity BEFORE it is
   *  scheduled. Source of truth = official CostSetting rates; no manual cost.
   *  A missing rate surfaces costMissing so the UI can warn + block fund use. */
  async costPreview(input: {
    activityType?: string; deliveryType?: string; districtType?: string;
    teachersAttended?: number; leadersAttended?: number; otherParticipants?: number;
  }) {
    if (!input.activityType) throw new BadRequestException('activityType is required for a cost preview.');
    const rates = await this.rateCard();
    const cost = costForActivity(
      {
        activityType: input.activityType as CostableActivity['activityType'],
        deliveryType: (input.deliveryType ?? 'staff') as CostableActivity['deliveryType'],
        districtType: input.districtType,
        teachersAttended: input.teachersAttended,
        leadersAttended: input.leadersAttended,
        otherParticipants: input.otherParticipants,
      },
      rates,
    );
    return {
      source: `Uganda · FY ${getOperationalFY()} Country Cost Register`,
      currency: 'UGX',
      amount: cost.amount,
      costMissing: cost.costMissing,
      lines: cost.lines,
    };
  }

  private resolveCost(
    a: CostableActivity & { estCostCents?: number | null; costMissing?: boolean | null },
    rates: RateCard,
    snapshotLines?: SnapshotCostLine[],
  ) {
    return resolveActivityCost(a, rates, snapshotLines);
  }

  // ── Activity scope (own work + work in own schools) ─────────────────────────

  /** Budget reads: country roles + RVP see the full country schedule. */
  private budgetActivityWhere(scope: UserScope): Prisma.ActivityWhereInput {
    const base: Prisma.ActivityWhereInput = {
      deletedAt: null,
      status: { in: BUDGETABLE_STATUSES },
    };
    if (scope.countryScope || scope.canViewSummaryOnly) return base;
    return this.activityWhere(scope);
  }

  private activityWhere(scope: UserScope): Prisma.ActivityWhereInput {
    const base: Prisma.ActivityWhereInput = {
      deletedAt: null,
      status: { in: BUDGETABLE_STATUSES },
    };
    if (scope.countryScope) return base;
    const staffIds = [...scope.staffIds, ...scope.supervisedStaffIds];
    const or: Prisma.ActivityWhereInput[] = [];
    if (staffIds.length) or.push({ responsibleStaffId: { in: staffIds } });
    if (scope.schoolIds.length) or.push({ schoolId: { in: scope.schoolIds } });
    if (!or.length) return { ...base, id: '__none__' };
    return { ...base, OR: or };
  }

  // ── The budget, built from the schedule ─────────────────────────────────────

  /**
   * The caller's full scheduled-work budget for an FY, auto-costed and rolled up
   * by month (→ busy/slow), activity type, and delivery (staff/partner). This is
   * the one read that powers weekly fund requests, the monthly country request,
   * and quarterly/annual summaries — the period param just changes the lens.
   */
  async fromSchedule(user: AuthUser, opts: { fy?: string } = {}) {
    const scope = await this.scope.resolveUserScope(user);
    const fy = opts.fy || getOperationalFY();
    const rates = await this.rateCard();

    const activities = await this.prisma.activity.findMany({
      where: { ...this.activityWhere(scope), fy },
      select: {
        id: true,
        activityType: true,
        deliveryType: true,
        status: true,
        estCostCents: true,
        costMissing: true,
        quarter: true,
        month: true,
        plannedMonth: true,
        scheduledDate: true,
        teachersAttended: true,
        leadersAttended: true,
        otherParticipants: true,
        school: { select: { schoolType: true } },
        scheduleCostLines: {
          select: { label: true, costSettingKey: true, unitCost: true, quantity: true, amount: true },
        },
      },
    });

    // Per-month accumulators (busy/slow), per-type, per-delivery, totals.
    const byMonth = MONTHS.map((m, i) => ({ month: i + 1, label: m, amount: 0, count: 0, trainings: 0 }));
    const byType = new Map<string, { amount: number; count: number }>();
    const byDelivery = { staff: { amount: 0, count: 0 }, partner: { amount: 0, count: 0 } };
    let total = 0;
    let costMissingCount = 0;

    for (const a of activities) {
      const costable: CostableActivity = {
        activityType: a.activityType,
        deliveryType: a.deliveryType,
        teachersAttended: a.teachersAttended,
        leadersAttended: a.leadersAttended,
        otherParticipants: a.otherParticipants,
      };
      const cost = this.resolveCost(
        { ...costable, estCostCents: a.estCostCents, costMissing: a.costMissing },
        rates,
        a.scheduleCostLines,
      );
      if (cost.costMissing) costMissingCount += 1;
      total += cost.amount;

      const mIdx = this.monthIndexOf(a);
      if (mIdx != null) {
        byMonth[mIdx].amount += cost.amount;
        byMonth[mIdx].count += 1;
        if (/training/.test(a.activityType)) byMonth[mIdx].trainings += 1;
      }

      const t = byType.get(a.activityType) ?? { amount: 0, count: 0 };
      t.amount += cost.amount;
      t.count += 1;
      byType.set(a.activityType, t);

      const d = a.deliveryType === 'partner' ? byDelivery.partner : byDelivery.staff;
      d.amount += cost.amount;
      d.count += 1;
    }

    // Busy/slow are judged against the average of the MONTHS that carry work —
    // using month-attributed spend only (activities with no schedule month are
    // in `total` but cannot be placed on the calendar).
    const monthsWithWork = byMonth.filter((m) => m.count > 0);
    const attributedTotal = monthsWithWork.reduce((s, m) => s + m.amount, 0);
    const avg = monthsWithWork.length ? attributedTotal / monthsWithWork.length : 0;
    // Busy = clearly above the active-month average; slow = has work but well below.
    const busyMonths = byMonth
      .filter((m) => m.count > 0 && m.amount > avg * 1.4)
      .map((m) => ({ ...m, insight: `${m.label} is overloaded: ${m.count} activities · ${ugx(m.amount)}` }));
    const slowMonths = byMonth
      .filter((m) => m.count > 0 && m.amount < avg * 0.5)
      .map((m) => ({ ...m, insight: `${m.label} is under-planned: only ${m.count} activities · ${ugx(m.amount)}` }));

    return {
      live: true,
      fy,
      role: scope.activeRole,
      scope: scope.countryScope ? 'country' : scope.canViewTeam ? 'team' : 'own',
      total,
      activityCount: activities.length,
      costMissingCount,
      scheduledTotal: attributedTotal,
      unscheduledCount: activities.length - monthsWithWork.reduce((s, m) => s + m.count, 0),
      unscheduledAmount: total - attributedTotal,
      byMonth,
      byQuarter: this.rollQuarters(byMonth),
      byType: Array.from(byType.entries())
        .map(([type, v]) => ({ type, ...v }))
        .sort((a, b) => b.amount - a.amount),
      byDelivery,
      busyMonths,
      slowMonths,
      avgMonthlyCost: Math.round(avg),
    };
  }

  /**
   * Per-activity cost breakdown for a period — the exact rows that make up a
   * fund request total, each priced from the CD rate card (the cost catalogue).
   * This is what an approver expands to verify the rule "every cost of an
   * activity comes from the plan and the cost catalogue." fy + optional
   * month/quarter narrow to the request's period.
   */
  async breakdown(user: AuthUser, opts: { fy?: string; month?: number; quarter?: string } = {}) {
    const scope = await this.scope.resolveUserScope(user);
    const fy = opts.fy || getOperationalFY();
    const rates = await this.rateCard();
    const q = opts.quarter?.toUpperCase();
    // Edify FY quarters (1-indexed months): Q1 Oct–Dec, Q2 Jan–Mar, Q3 Apr–Jun,
    // Q4 Jul–Sep — must match common/fy/fy.util.ts (was shifted one quarter).
    const QMONTHS: Record<string, number[]> = { Q1: [10, 11, 12], Q2: [1, 2, 3], Q3: [4, 5, 6], Q4: [7, 8, 9] };

    const activities = await this.prisma.activity.findMany({
      where: { ...this.activityWhere(scope), fy },
      select: {
        id: true, activityType: true, deliveryType: true, status: true,
        estCostCents: true, costMissing: true,
        quarter: true, month: true, plannedMonth: true, scheduledDate: true,
        teachersAttended: true, leadersAttended: true, otherParticipants: true,
        school: { select: { name: true, schoolType: true } },
        cluster: { select: { name: true } },
        scheduleCostLines: {
          select: { label: true, costSettingKey: true, unitCost: true, quantity: true, amount: true },
        },
      },
    });

    const rows = activities
      .map((a) => ({ a, month: this.monthNumberOf(a) }))
      .filter(({ month }) => {
        if (opts.month != null) return month === opts.month;
        if (q) return month != null && (QMONTHS[q]?.includes(month) ?? false);
        return true;
      })
      .map(({ a, month }) => {
        const cost = this.resolveCost(
          {
            activityType: a.activityType,
            deliveryType: a.deliveryType,
            teachersAttended: a.teachersAttended,
            leadersAttended: a.leadersAttended,
            otherParticipants: a.otherParticipants,
            estCostCents: a.estCostCents,
            costMissing: a.costMissing,
          },
          rates,
          a.scheduleCostLines,
        );
        return {
          id: a.id,
          activityType: a.activityType,
          deliveryType: a.deliveryType,
          target: a.school?.name ?? a.cluster?.name ?? 'cluster',
          month,
          amount: cost.amount,
          costMissing: cost.costMissing,
          lines: cost.lines.map((l) => ({ label: l.label, qty: l.qty, unit: l.unit, amount: l.amount, missing: l.missing })),
        };
      })
      .sort((x, y) => y.amount - x.amount);

    return { fy, activities: rows, total: rows.reduce((s, r) => s + r.amount, 0), count: rows.length };
  }

  /**
   * Weekly fund request — the operational view for CCEO/PL. The activities
   * scheduled for a given ISO week, each line-item costed, with the total the
   * caller should request. Defaults to the current FY's upcoming scheduled work
   * grouped by (week-of-month) when exact dates are sparse.
   */
  async weekly(user: AuthUser, opts: { fy?: string; month?: number } = {}) {
    const scope = await this.scope.resolveUserScope(user);
    const fy = opts.fy || getOperationalFY();
    const rates = await this.rateCard();

    const activities = await this.prisma.activity.findMany({
      where: { ...this.activityWhere(scope), fy },
      select: {
        id: true,
        activityType: true,
        deliveryType: true,
        status: true,
        estCostCents: true,
        costMissing: true,
        month: true,
        plannedMonth: true,
        plannedWeek: true,
        week: true,
        scheduledDate: true,
        quarter: true,
        teachersAttended: true,
        leadersAttended: true,
        otherParticipants: true,
        paymentStatus: true,
        iaVerificationStatus: true,
        school: { select: { name: true, schoolType: true, district: { select: { name: true } } } },
        cluster: { select: { name: true } },
        responsibleStaff: { select: { user: { select: { name: true } } } },
        assignedPartner: { select: { name: true } },
        scheduleCostLines: {
          select: { label: true, costSettingKey: true, unitCost: true, quantity: true, amount: true },
        },
      },
      orderBy: [{ scheduledDate: 'asc' }, { plannedWeek: 'asc' }],
    });

    const monthFilter = opts.month ?? null;
    const lines = activities
      .filter((a) => monthFilter == null || this.monthNumberOf(a) === monthFilter)
      .map((a) => {
        const cost = this.resolveCost(
          {
            activityType: a.activityType,
            deliveryType: a.deliveryType,
            teachersAttended: a.teachersAttended,
            leadersAttended: a.leadersAttended,
            otherParticipants: a.otherParticipants,
            estCostCents: a.estCostCents,
            costMissing: a.costMissing,
          },
          rates,
          a.scheduleCostLines,
        );
        return {
          id: a.id,
          activityType: a.activityType,
          deliveryType: a.deliveryType,
          status: a.status,
          month: this.monthNumberOf(a),
          week: a.plannedWeek ?? a.week ?? null,
          scheduledDate: a.scheduledDate,
          place: a.school?.name ?? a.cluster?.name ?? '—',
          district: a.school?.district?.name ?? null,
          staff: a.responsibleStaff?.user?.name ?? null,
          partner: a.assignedPartner?.name ?? null,
          amount: cost.amount,
          costMissing: cost.costMissing,
          lines: cost.lines,
          paymentStatus: a.paymentStatus,
          iaVerificationStatus: a.iaVerificationStatus,
        };
      });

    // Group into weeks (month*10 + week) for the request rows.
    const weeks = new Map<string, { key: string; month: number | null; week: number | null; amount: number; count: number }>();
    for (const l of lines) {
      const key = `${l.month ?? 0}-${l.week ?? 0}`;
      const g = weeks.get(key) ?? { key, month: l.month, week: l.week, amount: 0, count: 0 };
      g.amount += l.amount;
      g.count += 1;
      weeks.set(key, g);
    }

    return {
      live: true,
      fy,
      role: scope.activeRole,
      total: lines.reduce((s, l) => s + l.amount, 0),
      count: lines.length,
      costMissingCount: lines.filter((l) => l.costMissing).length,
      weeks: Array.from(weeks.values()).sort((a, b) => (a.month! - b.month!) || (a.week! - b.week!)),
      lines,
    };
  }

  /**
   * Monthly budget template board — grouped activity rows by category, period
   * lens (week / month / quarter / year), and summary KPIs (this week, next week,
   * this month, etc.). Powers the role-aware budget dashboard UI.
   */
  async board(
    user: AuthUser,
    opts: { fy?: string; lens?: string; month?: number; quarter?: string; week?: number } = {},
  ) {
    const scope = await this.scope.resolveUserScope(user);
    const fy = opts.fy || getOperationalFY();
    const lens = (['week', 'month', 'quarter', 'year'].includes(opts.lens ?? '')
      ? opts.lens
      : 'month') as BudgetLens;
    const rates = await this.rateCard();
    const now = new Date();
    const currentMonth = now.getUTCMonth() + 1;
    const currentWeek = this.weekOfMonth(now);
    const currentQuarter = getQuarterForDate(now);

    const activities = await this.prisma.activity.findMany({
      where: { ...this.budgetActivityWhere(scope), fy },
      select: {
        id: true,
        activityType: true,
        deliveryType: true,
        estCostCents: true,
        costMissing: true,
        month: true,
        plannedMonth: true,
        plannedWeek: true,
        week: true,
        scheduledDate: true,
        teachersAttended: true,
        leadersAttended: true,
        otherParticipants: true,
        responsibleStaff: {
          select: { user: { select: { name: true, roles: true } } },
        },
        assignedPartner: { select: { name: true } },
        scheduleCostLines: {
          select: { label: true, costSettingKey: true, unitCost: true, quantity: true, amount: true },
        },
      },
    });

    type Costed = {
      activityType: string;
      month: number | null;
      week: number | null;
      amount: number;
      costMissing: boolean;
      schoolCount: number;
      responsible: string;
      unitCost: number | null;
      category: string;
      activityLabel: string;
    };

    const costed: Costed[] = activities.map((a) => {
      const cost = this.resolveCost(
        {
          activityType: a.activityType,
          deliveryType: a.deliveryType,
          teachersAttended: a.teachersAttended,
          leadersAttended: a.leadersAttended,
          otherParticipants: a.otherParticipants,
          estCostCents: a.estCostCents,
          costMissing: a.costMissing,
        },
        rates,
        a.scheduleCostLines,
      );
      const schoolCount = this.schoolCountFor(a);
      const unitLine = cost.lines.find((l) => !l.missing && l.unit != null);
      const unitCost = unitLine?.unit ?? (schoolCount > 0 ? Math.round(cost.amount / schoolCount) : null);
      return {
        activityType: a.activityType,
        month: this.monthNumberOf(a),
        week: a.plannedWeek ?? a.week ?? (a.scheduledDate ? this.weekOfMonth(a.scheduledDate) : null),
        amount: cost.amount,
        costMissing: cost.costMissing,
        schoolCount,
        responsible: this.responsibleLabel(a),
        unitCost,
        category: this.activityCategory(a.activityType),
        activityLabel: titleCaseActivity(a.activityType),
      };
    });

    const sum = (rows: Costed[]) => rows.reduce((s, r) => s + r.amount, 0);

    const thisWeekRows = costed.filter((r) => r.month === currentMonth && (r.week ?? 1) === currentWeek);
    const nextWeekNum = currentWeek >= 4 ? 1 : currentWeek + 1;
    const nextWeekMonth = currentWeek >= 4 ? (currentMonth === 12 ? 1 : currentMonth + 1) : currentMonth;
    const nextWeekRows = costed.filter((r) => r.month === nextWeekMonth && (r.week ?? 1) === nextWeekNum);
    const thisMonthRows = costed.filter((r) => r.month === currentMonth);
    const thisQuarterRows = costed.filter(
      (r) => r.month != null && QMONTHS[currentQuarter].includes(r.month),
    );

    const targetMonth = opts.month ?? currentMonth;
    const targetQuarter = (opts.quarter?.toUpperCase() as Quarter) || currentQuarter;
    const targetWeek = opts.week ?? currentWeek;

    const periodRows = costed.filter((r) => {
      if (lens === 'year') return true;
      if (lens === 'month') return r.month === targetMonth;
      if (lens === 'quarter') {
        return r.month != null && QMONTHS[targetQuarter]?.includes(r.month);
      }
      // week
      const wMonth = opts.month ?? currentMonth;
      return r.month === wMonth && (r.week ?? 1) === targetWeek;
    });

    // Group rows: category → activity+responsible
    const groupMap = new Map<string, {
      category: string;
      activity: string;
      responsible: string;
      schoolCount: number;
      total: number;
      unitCost: number | null;
      costMissing: boolean;
    }>();

    for (const r of periodRows) {
      const key = `${r.category}|${r.activityLabel}|${r.responsible}`;
      const g = groupMap.get(key) ?? {
        category: r.category,
        activity: r.activityLabel,
        responsible: r.responsible,
        schoolCount: 0,
        total: 0,
        unitCost: r.unitCost,
        costMissing: false,
      };
      g.schoolCount += r.schoolCount;
      g.total += r.amount;
      if (r.costMissing) g.costMissing = true;
      if (g.unitCost == null && r.unitCost != null) g.unitCost = r.unitCost;
      groupMap.set(key, g);
    }

    const categories = new Map<string, typeof groupMap extends Map<string, infer V> ? V[] : never>();
    for (const g of groupMap.values()) {
      const list = categories.get(g.category) ?? [];
      list.push(g);
      categories.set(g.category, list);
    }

    const categoryOrder = [
      'School Visits', 'Training', 'Cluster Activities', 'SSA Activities',
      'Special Projects', 'Partner Delivery', 'Other Activities',
    ];

    let rowIndex = 0;
    const grouped = categoryOrder
      .filter((cat) => categories.has(cat))
      .map((category) => ({
        category,
        rows: (categories.get(category) ?? [])
          .sort((a, b) => b.total - a.total)
          .map((r) => {
            rowIndex += 1;
            const unitCost = r.unitCost ?? (r.schoolCount > 0 ? Math.round(r.total / r.schoolCount) : null);
            return {
              index: rowIndex,
              activity: r.activity,
              schoolCount: r.schoolCount,
              responsible: r.responsible,
              unitCost,
              total: r.total,
              costMissing: r.costMissing,
            };
          }),
      }));

    const byType = new Map<string, number>();
    for (const r of periodRows) {
      byType.set(r.category, (byType.get(r.category) ?? 0) + r.amount);
    }
    const periodTotal = sum(periodRows);
    const byCategory = Array.from(byType.entries())
      .map(([label, amount]) => ({
        label,
        amount,
        pct: periodTotal > 0 ? Math.round((amount / periodTotal) * 1000) / 10 : 0,
      }))
      .sort((a, b) => b.amount - a.amount);

    const byMonth = MONTHS.map((label, i) => {
      const month = i + 1;
      const rows = costed.filter((r) => r.month === month);
      return { month, label, amount: sum(rows), count: rows.length };
    });

    const lensLabel =
      lens === 'week'
        ? `Week ${targetWeek} · ${MONTHS[targetMonth - 1]} FY${fy}`
        : lens === 'month'
          ? `${MONTHS[targetMonth - 1]} FY${fy}`
          : lens === 'quarter'
            ? `${targetQuarter} FY${fy}`
            : `FY ${fy}`;

    const viewMode =
      scope.canViewSummaryOnly
        ? 'country_summary'
        : scope.countryScope
          ? 'country'
          : scope.canViewTeam
            ? 'team'
            : 'own';

    return {
      live: true,
      fy,
      role: scope.activeRole,
      scope: scope.countryScope || scope.canViewSummaryOnly ? 'country' : scope.canViewTeam ? 'team' : 'own',
      viewMode,
      lens,
      lensLabel,
      period: { month: targetMonth, quarter: targetQuarter, week: targetWeek },
      summary: {
        thisWeek: sum(thisWeekRows),
        nextWeek: sum(nextWeekRows),
        thisMonth: sum(thisMonthRows),
        thisQuarter: sum(thisQuarterRows),
        fiscalYear: sum(costed),
        periodTotal,
        activityCount: periodRows.length,
        costMissingCount: periodRows.filter((r) => r.costMissing).length,
      },
      grouped,
      byCategory,
      byMonth,
      workflow: [
        { step: 1, label: 'Plan & cost from catalogue', detail: 'Staff schedule activities; costs auto-calculated from the Country Cost Register.' },
        { step: 2, label: 'CCEO → PL review', detail: 'CCEO plans route to their Program Lead for fund approval.' },
        { step: 3, label: 'PL / IA / Accountant → CD', detail: 'PL, IA, and Accountant plans route to the Country Director.' },
        { step: 4, label: 'CD approval + admin cost', detail: 'CD approves the plan and budget, then adds administrative costs.' },
        { step: 5, label: 'RVP final approval', detail: 'Consolidated country budget goes to RVP for final sign-off.' },
      ],
    };
  }

  // ── helpers ──────────────────────────────────────────────────────────────

  private activityCategory(type: string): string {
    if (VISIT_TYPES.has(type)) return 'School Visits';
    if (TRAINING_TYPES.has(type)) return 'Training';
    if (type.startsWith('cluster_')) return 'Cluster Activities';
    if (type === 'ssa_activity') return 'SSA Activities';
    if (type === 'project_activity') return 'Special Projects';
    if (type === 'partner_activity') return 'Partner Delivery';
    return 'Other Activities';
  }

  private schoolCountFor(a: {
    activityType: string;
    teachersAttended?: number | null;
    leadersAttended?: number | null;
    otherParticipants?: number | null;
  }): number {
    if (TRAINING_TYPES.has(a.activityType)) {
      const n = (a.teachersAttended ?? 0) + (a.leadersAttended ?? 0) + (a.otherParticipants ?? 0);
      return n > 0 ? n : 1;
    }
    return 1;
  }

  private responsibleLabel(a: {
    responsibleStaff?: { user?: { name?: string | null; roles?: string[] } | null } | null;
    assignedPartner?: { name?: string | null } | null;
  }): string {
    if (a.assignedPartner?.name) return `${a.assignedPartner.name} (Partner)`;
    const name = a.responsibleStaff?.user?.name ?? 'Unassigned';
    const role = a.responsibleStaff?.user?.roles?.[0] ?? '';
    const short = ROLE_SHORT[role] ?? (role || 'Staff');
    return `${name} (${short})`;
  }

  private weekOfMonth(d: Date): number {
    return Math.min(4, Math.ceil(d.getUTCDate() / 7));
  }

  private monthNumberOf(a: { scheduledDate?: Date | null; month?: number | null; plannedMonth?: number | null }): number | null {
    if (a.scheduledDate) return a.scheduledDate.getMonth() + 1;
    return a.month ?? a.plannedMonth ?? null;
  }
  private monthIndexOf(a: { scheduledDate?: Date | null; month?: number | null; plannedMonth?: number | null }): number | null {
    const m = this.monthNumberOf(a);
    return m == null ? null : m - 1;
  }

  private rollQuarters(byMonth: { month: number; amount: number; count: number }[]) {
    // Edify FY quarters: Q1 Oct–Dec, Q2 Jan–Mar, Q3 Apr–Jun, Q4 Jul–Sep
    // (1-indexed months). Must match common/fy/fy.util.ts.
    const map: Record<string, number[]> = { Q1: [10, 11, 12], Q2: [1, 2, 3], Q3: [4, 5, 6], Q4: [7, 8, 9] };
    return Object.entries(map).map(([q, months]) => {
      const rows = byMonth.filter((m) => months.includes(m.month));
      return { quarter: q, amount: rows.reduce((s, r) => s + r.amount, 0), count: rows.reduce((s, r) => s + r.count, 0) };
    });
  }
}

function titleCaseActivity(s: string): string {
  return s.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

function ugx(n: number): string {
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `UGX ${Math.round(n / 1_000)}K`;
  return `UGX ${Math.round(n)}`;
}

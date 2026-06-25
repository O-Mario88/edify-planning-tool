import { Injectable, Logger } from '@nestjs/common';
import { Cron } from '@nestjs/schedule';
import { Prisma, FundRequestPeriod, FundRequestStatus, MonthlyWorkPlanBudgetStatus } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { AuditService } from '../../common/audit/audit.service';
import { DomainEventService } from '../../common/realtime/domain-events.service';
import { getOperationalFY } from '../../common/fy/fy.util';

// ─────────────────────────── Budget Automation ─────────────────────────────
//
// Two scheduled jobs and their manual-regenerate counterparts:
//
//   • WeeklyFundRequestJob — fires every Friday at 06:00 local. For every
//     staff with planned + costed activities falling into the upcoming
//     Mon–Sun window, UPSERT a draft `FundRequest` (period=weekly) and
//     populate its `FundRequestItem` rows from each costed schedule line.
//     Idempotent: the unique (submittedByUserId, period, periodKey) index
//     prevents duplicate drafts; line-level uniqueness on
//     (costLineId, period, periodKey) prevents the same line entering two
//     active weekly requests.
//
//   • MonthlyWorkPlanBudgetJob — fires on the 25th at 06:00 local. For each
//     country, UPSERT a draft `MonthlyWorkPlanBudget` for next calendar
//     month, computing the program total from all costed schedule lines
//     and emitting one `MonthlyWorkPlanItem` per line. Admin lines are
//     added by the CD before submission to RVP.
//
// Both jobs SKIP requests/envelopes already in approved/disbursed/closed
// states — they only refresh drafts. Activities added after generation
// flagged with `addedAfterGeneration: true` for the late-change banner.

const NON_REFRESH_STATUSES_FR: FundRequestStatus[] = [
  FundRequestStatus.approved,
  FundRequestStatus.approved_by_pl,
  FundRequestStatus.approved_by_cd,
  FundRequestStatus.approved_by_rvp,
  FundRequestStatus.sent_to_accountant,
  FundRequestStatus.disbursed,
  FundRequestStatus.closed,
];

const NON_REFRESH_STATUSES_MWP: MonthlyWorkPlanBudgetStatus[] = [
  MonthlyWorkPlanBudgetStatus.approved_by_rvp,
  MonthlyWorkPlanBudgetStatus.sent_to_accountant,
  MonthlyWorkPlanBudgetStatus.disbursed,
  MonthlyWorkPlanBudgetStatus.closed,
];

@Injectable()
export class BudgetAutomationService {
  private readonly log = new Logger('BudgetAutomation');

  constructor(
    private readonly prisma: PrismaService,
    private readonly audit: AuditService,
    private readonly events: DomainEventService,
  ) {}

  // ── Helpers ────────────────────────────────────────────────────────────

  /** Mon–Sun window for the operational week starting AFTER the next Friday. */
  static upcomingOpWeek(now: Date): { start: Date; end: Date; key: string } {
    // "Upcoming operational week" = the Mon–Sun that includes the Monday
    // after `now`. Running on Friday → next week. Running on Saturday →
    // the immediate next week. Running on Wednesday (manual) → the Mon
    // we already passed if we want THIS week, but the contract here is
    // "the next Mon-Sun starting at or after `now`".
    const dow = now.getDay(); // 0=Sun, 1=Mon, …, 5=Fri, 6=Sat
    // Days until next Monday (1 if today is Sunday, 0 if today is Monday but
    // we want NEXT week, so we add 7 when today === Mon).
    const daysToNextMon = ((1 - dow + 7) % 7) || 7;
    const start = new Date(now);
    start.setDate(start.getDate() + daysToNextMon);
    start.setHours(0, 0, 0, 0);
    const end = new Date(start);
    end.setDate(end.getDate() + 6);
    end.setHours(23, 59, 59, 999);
    // Stable periodKey: "YYYY-Www" ISO-style week. Use start date as the
    // canonical anchor so the unique index is deterministic regardless of
    // timezone wall-clock.
    const key = `${start.getFullYear()}-W${start.toISOString().slice(5, 10).replace('-', '')}`;
    return { start, end, key };
  }

  /** "2026-03" key for the calendar month AFTER `now`. */
  static nextCalendarMonthKey(now: Date): { monthKey: string; start: Date; end: Date } {
    const y = now.getFullYear();
    const m = now.getMonth(); // 0-11
    const start = new Date(y, m + 1, 1, 0, 0, 0, 0);
    const end = new Date(y, m + 2, 0, 23, 59, 59, 999);
    const monthKey = `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}`;
    return { monthKey, start, end };
  }

  // ── Friday Weekly Fund Request Job (idempotent) ────────────────────────

  /** Cron: every Friday at 06:00 local. */
  @Cron('0 6 * * 5', { name: 'WeeklyFundRequestJob' })
  async runWeeklyFundRequestJob() {
    try {
      const out = await this.generateWeeklyFundRequests(new Date(), { actor: 'cron' });
      this.log.log(`WeeklyFundRequestJob: ${out.requestsCreated} created, ${out.requestsRefreshed} refreshed, ${out.skipped} skipped (approved/disbursed)`);
    } catch (err) {
      this.log.error('WeeklyFundRequestJob failed', err as Error);
    }
  }

  /** Manual or scheduled — generate/refresh weekly fund requests for the
   *  Mon–Sun window starting after `now`. Returns summary counts. */
  async generateWeeklyFundRequests(now: Date, opts: { actor: 'cron' | string }) {
    const fy = getOperationalFY();
    const { start, end, key } = BudgetAutomationService.upcomingOpWeek(now);
    // Find all schedule cost lines whose parent activity falls into the window
    // AND is not cancelled/deferred/rejected.
    const lines = await this.prisma.activityScheduleCostLine.findMany({
      where: {
        activity: {
          deletedAt: null,
          scheduledDate: { gte: start, lte: end },
          status: { notIn: ['cancelled', 'rejected', 'deferred', 'not_planned'] },
          costMissing: false, // exclude cost-blocked activities (spec §10)
        },
      },
      include: {
        activity: {
          select: {
            id: true, responsibleStaffId: true,
            responsibleStaff: { select: { userId: true } },
            assignedPartnerId: true,
            scheduledDate: true,
          },
        },
      },
    });

    // Group by submitter (the responsible staff's userId).
    const groups = new Map<string, typeof lines>();
    for (const l of lines) {
      const uid = l.activity.responsibleStaff?.userId;
      if (!uid) continue; // partner-monitored activities without staff owner are skipped
      const arr = groups.get(uid) ?? [];
      arr.push(l);
      groups.set(uid, arr);
    }

    let requestsCreated = 0, requestsRefreshed = 0, skipped = 0;

    for (const [userId, userLines] of groups) {
      // Try to find an existing request for (user, weekly, key) — guaranteed
      // unique by index. If it's in a frozen approved/disbursed state, skip
      // and emit a "late additions" notification instead.
      const existing = await this.prisma.fundRequest.findUnique({
        where: { uniq_request_period_owner: { submittedByUserId: userId, period: FundRequestPeriod.weekly, periodKey: key } },
      });

      if (existing && NON_REFRESH_STATUSES_FR.includes(existing.status)) {
        // Don't overwrite approved/disbursed totals — flag any lines that
        // are NOT already members as late additions.
        const existingItems = await this.prisma.fundRequestItem.findMany({
          where: { fundRequestId: existing.id },
          select: { activityScheduleCostLineId: true },
        });
        const have = new Set(existingItems.map((i) => i.activityScheduleCostLineId));
        const additions = userLines.filter((l) => !have.has(l.id));
        if (additions.length) {
          await this.notifyLateChanges(existing.id, additions.length);
        }
        skipped++;
        continue;
      }

      const totalAmount = userLines.reduce((sum, l) => sum + l.amount, 0);

      const submitterRole = await this.userRole(userId);
      const fr = await this.prisma.fundRequest.upsert({
        where: { uniq_request_period_owner: { submittedByUserId: userId, period: FundRequestPeriod.weekly, periodKey: key } },
        create: {
          fy, period: FundRequestPeriod.weekly, periodKey: key,
          scope: 'own',
          submittedByUserId: userId,
          submittedByRole: submitterRole,
          totalAmount, activityCount: userLines.length,
          status: FundRequestStatus.draft,
        },
        update: {
          totalAmount, activityCount: userLines.length,
          // refresh only if still in draft/submitted_to_pl/returned states
        },
      });

      if (existing) requestsRefreshed++;
      else requestsCreated++;

      // Upsert items — unique on (fundRequestId, activityScheduleCostLineId)
      // prevents double-inclusion. Lines not in the current set are deleted
      // (cancellation/reschedule out of week).
      const currentLineIds = new Set(userLines.map((l) => l.id));
      await this.prisma.fundRequestItem.deleteMany({
        where: { fundRequestId: fr.id, activityScheduleCostLineId: { notIn: [...currentLineIds] } },
      });
      for (const l of userLines) {
        await this.prisma.fundRequestItem.upsert({
          where: { uniq_request_costline: { fundRequestId: fr.id, activityScheduleCostLineId: l.id } },
          create: {
            fundRequestId: fr.id,
            activityId: l.activityId,
            activityScheduleCostLineId: l.id,
            amount: l.amount,
            period: FundRequestPeriod.weekly,
            periodKey: key,
            addedAfterGeneration: !!existing, // refresh = late add
          },
          update: { amount: l.amount },
        });
      }

      await this.audit.log({
        action: 'fundRequest.weeklyAutoGenerate',
        subjectKind: 'FundRequest', subjectId: fr.id,
        actorId: opts.actor === 'cron' ? 'cron' : opts.actor,
        payload: { weekStart: start.toISOString(), weekEnd: end.toISOString(), key, total: totalAmount, count: userLines.length },
      });
    }

    return { requestsCreated, requestsRefreshed, skipped, weekStart: start, weekEnd: end, periodKey: key };
  }

  // ── 25th Monthly Work Plan Budget Job (idempotent) ─────────────────────

  /** Cron: every 25th of the month at 06:00 local. */
  @Cron('0 6 25 * *', { name: 'MonthlyWorkPlanBudgetJob' })
  async runMonthlyWorkPlanBudgetJob() {
    try {
      const out = await this.generateMonthlyWorkPlanBudget(new Date(), { actor: 'cron' });
      this.log.log(`MonthlyWorkPlanBudgetJob: ${out.budgetsCreated} created, ${out.budgetsRefreshed} refreshed, ${out.skipped} skipped`);
    } catch (err) {
      this.log.error('MonthlyWorkPlanBudgetJob failed', err as Error);
    }
  }

  /** Manual or scheduled — generate/refresh the next-month work plan budget.
   *  One envelope per country (single-country deployment for now). */
  async generateMonthlyWorkPlanBudget(now: Date, opts: { actor: 'cron' | string; countryId?: string }) {
    const fy = getOperationalFY();
    const { monthKey, start, end } = BudgetAutomationService.nextCalendarMonthKey(now);
    const countryId = opts.countryId ?? null;

    const lines = await this.prisma.activityScheduleCostLine.findMany({
      where: {
        activity: {
          deletedAt: null,
          scheduledDate: { gte: start, lte: end },
          status: { notIn: ['cancelled', 'rejected', 'deferred', 'not_planned'] },
          costMissing: false,
        },
      },
      include: {
        activity: {
          select: {
            id: true, activityType: true, deliveryType: true,
            responsibleStaffId: true, assignedPartnerId: true,
            projectId: true, clusterId: true, schoolId: true,
            school: { select: { districtId: true } },
          },
        },
      },
    });

    const existing = await this.prisma.monthlyWorkPlanBudget.findUnique({
      where: { uniq_country_month: { countryId, monthKey } } as Prisma.MonthlyWorkPlanBudgetWhereUniqueInput,
    }).catch(() => null);

    if (existing && NON_REFRESH_STATUSES_MWP.includes(existing.status)) {
      // Don't silently overwrite — flag deltas via late-change items.
      const existingItems = await this.prisma.monthlyWorkPlanItem.findMany({
        where: { monthlyBudgetId: existing.id },
        select: { activityScheduleCostLineId: true },
      });
      const have = new Set(existingItems.map((i) => i.activityScheduleCostLineId));
      const additions = lines.filter((l) => !have.has(l.id));
      if (additions.length) await this.notifyLateChanges(existing.id, additions.length);
      return { budgetsCreated: 0, budgetsRefreshed: 0, skipped: 1, monthKey };
    }

    const programTotal = lines.reduce((s, l) => s + l.amount, 0);
    // Admin lines persist across refreshes — recompute admin total from
    // existing rows so a draft refresh doesn't wipe CD's admin plan.
    const adminTotal = existing
      ? (await this.prisma.adminBudgetLine.aggregate({ where: { monthlyBudgetId: existing.id, status: 'active' }, _sum: { totalCost: true } }))._sum.totalCost ?? 0
      : 0;

    const mwpb = await this.prisma.monthlyWorkPlanBudget.upsert({
      where: { uniq_country_month: { countryId, monthKey } } as Prisma.MonthlyWorkPlanBudgetWhereUniqueInput,
      create: {
        fy, monthKey, countryId, programTotal, adminTotal,
        totalAmount: programTotal + adminTotal,
        activityCount: lines.length,
        status: MonthlyWorkPlanBudgetStatus.draft_generated,
      },
      update: {
        programTotal, activityCount: lines.length,
        totalAmount: programTotal + adminTotal,
      },
    });

    // Upsert program items.
    const currentLineIds = new Set(lines.map((l) => l.id));
    await this.prisma.monthlyWorkPlanItem.deleteMany({
      where: { monthlyBudgetId: mwpb.id, activityScheduleCostLineId: { notIn: [...currentLineIds] } },
    });
    for (const l of lines) {
      await this.prisma.monthlyWorkPlanItem.upsert({
        where: { uniq_month_costline: { monthlyBudgetId: mwpb.id, activityScheduleCostLineId: l.id } },
        create: {
          monthlyBudgetId: mwpb.id,
          activityId: l.activityId,
          activityScheduleCostLineId: l.id,
          amount: l.amount,
          activityType: l.activity.activityType,
          deliveryType: l.activity.deliveryType,
          responsibleStaffId: l.activity.responsibleStaffId,
          districtId: l.activity.school?.districtId,
          partnerId: l.activity.assignedPartnerId,
          projectId: l.activity.projectId,
          clusterId: l.activity.clusterId,
          schoolId: l.activity.schoolId,
          addedAfterGeneration: !!existing,
        },
        update: { amount: l.amount },
      });
    }

    await this.audit.log({
      action: 'monthlyWorkPlanBudget.autoGenerate',
      subjectKind: 'MonthlyWorkPlanBudget', subjectId: mwpb.id,
      actorId: opts.actor === 'cron' ? 'cron' : opts.actor,
      payload: { monthKey, programTotal, adminTotal, count: lines.length },
    });

    return {
      budgetsCreated: existing ? 0 : 1,
      budgetsRefreshed: existing ? 1 : 0,
      skipped: 0,
      monthKey,
    };
  }

  // ── Helpers ────────────────────────────────────────────────────────────

  private async userRole(userId: string) {
    const u = await this.prisma.user.findUnique({ where: { id: userId }, select: { activeRole: true } });
    return u?.activeRole ?? 'CCEO';
  }

  private async notifyLateChanges(_subjectId: string, count: number) {
    // Hook for future notification; for now the audit log is the source of
    // truth and the FE can read `addedAfterGeneration` to surface the chip.
    this.log.warn(`Late additions detected on ${_subjectId}: ${count} new lines after approval/disbursement`);
  }
}

import { Injectable, Logger } from '@nestjs/common';
import { Cron } from '@nestjs/schedule';
import { ConfigService } from '@nestjs/config';
import { NotificationPriority } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { DomainEventService } from '../../common/realtime/domain-events.service';

// ───────────────────────── Notification Jobs ────────────────────────────────
//
// The two scheduled jobs the audit flagged as missing:
//
//   • NotificationEscalationJob — hourly. Finds action-required notifications
//     still unread past their SLA window and escalates them: bumps the
//     priority one band (normal → high → urgent) so they climb the recipient's
//     rail, and notifies the recipient's supervisor once (deduped by
//     sourceEventId) so a stuck action can't silently age out.
//
//   • DailyDigestJob — every day at 07:30 local. For each user with unread
//     notifications, emits a single digest notification summarising the count
//     by priority, with a deep link to the notification rail. Once-per-day so
//     staff aren't spammed.
//
// Both jobs are gated on ENABLE_BACKGROUND_JOBS (single worker replica), same
// as the budget automation jobs.

/** Escalation priority bands: low→normal→high→urgent. Urgent is the ceiling. */
export const NEXT_BAND: Record<NotificationPriority, NotificationPriority | null> = {
  low: 'normal', normal: 'high', high: 'urgent', urgent: null,
};
const PRIORITY_RANK: Record<NotificationPriority, number> = {
  low: 0, normal: 1, high: 2, urgent: 3,
};

/** Hours an action-required notification may sit unread before escalating. */
export const ESCALATION_SLA_HOURS = 48;

@Injectable()
export class NotificationJobsService {
  private readonly log = new Logger('NotificationJobs');

  constructor(
    private readonly prisma: PrismaService,
    private readonly events: DomainEventService,
    private readonly config: ConfigService,
  ) {}

  private get cronEnabled(): boolean {
    return this.config.get<boolean>('ENABLE_BACKGROUND_JOBS') ?? false;
  }

  // ── Hourly escalation sweep ──────────────────────────────────────────

  /** Cron: at minute 0 of every hour. Escalates stale action-required alerts. */
  @Cron('0 * * * *', { name: 'NotificationEscalationJob' })
  async runEscalationJob() {
    if (!this.cronEnabled) return;
    try {
      const escalated = await this.escalateStaleNotifications();
      if (escalated > 0) this.log.log(`NotificationEscalationJob: escalated ${escalated} stale action-required notifications`);
    } catch (err) {
      this.log.error('NotificationEscalationJob failed', err as Error);
    }
  }

  /** Find unread, action-required notifications past the SLA, bump their
   *  priority band, and (once per source) alert the recipient's supervisor. */
  async escalateStaleNotifications(): Promise<number> {
    const cutoff = new Date(Date.now() - ESCALATION_SLA_HOURS * 60 * 60 * 1000);

    // Candidates: action-required, still unread, created before the SLA cutoff,
    // and not already at urgent (can't escalate further).
    const stale = await this.prisma.notification.findMany({
      where: {
        actionRequired: true,
        status: 'unread',
        createdAt: { lt: cutoff },
        priority: { not: 'urgent' },
      },
      take: 200,
    });
    if (stale.length === 0) return 0;

    let count = 0;
    for (const n of stale) {
      const next = NEXT_BAND[n.priority];
      if (!next) continue; // already urgent

      await this.prisma.notification.update({
        where: { id: n.id },
        data: { priority: next },
      });
      count++;

      // Supervisor alert — deduped by sourceEventId so the hourly sweep doesn't
      // spam the supervisor for the same stuck action.
      if (n.sourceEventId) {
        await this.alertSupervisorOnce(n, next);
      }
    }
    return count;
  }

  /** Resolve the recipient's active supervisor (via the join table) and, if
   *  we haven't already alerted them for this source, send one escalation note. */
  private async alertSupervisorOnce(
    n: { id: string; title: string; recipientId: string; contextType: string | null; contextId: string | null; targetRoute: string | null; sourceEventId: string | null },
    priority: NotificationPriority,
  ): Promise<void> {
    if (!n.sourceEventId) return;
    // Resolve the recipient's StaffProfile → active supervisor assignment.
    const profile = await this.prisma.staffProfile.findFirst({
      where: { userId: n.recipientId },
      select: {
        supervisorLinks: {
          where: { supervisor: { deletedAt: null, user: { isActive: true } } },
          take: 1,
          select: { supervisor: { select: { userId: true } } },
        },
      },
    });
    const supervisorUserId = profile?.supervisorLinks[0]?.supervisor.userId;
    if (!supervisorUserId) return;

    const alreadyAlerted = await this.prisma.notification.findFirst({
      where: {
        recipientId: supervisorUserId,
        sourceEventType: 'notification.escalated',
        sourceEventId: n.sourceEventId,
      },
      select: { id: true },
    });
    if (alreadyAlerted) return;

    await this.events.notifyOnly({
      type: 'notification.escalated',
      subjectKind: 'Notification',
      subjectId: n.id,
      actorId: undefined,
      notify: [{
        recipientId: supervisorUserId,
        title: `Escalated: ${n.title}`,
        body: `This action-required item has been unread for ${ESCALATION_SLA_HOURS}h. Review and follow up.`,
        contextType: n.contextType ?? undefined,
        contextId: n.contextId ?? undefined,
        targetRoute: n.targetRoute ?? '/notifications',
        actionLabel: 'Review',
        actionRequired: true,
        priority,
        sourceEventType: 'notification.escalated',
        sourceEventId: n.sourceEventId,
      }],
    });
  }

  // ── Daily digest ─────────────────────────────────────────────────────

  /** Cron: every day at 07:30 local. Emits one digest per user with unread. */
  @Cron('30 7 * * *', { name: 'DailyDigestJob' })
  async runDigestJob() {
    if (!this.cronEnabled) return;
    try {
      const sent = await this.sendDailyDigests();
      if (sent > 0) this.log.log(`DailyDigestJob: sent ${sent} digests`);
    } catch (err) {
      this.log.error('DailyDigestJob failed', err as Error);
    }
  }

  /** For each user with unread notifications, emit a single digest summary.
   *  Deduped per (user, calendar-day) via sourceEventId so re-runs are safe. */
  async sendDailyDigests(): Promise<number> {
    const today = new Date().toISOString().slice(0, 10);
    const dayKey = `digest-${today}`;

    // Users with at least one unread notification.
    const recipients = await this.prisma.notification.groupBy({
      by: ['recipientId'],
      where: { status: 'unread' },
      _count: { _all: true },
    });
    if (recipients.length === 0) return 0;

    let sent = 0;
    for (const { recipientId, _count } of recipients) {
      // Skip if we already sent today's digest to this user (idempotent re-run).
      const already = await this.prisma.notification.findFirst({
        where: { recipientId, sourceEventType: 'notification.digest', sourceEventId: dayKey },
        select: { id: true },
      });
      if (already) continue;

      // Break down the unread set by priority for the summary line.
      const byPriority = await this.prisma.notification.groupBy({
        by: ['priority'],
        where: { recipientId, status: 'unread' },
        _count: { _all: true },
      });
      const parts = byPriority
        .sort((a, b) => PRIORITY_RANK[b.priority] - PRIORITY_RANK[a.priority])
        .map((p) => `${p._count._all} ${p.priority}`);
      const total = _count._all;

      await this.events.notifyOnly({
        type: 'notification.digest',
        subjectKind: 'Notification',
        subjectId: dayKey,
        actorId: undefined,
        liveUserIds: [recipientId],
        notify: [{
          recipientId,
          title: `Daily digest — ${total} unread`,
          body: parts.length ? `You have ${parts.join(', ')} notification${total === 1 ? '' : 's'} waiting.` : `${total} notification${total === 1 ? '' : 's'} waiting.`,
          targetRoute: '/notifications',
          actionLabel: total > 0 ? 'Open notifications' : undefined,
          actionRequired: false,
          priority: 'low',
          sourceEventType: 'notification.digest',
          sourceEventId: dayKey,
        }],
      });
      sent++;
    }
    return sent;
  }
}

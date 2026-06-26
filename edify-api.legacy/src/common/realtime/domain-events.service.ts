import { Injectable } from '@nestjs/common';
import { EdifyRole, Prisma } from '@prisma/client';
import { PrismaService } from '../../prisma/prisma.service';
import { RealtimeService } from './realtime.service';
import { AuditService } from '../audit/audit.service';
import { resolveContextRoute } from '../notifications/context-route';
import { actionLabelFor, dbPriority, renderRule, resolveRecipients, ruleFor, type ResolvedAudience } from '../notifications/notification-rules';

export type NotifySpec = {
  recipientId: string;
  title: string;
  body?: string;
  contextType?: string;
  contextId?: string;
  targetRoute?: string;
  actionLabel?: string;
  actionRequired?: boolean;
  priority?: 'low' | 'normal' | 'high' | 'urgent';
  /** Provenance (spec §16) — which workflow event produced this notification. */
  sourceEventType?: string;
  sourceEventId?: string;
  expiresAt?: Date;
};

export type DomainEvent = {
  type: string;
  actorId?: string;
  actorRole?: EdifyRole;
  subjectKind?: string;
  subjectId?: string;
  payload?: Prisma.InputJsonValue;
  /** Database-backed notifications to create + push to recipients. */
  notify?: NotifySpec[];
  /** Extra users who should get a live "refresh" patch (beyond notify recipients + actor). */
  liveUserIds?: Array<string | undefined | null>;
};

// The single seam every workflow action calls AFTER its DB transaction commits.
// It makes the system behave like a live command center: one action →
//   1. an audit-log row (leadership trust + the activity timeline)
//   2. database-backed notifications for the right recipients
//   3. real-time push so the affected dashboards/queues refresh without a reload
//
// Emitting never throws into the caller's transaction — the write already
// succeeded; notification/realtime failures must not roll the workflow back.
@Injectable()
export class DomainEventService {
  constructor(
    private readonly prisma: PrismaService,
    private readonly realtime: RealtimeService,
    private readonly audit: AuditService,
  ) {}

  async emit(evt: DomainEvent): Promise<void> {
    const at = Date.now();
    // 0) Persisted domain-event log (spec §16). Created BEFORE processing with a
    // null processedAt so a health check (spec §19) can find events that were
    // recorded but never turned into notifications. Best-effort.
    const logId = await this.logDomainEvent(evt);
    try {
      // 1) Audit — the immutable record of what changed. Routed through the
      // hash-chained AuditService.log (prevHash + chainHash + advisory lock) so
      // every emitted event is tamper-evident, not a raw null-hash row outside
      // the chain.
      await this.audit.log({
        action: evt.type,
        subjectKind: evt.subjectKind,
        subjectId: evt.subjectId,
        actorId: evt.actorId,
        actorRole: evt.actorRole,
        payload: evt.payload,
      });

      // 2) Notifications — saved per-recipient, never decorative. Routed to a
      // role-aware deep link, and deduped so the same unresolved alert never spams.
      const created = await this.createNotifications(evt.notify, evt.subjectKind, evt.subjectId);
      await this.markDomainEventProcessed(logId);

      // 3a) Recipients get a live "notification" event (drives the unread badge).
      for (const n of created) {
        this.realtime.publish(n.recipientId, {
          type: 'notification', subjectKind: 'Notification', subjectId: n.id, at,
          meta: { title: n.title, actionRequired: n.actionRequired, priority: n.priority },
        });
      }

      // 3b) Everyone affected gets a domain "refresh" patch (re-fetch the touched surfaces).
      this.realtime.publishMany(
        [...(evt.liveUserIds ?? []), ...created.map((c) => c.recipientId), evt.actorId],
        { type: evt.type, subjectKind: evt.subjectKind, subjectId: evt.subjectId, at },
      );
    } catch {
      // Swallow — the source-of-truth write already committed. A production
      // build would enqueue a retry job here (BullMQ); for now the audit/notify
      // best-effort failure must never surface as a failed workflow action.
    }
  }

  /** Notifications + realtime push WITHOUT writing an audit row. Use this when
   *  the caller already wrote a hash-chained audit entry via AuditService.log
   *  (e.g. money operations, whose audit must stay in the tamper-evident chain)
   *  and only needs the recipient notifications + live refresh. */
  async notifyOnly(evt: Omit<DomainEvent, 'actorRole' | 'payload'>): Promise<void> {
    const at = Date.now();
    const logId = await this.logDomainEvent(evt as DomainEvent);
    try {
      const created = await this.createNotifications(evt.notify, evt.subjectKind, evt.subjectId);
      await this.markDomainEventProcessed(logId);
      for (const n of created) {
        this.realtime.publish(n.recipientId, {
          type: 'notification', subjectKind: 'Notification', subjectId: n.id, at,
          meta: { title: n.title, actionRequired: n.actionRequired, priority: n.priority },
        });
      }
      this.realtime.publishMany(
        [...(evt.liveUserIds ?? []), ...created.map((c) => c.recipientId), evt.actorId],
        { type: evt.type, subjectKind: evt.subjectKind, subjectId: evt.subjectId, at },
      );
    } catch {
      // Best-effort — the source-of-truth write + its chained audit already committed.
    }
  }

  /**
   * Persist per-recipient notifications with two guarantees:
   *  • role-aware deep link — when the caller didn't pass an explicit targetRoute,
   *    resolve one for the recipient's role + the event context (never a route the
   *    role can't act on);
   *  • dedupe — one UNRESOLVED notification per (recipient, context, title). A repeat
   *    event bumps the existing row to the top instead of spamming a new one.
   */
  private async createNotifications(
    notify: NotifySpec[] | undefined,
    fallbackKind?: string,
    fallbackId?: string,
  ) {
    const specs = notify ?? [];
    if (specs.length === 0) return [];
    const ids = [...new Set(specs.map((s) => s.recipientId))];
    const roleById = new Map<string, EdifyRole>();
    for (const u of await this.prisma.user.findMany({ where: { id: { in: ids } }, select: { id: true, activeRole: true } })) {
      roleById.set(u.id, u.activeRole);
    }
    const created: Array<{ id: string; recipientId: string; title: string; actionRequired: boolean; priority: string }> = [];
    for (const n of specs) {
      const contextType = n.contextType ?? fallbackKind ?? null;
      const contextId = n.contextId ?? fallbackId ?? null;
      const role = roleById.get(n.recipientId);
      const targetRoute = n.targetRoute ?? (role && contextType ? resolveContextRoute(role, contextType, contextId) : undefined);
      const data = {
        recipientId: n.recipientId,
        recipientRole: role ?? null,
        title: n.title,
        body: n.body,
        contextType,
        contextId,
        targetRoute,
        actionLabel: n.actionLabel,
        actionRequired: n.actionRequired ?? false,
        priority: (n.priority ?? 'normal') as never,
        sourceEventType: n.sourceEventType,
        sourceEventId: n.sourceEventId,
        expiresAt: n.expiresAt,
      };
      // Dedupe against an existing unread notification for the same record + title.
      const existing = await this.prisma.notification.findFirst({
        where: { recipientId: n.recipientId, status: 'unread', title: n.title, contextType, contextId },
        select: { id: true },
      });
      const row = existing
        ? await this.prisma.notification.update({ where: { id: existing.id }, data: { ...data, createdAt: new Date() } })
        : await this.prisma.notification.create({ data });
      created.push(row);
    }
    return created;
  }

  /**
   * Auto-resolve open notifications for a context once the underlying issue is
   * fixed — e.g. uploading evidence resolves the "evidence missing" alert, paying
   * resolves "payment ready". Workflow actions call this post-commit so stale
   * notifications never linger. Pushes a live refresh so the bell badge drops.
   */
  async resolveContext(contextType: string, contextId: string, opts?: { titleIncludes?: string }): Promise<number> {
    try {
      const where: Prisma.NotificationWhereInput = {
        contextType, contextId, status: { in: ['unread', 'read'] },
        ...(opts?.titleIncludes ? { title: { contains: opts.titleIncludes } } : {}),
      };
      const affected = await this.prisma.notification.findMany({ where, select: { recipientId: true } });
      if (affected.length === 0) return 0;
      await this.prisma.notification.updateMany({ where, data: { status: 'archived' } });
      this.realtime.publishMany(
        [...new Set(affected.map((a) => a.recipientId))],
        { type: 'notification.resolved', subjectKind: 'Notification', subjectId: contextId, at: Date.now() },
      );
      return affected.length;
    } catch {
      return 0;
    }
  }

  /**
   * Emit a workflow event THROUGH the declarative notification rule engine
   * (spec §9): the rule decides priority, title/body, context type, action flag
   * and the role audience; the caller supplies only the concrete relational ids
   * (assignee, submitter, supervisors, account owner, …). This keeps every
   * workflow call site small and guarantees no notification ships without a
   * route/action. Role audiences are auto-expanded via usersWithRole.
   */
  async emitFromRule(input: {
    event: string;
    actorId?: string;
    actorRole?: EdifyRole;
    subjectKind?: string;
    subjectId?: string;
    contextId?: string | null;
    payload?: Prisma.InputJsonValue;
    vars?: { name?: string; detail?: string };
    audience?: Omit<ResolvedAudience, 'usersByRole'>;
    /** Skip the audit-log row (use when the caller already logged the action). */
    notifyOnly?: boolean;
  }): Promise<void> {
    const rule = ruleFor(input.event);
    if (!rule) {
      // Spec §19 health check: a workflow event with no notification rule is a
      // gap — surface it instead of silently dropping the alert.
      try {
        await this.audit.log({
          action: 'system.notificationRuleMissing', subjectKind: input.subjectKind, subjectId: input.subjectId,
          actorId: input.actorId, actorRole: input.actorRole, payload: { event: input.event } as Prisma.InputJsonValue,
        });
      } catch { /* best-effort */ }
      return;
    }
    // Expand role audiences to concrete user rosters.
    const usersByRole: Partial<Record<EdifyRole, string[]>> = {};
    for (const t of rule.audience) {
      if (t.kind === 'role' && !(t.role in usersByRole)) usersByRole[t.role] = await this.usersWithRole(t.role);
    }
    const recipients = resolveRecipients(rule, { ...(input.audience ?? {}), usersByRole });
    if (recipients.length === 0) return;
    const { title, body } = renderRule(rule, input.vars ?? {});
    const actionLabel = actionLabelFor(rule);
    const notify = recipients.map((recipientId) => ({
      recipientId, title, body,
      contextType: rule.contextType, contextId: input.contextId ?? input.subjectId,
      actionLabel, actionRequired: rule.actionRequired, priority: dbPriority(rule.priority),
      sourceEventType: input.event, sourceEventId: input.subjectId,
    }));
    const evt = {
      type: input.event, actorId: input.actorId, actorRole: input.actorRole,
      subjectKind: input.subjectKind, subjectId: input.subjectId, payload: input.payload,
      notify, liveUserIds: [input.actorId],
    };
    if (input.notifyOnly) await this.notifyOnly(evt);
    else await this.emit(evt);
  }

  /** Append the persisted domain-event log row (spec §16). Returns the row id so
   *  the caller can mark it processed once notifications are created. Best-effort
   *  — a logging failure must never break the workflow action. */
  private async logDomainEvent(evt: DomainEvent): Promise<string | null> {
    try {
      const row = await this.prisma.domainEventLog.create({
        data: {
          eventType: evt.type,
          aggregateType: evt.subjectKind,
          aggregateId: evt.subjectId,
          actorId: evt.actorId,
          payload: evt.payload,
        },
        select: { id: true },
      });
      return row.id;
    } catch {
      return null;
    }
  }

  private async markDomainEventProcessed(logId: string | null): Promise<void> {
    if (!logId) return;
    try {
      await this.prisma.domainEventLog.update({ where: { id: logId }, data: { processedAt: new Date() } });
    } catch {
      /* best-effort */
    }
  }

  /** Resolve the User ids for a role (e.g. all accountants to notify of a ready payment). */
  async usersWithRole(role: EdifyRole): Promise<string[]> {
    const rows = await this.prisma.user.findMany({ where: { roles: { has: role } }, select: { id: true } });
    return rows.map((r) => r.id);
  }

  /** Resolve a StaffProfile id → its User id (notification recipients are Users). */
  async userForStaff(staffProfileId?: string | null): Promise<string | null> {
    if (!staffProfileId) return null;
    const sp = await this.prisma.staffProfile.findUnique({ where: { id: staffProfileId }, select: { userId: true } });
    return sp?.userId ?? null;
  }
}

import { ForbiddenException, Injectable, NotFoundException } from '@nestjs/common';
import { PrismaService } from '../../prisma/prisma.service';
import { AuthUser } from '../../common/auth/auth-user';
import { paginate, PaginationDto } from '../../common/dto/pagination.dto';

// Per-user notifications, always scoped to the recipient. Never hardcoded.
@Injectable()
export class NotificationsService {
  constructor(private readonly prisma: PrismaService) {}

  // Active feed excludes resolved (archived) notifications — a resolved alert
  // disappears from the bell instead of lingering as stale noise.
  list(user: AuthUser, q: PaginationDto) {
    const where = { recipientId: user.userId, status: { not: 'archived' as const } };
    return Promise.all([
      this.prisma.notification.findMany({ where, skip: q.skip, take: q.take, orderBy: { createdAt: 'desc' } }),
      this.prisma.notification.count({ where }),
    ]).then(([data, total]) => paginate(data, total, q));
  }

  recent(user: AuthUser) {
    return this.prisma.notification.findMany({ where: { recipientId: user.userId, status: { not: 'archived' } }, orderBy: { createdAt: 'desc' }, take: 8 });
  }

  async counts(user: AuthUser) {
    const [unread, actionRequired] = await Promise.all([
      this.prisma.notification.count({ where: { recipientId: user.userId, status: 'unread' } }),
      this.prisma.notification.count({ where: { recipientId: user.userId, status: 'unread', actionRequired: true } }),
    ]);
    return { unread, actionRequired };
  }

  // Just the unread badge number (spec §17 GET /notifications/unread-count).
  async unreadCount(user: AuthUser) {
    const count = await this.prisma.notification.count({ where: { recipientId: user.userId, status: 'unread' } });
    return { count };
  }

  // The live notification rail (spec §12): active (non-archived) notifications
  // grouped by priority, with the full action contract each item needs to drive
  // a CTA + deep link. The frontend drawer renders these groups in order.
  async rail(user: AuthUser) {
    const rows = await this.prisma.notification.findMany({
      where: { recipientId: user.userId, status: { not: 'archived' } },
      orderBy: { createdAt: 'desc' },
      take: 100,
    });
    const item = (n: (typeof rows)[number]) => ({
      id: n.id, title: n.title, body: n.body, priority: n.priority,
      contextType: n.contextType, contextId: n.contextId, targetRoute: n.targetRoute,
      actionLabel: n.actionLabel, actionRequired: n.actionRequired,
      status: n.status, createdAt: n.createdAt, expiresAt: n.expiresAt,
      sourceEventType: n.sourceEventType, sourceEventId: n.sourceEventId,
    });
    const order: Array<'urgent' | 'high' | 'normal' | 'low'> = ['urgent', 'high', 'normal', 'low'];
    const groups = order
      .map((priority) => ({ priority, items: rows.filter((n) => n.priority === priority).map(item) }))
      .filter((g) => g.items.length > 0);
    const unread = rows.filter((n) => n.status === 'unread').length;
    return { unread, total: rows.length, groups };
  }

  async markRead(id: string, user: AuthUser) {
    const n = await this.prisma.notification.findUnique({ where: { id } });
    if (!n) throw new NotFoundException('Notification not found');
    if (n.recipientId !== user.userId) throw new ForbiddenException('Not your notification');
    return this.prisma.notification.update({ where: { id }, data: { status: 'read', readAt: new Date() } });
  }

  async markAllRead(user: AuthUser) {
    const r = await this.prisma.notification.updateMany({ where: { recipientId: user.userId, status: 'unread' }, data: { status: 'read', readAt: new Date() } });
    return { updated: r.count };
  }

  // Mark a notification resolved (the issue it points to is handled). Resolved
  // notifications leave the active feed and the unread badge.
  async resolve(id: string, user: AuthUser) {
    const n = await this.prisma.notification.findUnique({ where: { id } });
    if (!n) throw new NotFoundException('Notification not found');
    if (n.recipientId !== user.userId) throw new ForbiddenException('Not your notification');
    return this.prisma.notification.update({ where: { id }, data: { status: 'archived' } });
  }
}

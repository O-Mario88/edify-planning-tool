import { describe, it, expect, vi } from 'vitest';
import { BadRequestException } from '@nestjs/common';
import { EdifyRole } from '@prisma/client';
import { MessagesService } from './messages.service';
import { AuthUser } from '../../common/auth/auth-user';

// Spec §5/§6/§20 — the message send/reply path: every message carries a context
// the policy allows, and replies INHERIT the thread's context automatically.

function user(role: EdifyRole, over: Partial<AuthUser> = {}): AuthUser {
  return { userId: 'u1', email: 'x@edify.org', name: 'CD', roles: [role], activeRole: role, ...over };
}

function svc(opts: {
  recipient?: { id: string; activeRole: EdifyRole } | null;
  thread?: Record<string, unknown> | null;
  otherUser?: { activeRole: EdifyRole } | null;
}) {
  const prisma = {
    user: {
      findFirst: vi.fn(async () => opts.recipient ?? null),
      findUnique: vi.fn(async () => opts.otherUser ?? null),
    },
    messageThread: {
      create: vi.fn(async (a: { data: Record<string, unknown> }) => ({ id: 'thread1', ...a.data })),
      findUnique: vi.fn(async () => opts.thread ?? null),
    },
    message: {
      create: vi.fn(async (a: { data: Record<string, unknown> }) => ({ id: 'msg1', ...a.data })),
    },
  };
  const events = { notifyOnly: vi.fn(async () => undefined) };
  const s = new MessagesService(prisma as never, events as never);
  return { s, prisma, events };
}

describe('MessagesService.send — policy enforcement', () => {
  it('rejects a message with no context', async () => {
    const { s } = svc({ recipient: { id: 'u2', activeRole: 'CCEO' } });
    await expect(s.send(user('CountryDirector'), { recipientId: 'u2', body: 'hi' })).rejects.toBeInstanceOf(BadRequestException);
  });

  it('rejects an off-policy context for the pairing', async () => {
    const { s } = svc({ recipient: { id: 'u2', activeRole: 'CountryDirector' } });
    // CCEO → CD cannot use the CD→RVP "country-budget-approval" context.
    await expect(
      s.send(user('CCEO'), { recipientId: 'u2', body: 'hi', contextKey: 'country-budget-approval' }),
    ).rejects.toBeInstanceOf(BadRequestException);
  });

  it('creates a context-tagged thread + message for a valid pairing', async () => {
    const { s, prisma, events } = svc({ recipient: { id: 'u2', activeRole: 'CCEO' } });
    const res = await s.send(user('CountryDirector'), { recipientId: 'u2', body: 'Great work this week', contextKey: 'performance-progress' });
    expect(res.threadId).toBe('thread1');
    const msgData = prisma.message.create.mock.calls[0][0].data;
    expect(msgData.category).toBe('performance-progress');
    expect(msgData.recipientId).toBe('u2');
    expect(events.notifyOnly).toHaveBeenCalled();
  });
});

describe('MessagesService.reply — inherits context (spec §20)', () => {
  it('a reply carries the thread context forward automatically', async () => {
    const thread = {
      id: 'thread1', subject: 'School concern', contextType: 'school', contextId: 'sch-1',
      messages: [{ senderId: 'u1', recipientId: 'u2' }],
    };
    const { s, prisma } = svc({ thread, otherUser: { activeRole: 'CountryDirector' } });
    await s.reply(user('CCEO', { userId: 'u2' }), 'thread1', { body: 'Thanks, following up' });
    const data = prisma.message.create.mock.calls[0][0].data;
    expect(data.contextType).toBe('school');
    expect(data.contextId).toBe('sch-1');
    expect(data.recipientId).toBe('u1'); // routes to the other participant
  });
});

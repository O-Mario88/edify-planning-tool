import { describe, it, expect, vi } from 'vitest';
import { EdifyRole } from '@prisma/client';
import { CommandCenterAlertsService } from './command-center-alerts.service';
import { AuthUser } from '../../common/auth/auth-user';

// Spec §13/§17/§20 — the persistent-alert read path: live generation, per-user
// temporary dismissal, and reappear-while-unresolved.

const user: AuthUser = { userId: 'u1', email: 'x@edify.org', name: 'X', roles: ['CountryDirector' as EdifyRole], activeRole: 'CountryDirector' as EdifyRole };

const openAlert = (over: Record<string, unknown> = {}) => ({
  id: 'a1', alertType: 'schools_without_ssa', severity: 'urgent', scope: 'country',
  title: '3 schools without SSA', body: null, targetRoute: '/planning', contextType: 'data_quality_issue',
  contextId: null, conditionHash: 'schools_without_ssa:country', status: 'open',
  createdAt: new Date('2026-06-01'), updatedAt: new Date('2026-06-01'), resolvedAt: null, ...over,
});

function svc(opts: { open?: Record<string, unknown>[]; dismissals?: { alertId: string; dismissedUntil: Date }[]; alert?: Record<string, unknown> | null }) {
  const prisma = {
    commandCenterAlert: {
      findMany: vi.fn(async () => opts.open ?? []),
      findUnique: vi.fn(async () => opts.alert ?? null),
      upsert: vi.fn(async () => undefined),
      updateMany: vi.fn(async () => ({ count: 0 })),
    },
    commandCenterAlertDismissal: {
      findMany: vi.fn(async () => opts.dismissals ?? []),
      upsert: vi.fn(async (a: { where: { alertId_userId: Record<string, unknown> }; create: { dismissedUntil: Date } & Record<string, unknown> } ) => a.create),
    },
  };
  const s = new CommandCenterAlertsService(prisma as never);
  // Skip the heavy live generator — these tests cover the read/dismiss path.
  s.generate = vi.fn(async () => undefined);
  return { s, prisma };
}

describe('CommandCenterAlertsService.list', () => {
  it('returns open alerts when the user has no dismissals', async () => {
    const { s } = svc({ open: [openAlert()] });
    const out = await s.list(user);
    expect(out).toHaveLength(1);
    expect(out[0].alertType).toBe('schools_without_ssa');
  });

  it('hides an alert dismissed within its window, then shows it again once lapsed', async () => {
    const future = svc({ open: [openAlert()], dismissals: [{ alertId: 'a1', dismissedUntil: new Date(Date.now() + 3600_000) }] });
    expect(await future.s.list(user)).toHaveLength(0);

    const past = svc({ open: [openAlert()], dismissals: [{ alertId: 'a1', dismissedUntil: new Date(Date.now() - 3600_000) }] });
    expect(await past.s.list(user)).toHaveLength(1);
  });
});

describe('CommandCenterAlertsService.dismiss', () => {
  it('records a dismissal window for the user', async () => {
    const { s, prisma } = svc({ alert: { id: 'a1' } });
    const res = await s.dismiss(user, 'a1', 6);
    expect(res.ok).toBe(true);
    expect(prisma.commandCenterAlertDismissal.upsert).toHaveBeenCalled();
    const arg = prisma.commandCenterAlertDismissal.upsert.mock.calls[0][0]!;
    expect(arg.where.alertId_userId).toEqual({ alertId: 'a1', userId: 'u1' });
    expect(arg.create.dismissedUntil.getTime()).toBeGreaterThan(Date.now());
  });

  it('no-ops for an unknown alert id', async () => {
    const { s, prisma } = svc({ alert: null });
    expect(await s.dismiss(user, 'missing')).toEqual({ ok: false });
    expect(prisma.commandCenterAlertDismissal.upsert).not.toHaveBeenCalled();
  });

  it('caps an absurd dismissal window to the fortnight ceiling', async () => {
    const { s, prisma } = svc({ alert: { id: 'a1' } });
    await s.dismiss(user, 'a1', 99999);
    const until = prisma.commandCenterAlertDismissal.upsert.mock.calls[0][0]!.create.dismissedUntil.getTime();
    const ceilingMs = Date.now() + 24 * 14 * 3600 * 1000 + 1000;
    expect(until).toBeLessThanOrEqual(ceilingMs);
  });
});

import { describe, it, expect } from 'vitest';
import { conditionHash, summarize, sortAlerts, visibleAlerts, type OpenAlert } from './alert-visibility';

// Spec §13 + §20 — command-center alerts are persistent operational risks. A
// user may dismiss one temporarily, but it REAPPEARS when the window lapses if
// the underlying issue is still unresolved. These lock that behaviour.

const mkAlert = (over: Partial<OpenAlert> = {}): OpenAlert => ({
  id: 'a1', alertType: 'schools_without_ssa', severity: 'urgent', scope: 'country',
  title: '3 schools without SSA', body: null, targetRoute: '/planning', contextType: 'data_quality_issue',
  contextId: null, conditionHash: 'schools_without_ssa:country', createdAt: new Date('2026-06-01'), updatedAt: new Date('2026-06-01'),
  ...over,
});

describe('conditionHash', () => {
  it('is stable per (alertType, scope) so re-generation upserts one row', () => {
    expect(conditionHash('schools_without_ssa', 'country')).toBe('schools_without_ssa:country');
    expect(conditionHash('schools_without_ssa', 'country')).toBe(conditionHash('schools_without_ssa', 'country'));
  });
});

describe('visibleAlerts — dismiss + reappear (spec §13)', () => {
  const now = new Date('2026-06-23T12:00:00Z');

  it('shows an open alert with no dismissal', () => {
    expect(visibleAlerts([mkAlert()], [], now)).toHaveLength(1);
  });

  it('hides an alert while the dismissal window is still in the future', () => {
    const dismissals = [{ alertId: 'a1', dismissedUntil: new Date('2026-06-24T12:00:00Z') }];
    expect(visibleAlerts([mkAlert()], dismissals, now)).toHaveLength(0);
  });

  it('REAPPEARS once the dismissal window lapses and the issue is still open', () => {
    const dismissals = [{ alertId: 'a1', dismissedUntil: new Date('2026-06-23T06:00:00Z') }];
    const visible = visibleAlerts([mkAlert()], dismissals, now);
    expect(visible).toHaveLength(1);
    expect(visible[0].id).toBe('a1');
  });

  it('a dismissal for a DIFFERENT alert does not hide this one', () => {
    const dismissals = [{ alertId: 'other', dismissedUntil: new Date('2026-07-01T00:00:00Z') }];
    expect(visibleAlerts([mkAlert()], dismissals, now)).toHaveLength(1);
  });
});

describe('sortAlerts + summarize', () => {
  it('orders most-severe first', () => {
    const alerts = [
      mkAlert({ id: 'low', severity: 'low' }),
      mkAlert({ id: 'urg', severity: 'urgent' }),
      mkAlert({ id: 'hi', severity: 'high' }),
    ];
    expect(sortAlerts(alerts).map((a) => a.id)).toEqual(['urg', 'hi', 'low']);
  });

  it('buckets a summary by severity', () => {
    const s = summarize([{ severity: 'urgent' }, { severity: 'urgent' }, { severity: 'high' }, { severity: 'low' }]);
    expect(s).toEqual({ total: 4, urgent: 2, high: 1, normal: 0, low: 1 });
  });
});

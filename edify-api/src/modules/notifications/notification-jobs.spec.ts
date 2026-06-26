import { describe, it, expect } from 'vitest';
import { NEXT_BAND, ESCALATION_SLA_HOURS } from './notification-jobs.service';

// The escalation service hits Prisma, so these specs lock the pure decision
// logic — the priority-banding that drives which notifications escalate and
// the SLA window that gates it. The cron wiring is gated behind ENABLE_BACKGROUND_JOBS.

describe('notification escalation banding', () => {
  it('escalates one band at a time: low→normal→high→urgent', () => {
    expect(NEXT_BAND.low).toBe('normal');
    expect(NEXT_BAND.normal).toBe('high');
    expect(NEXT_BAND.high).toBe('urgent');
  });

  it('stops at urgent (the ceiling) — returns null, not a further band', () => {
    expect(NEXT_BAND.urgent).toBeNull();
  });

  it('the SLA window is a sensible two business days', () => {
    expect(ESCALATION_SLA_HOURS).toBe(48);
    expect(ESCALATION_SLA_HOURS).toBeGreaterThan(0);
  });
});

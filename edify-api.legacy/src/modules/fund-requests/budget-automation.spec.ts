import { describe, it, expect } from 'vitest';
import { BudgetAutomationService } from './budget-automation.service';

// Pure-function tests for the date helpers that drive the Friday + 25th
// jobs. These are the things that MUST be deterministic so the unique
// (submittedByUserId, period, periodKey) and (countryId, monthKey)
// indices don't race or create duplicate envelopes.

describe('BudgetAutomationService.upcomingOpWeek', () => {
  it('Friday → next week Mon..Sun', () => {
    // 2026-06-19 is a Friday.
    const out = BudgetAutomationService.upcomingOpWeek(new Date('2026-06-19T12:00:00Z'));
    expect(out.start.getDay()).toBe(1); // Monday
    expect(out.end.getDay()).toBe(0);   // Sunday
    // Window length = 7 calendar days inclusive.
    const span = out.end.getTime() - out.start.getTime();
    expect(span).toBeGreaterThan(6 * 86_400_000);
    expect(span).toBeLessThan(7 * 86_400_000);
  });

  it('Sunday → THIS upcoming Monday (the immediate next week)', () => {
    // 2026-06-21 is a Sunday.
    const out = BudgetAutomationService.upcomingOpWeek(new Date('2026-06-21T12:00:00Z'));
    expect(out.start.getDay()).toBe(1);
    // The Mon after Sun 6/21 is 6/22.
    expect(out.start.getDate()).toBe(22);
  });

  it('Monday → NEXT week Monday, not today', () => {
    // Idempotency requirement: running the job on Monday must target the
    // FOLLOWING week, not the current one.
    const out = BudgetAutomationService.upcomingOpWeek(new Date('2026-06-22T12:00:00Z'));
    expect(out.start.getDay()).toBe(1);
    expect(out.start.getDate()).toBe(29); // next Mon
  });

  it('periodKey is stable across runs on the same day', () => {
    const a = BudgetAutomationService.upcomingOpWeek(new Date('2026-06-19T06:00:00Z'));
    const b = BudgetAutomationService.upcomingOpWeek(new Date('2026-06-19T22:00:00Z'));
    expect(a.key).toBe(b.key);
  });
});

describe('BudgetAutomationService.nextCalendarMonthKey', () => {
  it('25th of June → 2026-07', () => {
    const out = BudgetAutomationService.nextCalendarMonthKey(new Date('2026-06-25T06:00:00Z'));
    expect(out.monthKey).toBe('2026-07');
    expect(out.start.getMonth()).toBe(6); // July (0-indexed)
    expect(out.start.getDate()).toBe(1);
    // Should END on the last day of July (31).
    expect(out.end.getMonth()).toBe(6);
    expect(out.end.getDate()).toBe(31);
  });

  it('25th of December → next-year January (rolls over)', () => {
    const out = BudgetAutomationService.nextCalendarMonthKey(new Date('2026-12-25T06:00:00Z'));
    expect(out.monthKey).toBe('2027-01');
    expect(out.start.getFullYear()).toBe(2027);
  });

  it('any day of January → February (rules of "next month")', () => {
    const earlyJan = BudgetAutomationService.nextCalendarMonthKey(new Date('2026-01-03T06:00:00Z'));
    const lateJan = BudgetAutomationService.nextCalendarMonthKey(new Date('2026-01-31T06:00:00Z'));
    expect(earlyJan.monthKey).toBe('2026-02');
    expect(lateJan.monthKey).toBe('2026-02');
  });
});

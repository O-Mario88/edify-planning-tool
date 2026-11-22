import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  addDays,
  buildMonthGrid,
  evaluateDayAvailability,
  formatDisplayDate,
  rangePresets,
  ugandaFiscalYear,
} from '@/lib/datePicker';

import { EdifyDatePicker, EdifyDateRangePicker } from './EdifyDatePicker';

describe('EdifyDatePicker — unified platform-wide calendar picker (Sections 10 & 11)', () => {
  it('renders a single full-width clickable button with a left calendar icon and zero chevron', () => {
    const html = renderToStaticMarkup(
      <EdifyDatePicker
        label="Field day date"
        name="date"
        value="2026-11-23"
        displayStyle="weekday"
      />,
    );
    expect(html).toContain('data-date-trigger="true"');
    expect(html).toContain('data-has-chevron="false"');
    expect(html).toContain('Mon, 23 Nov 2026');
    expect(html).toContain('type="hidden" name="date" value="2026-11-23"');
    // Must not render any native <input type="date"> or chevron icon inside the trigger.
    expect(html).not.toContain('type="date"');
    expect(html).not.toContain('lucide-chevron');
  });

  it('enforces Uganda FY2027 boundaries (Oct 1, 2026 to Sep 30, 2027) without UTC date drift', () => {
    expect(ugandaFiscalYear('2026-09-30')).toEqual({ fy: 'FY2026', start: '2025-10-01', end: '2026-09-30' });
    expect(ugandaFiscalYear('2026-10-01')).toEqual({ fy: 'FY2027', start: '2026-10-01', end: '2027-09-30' });
    expect(ugandaFiscalYear('2027-09-30')).toEqual({ fy: 'FY2027', start: '2026-10-01', end: '2027-09-30' });
    expect(addDays('2026-10-01', -1)).toBe('2026-09-30');
    expect(formatDisplayDate('2026-11-23', 'weekday')).toBe('Mon, 23 Nov 2026');
  });

  it('disables Sundays, public holidays, approved leave, and blackouts in planning mode while keeping Saturdays open', () => {
    const policy = {
      mode: 'planning' as const,
      holidays: [{ date: '2026-10-09', name: 'Independence Day' }],
      approvedLeaveDates: ['2026-11-25'],
      blackoutDates: ['2026-11-26'],
    };
    // 2026-11-22 is Sunday -> disabled
    expect(evaluateDayAvailability('2026-11-22', policy).disabled).toBe(true);
    // 2026-11-21 is Saturday -> enabled
    expect(evaluateDayAvailability('2026-11-21', policy).disabled).toBe(false);
    // Public holiday -> disabled with reason
    const hol = evaluateDayAvailability('2026-10-09', policy);
    expect(hol.disabled).toBe(true);
    expect(hol.reason).toContain('Independence Day');
    // Approved leave -> disabled
    expect(evaluateDayAvailability('2026-11-25', policy).disabled).toBe(true);
    // Blackout -> disabled
    expect(evaluateDayAvailability('2026-11-26', policy).disabled).toBe(true);
    // Free mode does NOT block Sundays (for historical/financial/PTO inputs)
    expect(evaluateDayAvailability('2026-11-22', { mode: 'free' }).disabled).toBe(false);
  });

  it('builds a full 42-day month grid and date range presets cleanly', () => {
    const grid = buildMonthGrid(2026, 11);
    expect(grid).toHaveLength(42);
    expect(grid.filter((c) => c.inMonth)).toHaveLength(30);
    const presets = rangePresets('2026-11-23');
    expect(presets.map((p) => p.label)).toEqual(['Today', 'Tomorrow', 'This Week', 'Next Week', 'This Month']);

    const rangeHtml = renderToStaticMarkup(
      <EdifyDateRangePicker startDate="2026-11-23" endDate="2026-11-28" onChange={() => undefined} />,
    );
    expect(rangeHtml).toContain('Nov 23, 2026 – Nov 28, 2026');
    expect(rangeHtml).toContain('data-has-chevron="false"');
  });
});

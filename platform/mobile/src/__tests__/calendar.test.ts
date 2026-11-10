import { addMonths, isWithin, monthCells, openingMonth, parseIso, shortLabel, toIso } from '../ui/calendar';

describe('parseIso and toIso', () => {
  test('a saved date is a calendar day, read as its parts', () => {
    expect(parseIso('2026-11-03')).toEqual({ y: 2026, m: 11, d: 3 });
    expect(toIso({ y: 2026, m: 1, d: 9 })).toBe('2026-01-09');
  });

  test('a value that is not a real day reads as no day', () => {
    expect(parseIso('')).toBeNull();
    expect(parseIso('2026-02-30')).toBeNull();
    expect(parseIso('12/11/2026')).toBeNull();
  });
});

describe('shortLabel', () => {
  test('reads as the web field does', () => {
    expect(shortLabel({ y: 2026, m: 11, d: 12 })).toBe('Nov 12, 2026');
  });
});

describe('monthCells', () => {
  test('six weeks from Sunday, blanks before the first and after the last day', () => {
    // 1 November 2026 is a Sunday.
    const cells = monthCells(2026, 11);
    expect(cells).toHaveLength(42);
    expect(cells[0]).toEqual({ y: 2026, m: 11, d: 1 });
    expect(cells[29]).toEqual({ y: 2026, m: 11, d: 30 });
    expect(cells[30]).toBeNull();
  });

  test('a month starting midweek leads with blanks', () => {
    // 1 October 2026 is a Thursday.
    const cells = monthCells(2026, 10);
    expect(cells.slice(0, 4)).toEqual([null, null, null, null]);
    expect(cells[4]).toEqual({ y: 2026, m: 10, d: 1 });
  });
});

describe('addMonths and isWithin', () => {
  test('steps across a year', () => {
    expect(addMonths({ y: 2026, m: 12 }, 1)).toEqual({ y: 2027, m: 1 });
    expect(addMonths({ y: 2026, m: 1 }, -1)).toEqual({ y: 2025, m: 12 });
  });

  test("a day outside the field's min or max cannot be picked", () => {
    const day = { y: 2026, m: 11, d: 12 };
    expect(isWithin(day, '2026-11-01', '2026-11-30')).toBe(true);
    expect(isWithin(day, '2026-11-13', '')).toBe(false);
    expect(isWithin(day, '', '2026-11-11')).toBe(false);
  });

  test("the calendar opens on the field's date, else today kept inside min and max", () => {
    const today = { y: 2026, m: 11, d: 10 };
    expect(openingMonth('2027-02-05', '', '', today)).toEqual({ y: 2027, m: 2 });
    expect(openingMonth('', '2027-01-01', '', today)).toEqual({ y: 2027, m: 1 });
    expect(openingMonth('', '', '', today)).toEqual({ y: 2026, m: 11 });
  });
});

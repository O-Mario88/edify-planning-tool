import { describe, expect, it } from 'vitest';

import { kindFor, movedText, parsePoint, sourceText } from './locationReport';

describe('location reports', () => {
  it('reports a school with a point as wrong and one without as missing', () => {
    expect(kindFor('recorded')).toBe('wrong');
    expect(kindFor('verified')).toBe('wrong');
    expect(kindFor('missing')).toBe('missing');
    expect(kindFor('invalid')).toBe('missing');
  });

  it('takes a typed point in Uganda and refuses the rest', () => {
    expect(parsePoint(' 0.4021 ', '32.6402')).toEqual({ lat: 0.4021, lng: 32.6402 });
    expect(parsePoint('0', '0')).toMatch(/not in Uganda/);
    expect(parsePoint('51.5', '-0.12')).toMatch(/not in Uganda/);
    expect(parsePoint('', '32.6')).toMatch(/as numbers/);
    expect(parsePoint('north', '32.6')).toMatch(/as numbers/);
  });

  it('says how far a point moves in metres or kilometres', () => {
    const at = { lat: 0.3, lng: 32.5 };
    expect(movedText({ previous: at, proposed: at, movedMeters: 420n } as never)).toBe('420 m from the point on record (straight line)');
    expect(movedText({ previous: at, proposed: at, movedMeters: 2350n } as never)).toBe('2.4 km from the point on record (straight line)');
    expect(movedText({ previous: undefined, proposed: at, movedMeters: 0n } as never)).toBe('No usable point was on record');
    expect(movedText({ previous: at, proposed: undefined, movedMeters: 0n } as never)).toBe('No new point proposed');
  });

  it('names where a point came from', () => {
    expect(sourceText({ pointSource: 'device', accuracyM: 12.4 })).toBe('Device location, accurate to 12 m');
    expect(sourceText({ pointSource: 'typed', accuracyM: 0 })).toBe('Typed in');
  });
});

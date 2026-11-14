import { bandOf, inUganda, isSettled, metersBetween, summarize } from '../offline/gpsMath';
import type { GpsSample } from '../offline/gpsMath';
import { actionForError, repeatOf, retryDelayMs, statusForOutcome } from '../offline/queueLogic';

const start = 1_000_000;
const at = (lat: number, lng: number, accuracy: number, t: number): GpsSample => ({ lat, lng, accuracy, at: start + t });

describe('reading a school position from GPS', () => {
  it('drops a cached fix from before the capture began', () => {
    const fix = summarize([at(0.5, 32.5, 3, -60_000), at(0.3476, 32.5825, 12, 1_000)], start);
    expect(fix?.lat).toBe(0.3476);
    expect(fix?.sampleCount).toBe(1);
  });

  it('has nothing when every reading is stale or useless', () => {
    expect(summarize([at(0.3, 32.5, 3, -10_000), at(0.3, 32.5, 900, 500)], start)).toBeNull();
  });

  it('takes the middle of the better readings and says how far apart they were', () => {
    const samples = [at(0.3476, 32.5825, 6, 1000), at(0.34762, 32.58252, 7, 2000), at(0.34758, 32.58248, 8, 3000), at(0.351, 32.59, 45, 4000)];
    const fix = summarize(samples, start)!;
    expect(fix.accuracy).toBe(6);
    expect(fix.sampleCount).toBe(3);
    expect(metersBetween(fix, { lat: 0.3476, lng: 32.5825 })).toBeLessThan(5);
    expect(fix.spread).toBeLessThan(5);
  });

  it('settles only on enough good readings that agree', () => {
    const good = [1, 2, 3, 4, 5].map((i) => at(0.3476 + i * 1e-6, 32.5825, 6, i * 1000));
    expect(isSettled(good, start)).toBe(true);
    expect(isSettled(good.slice(0, 3), start)).toBe(false);
    const apart = [1, 2, 3, 4, 5].map((i) => at(0.3476 + i * 1e-3, 32.5825, 6, i * 1000));
    expect(isSettled(apart, start)).toBe(false);
  });

  it('bands accuracy as the policy says', () => {
    expect(bandOf(20)).toBe('good');
    expect(bandOf(35)).toBe('confirm');
    expect(bandOf(51)).toBe('recapture');
  });

  it('knows Uganda', () => {
    expect(inUganda(0.3476, 32.5825)).toBe(true);
    expect(inUganda(0, 0)).toBe(false);
    expect(inUganda(51.5, -0.12)).toBe(false);
  });
});

describe('the offline capture queue', () => {
  it('waits longer after each failed try, to half an hour', () => {
    expect(retryDelayMs(0)).toBe(15_000);
    expect(retryDelayMs(2)).toBe(60_000);
    expect(retryDelayMs(20)).toBe(30 * 60_000);
  });

  it('reads the server answer', () => {
    expect(statusForOutcome('accepted', []).status).toBe('synced');
    expect(statusForOutcome('pending', ['accuracy_fair']).status).toBe('awaiting_review');
    expect(statusForOutcome('pending', ['correction', 'version_conflict']).status).toBe('conflict');
    expect(statusForOutcome('noted', []).status).toBe('synced');
  });

  it('keeps a capture through lost connections and expired sign-ins, and stops on a refusal', () => {
    expect(actionForError('network')).toBe('retry');
    expect(actionForError('timeout')).toBe('retry');
    expect(actionForError('unavailable')).toBe('retry');
    expect(actionForError('internal')).toBe('retry');
    expect(actionForError('unauthenticated')).toBe('sign_in');
    expect(actionForError('permission_denied')).toBe('failed');
    expect(actionForError('not_found')).toBe('failed');
  });
});

describe('a repeated capture', () => {
  const base = { schoolId: 's1', target: 'school', kind: 'correction', lat: 0.5465, lng: 32.8782, createdAt: 1_000_000, status: 'synced' as const };

  it('is the same school, point and answer within ten minutes', () => {
    expect(repeatOf({ ...base, createdAt: base.createdAt + 6 * 60_000 }, [base], metersBetween)).toBe(base);
    expect(repeatOf({ ...base, lat: 0.54652 }, [base], metersBetween)).toBe(base);
  });

  it('is not a new point, another school, a later visit or an earlier refusal', () => {
    expect(repeatOf({ ...base, lat: 0.5475 }, [base], metersBetween)).toBeNull();
    expect(repeatOf({ ...base, schoolId: 's2' }, [base], metersBetween)).toBeNull();
    expect(repeatOf({ ...base, createdAt: base.createdAt + 11 * 60_000 }, [base], metersBetween)).toBeNull();
    expect(repeatOf(base, [{ ...base, status: 'failed' as const }], metersBetween)).toBeNull();
    expect(repeatOf({ ...base, target: 'entrance' }, [base], metersBetween)).toBeNull();
  });

  it('counts a second "location is correct" the same day as a repeat', () => {
    const yes = { ...base, kind: 'confirm', lat: null, lng: null };
    expect(repeatOf({ ...yes, createdAt: base.createdAt + 60_000 }, [yes], metersBetween)).toBe(yes);
  });
});

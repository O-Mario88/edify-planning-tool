import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { RouteLegSchema, RouteTotalsSchema, SavedFieldDaySchema, SchoolPinSchema } from '@/gen/edify/routes/v1/routes_pb';

import { dayClock, directionsUrl, fieldDayState, hoursMinutes, hrMin, km, legFigures, measureLabel, pinTone, totalFigures } from './routePlanner';

describe('figures are written as the designs write them', () => {
  it.each([
    [0, '0 min'],
    [32 * 60, '32 min'],
    [135 * 60, '2h 15min'],
    [120 * 60, '2h'],
  ])('%is is %s', (s, want) => expect(hoursMinutes(s)).toBe(want));
  it('mobile writes hours as hr', () => expect(hrMin(85 * 60)).toBe('1 hr 25 min'));
  it('distances carry one decimal', () => expect(km(56_830)).toBe('56.8 km'));
});

describe('a straight line is never shown as a road', () => {
  it('uses the road where the provider measured it', () => {
    const leg = create(RouteLegSchema, { roadAvailable: true, roadMeters: 10_000n, roadSeconds: 1320n, straightLineMeters: 5800n });
    expect(legFigures(leg)).toEqual({ meters: 10_000, seconds: 1320, measure: 'road' });
  });
  it('falls back to the straight line and its planning estimate, labelled', () => {
    const leg = create(RouteLegSchema, { straightLineMeters: 5800n, estimateSeconds: 720n });
    const f = legFigures(leg);
    expect(f).toEqual({ meters: 5800, seconds: 720, measure: 'straight_line' });
    expect(measureLabel(f!.measure)).toBe('Straight-line distance');
  });
  it('has no figure for the first stop of a day with no start', () => {
    expect(legFigures(create(RouteLegSchema, {}))).toBeNull();
  });
  it('totals by road only when every leg was measured', () => {
    const partial = create(RouteTotalsSchema, { roadMeters: 9000n, roadSeconds: 600n, roadComplete: false, straightLineMeters: 20_000n, estimateSeconds: 2400n });
    expect(totalFigures(partial).measure).toBe('straight_line');
    expect(totalFigures(partial).meters).toBe(20_000);
  });
});

describe('directions go to the person’s own maps app, keyless', () => {
  const stops = [
    create(SchoolPinSchema, { name: 'A', point: { lat: 0.3, lng: 32.7 } }),
    create(SchoolPinSchema, { name: 'No point' }),
    create(SchoolPinSchema, { name: 'B', point: { lat: 0.4, lng: 32.8 } }),
  ];
  it('Google Maps gets the route with waypoints and no key', () => {
    const url = directionsUrl(stops)!;
    expect(url).toContain('destination=0.400000%2C32.800000');
    expect(url).toContain('waypoints=0.300000%2C32.700000');
    expect(url).not.toMatch(/key=/);
  });
  it('Apple Maps and Waze get the next stop', () => {
    expect(directionsUrl(stops, 'apple')).toBe('https://maps.apple.com/?daddr=0.300000,32.700000&dirflg=d');
    expect(directionsUrl(stops, 'waze')).toBe('https://waze.com/ul?ll=0.300000,32.700000&navigate=yes');
  });
  it('a day with no placed school has no directions', () => expect(directionsUrl([stops[1]!])).toBeNull());
});

describe('a profile shows its own school as the plain blue pin', () => {
  it('whatever the school is on the plan', () => {
    expect(pinTone(create(SchoolPinSchema, { status: 'other' }), 'location')).toBe('planned');
    expect(pinTone(create(SchoolPinSchema, { status: 'other' }))).toBe('other');
  });
});

describe('the field day', () => {
  const today = '2026-11-18';

  it('can be started only on its own day', () => {
    expect(fieldDayState(undefined, today, today)).toMatchObject({ phase: 'unsaved', canStart: true, running: false });
    expect(fieldDayState(undefined, '2026-11-19', today)).toMatchObject({ phase: 'unsaved', canStart: false });
  });

  it('runs from start to end, and keeps its order once started', () => {
    const saved = create(SavedFieldDaySchema, { schoolIds: ['a'], savedAt: '2026-11-18T04:50:00Z' });
    expect(fieldDayState(saved, today, today)).toMatchObject({ phase: 'saved', canStart: true, canSave: true });
    const started = create(SavedFieldDaySchema, { ...saved, startedAt: '2026-11-18T05:02:00Z' });
    expect(fieldDayState(started, today, today)).toMatchObject({ phase: 'started', running: true, canStart: false, canSave: false });
    const ended = create(SavedFieldDaySchema, { ...started, endedAt: '2026-11-18T12:00:00Z' });
    expect(fieldDayState(ended, today, today)).toMatchObject({ phase: 'ended', running: false, canStart: false, canSave: false });
  });

  it('writes its times on the Kampala clock', () => {
    expect(dayClock('2026-11-18T05:02:00Z')).toBe('08:02');
    expect(dayClock('')).toBe('');
  });
});

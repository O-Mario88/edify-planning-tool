import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { HomeShortcutSchema } from '@/gen/edify/screens/v1/home_pb';
import { NavItemSchema, NavSectionSchema } from '@/gen/edify/screens/v1/navigation_pb';
import { RouteLegSchema, RouteTotalsSchema, SavedFieldDaySchema, SchoolPinSchema } from '@/gen/edify/routes/v1/routes_pb';

import {
  ROUTE_PLANNER_PATH,
  withRoutePlanner,
  withRouteShortcut,
  dayClock,
  directionsUrl,
  inAppDirectionsPath,
  fieldDayState,
  hoursMinutes,
  hrMin,
  km,
  legFigures,
  measureLabel,
  pinTone,
  totalFigures,
} from './routePlanner';

describe('route figures say what they are', () => {
  it('formats distance and time as the web and mobile designs write them', () => {
    expect(km(12450)).toBe('12.4 km');
    expect(hoursMinutes(8100)).toBe('2h 15min');
    expect(hoursMinutes(2040)).toBe('34 min');
    expect(hrMin(5100)).toBe('1 hr 25 min');
    expect(hrMin(1080)).toBe('18 min');
  });

  it('uses road figures only when measured, and totals by road only when every leg is road', () => {
    const road = create(RouteLegSchema, { roadAvailable: true, roadMeters: 8200n, roadSeconds: 900n, straightLineMeters: 6000n, estimateSeconds: 720n });
    expect(legFigures(road)).toEqual({ meters: 8200, seconds: 900, measure: 'road' });
    const straight = create(RouteLegSchema, { roadAvailable: false, straightLineMeters: 6000n, estimateSeconds: 720n });
    expect(legFigures(straight)).toEqual({ meters: 6000, seconds: 720, measure: 'straight_line' });
    const partial = create(RouteTotalsSchema, { roadComplete: false, roadMeters: 8200n, straightLineMeters: 14000n, estimateSeconds: 1680n });
    expect(totalFigures(partial)).toEqual({ meters: 14000, seconds: 1680, measure: 'straight_line' });
    expect(measureLabel('road')).toBe('Estimated road distance');
    expect(measureLabel('straight_line')).toBe('Straight-line distance');
  });
});

describe('Get Directions stays 100% inside Edify (zero external maps redirects)', () => {
  const stops = [
    create(SchoolPinSchema, { schoolId: '1', name: 'A', point: { lat: 0.3, lng: 32.7 } }),
    create(SchoolPinSchema, { schoolId: '2', name: 'B' }),
    create(SchoolPinSchema, { schoolId: '3', name: 'C', point: { lat: 0.4, lng: 32.8 } }),
  ];
  it('returns an internal Edify Smart Route navigation path with placed school IDs only', () => {
    const url = directionsUrl(stops)!;
    expect(url).toBe('/my-plan/smart-route?navigate=1%2C3');
    expect(url).not.toContain('google.com/maps');
    expect(url).not.toContain('maps.apple.com');
    expect(url).not.toContain('waze.com');
    expect(inAppDirectionsPath(stops, '2026-11-23')).toBe('/my-plan/smart-route?date=2026-11-23&navigate=1%2C3');
  });
  it('a day with no placed school has no directions', () => expect(directionsUrl([stops[1]!])).toBeNull());
});

describe('pins use the legend colours', () => {
  it('distinguishes planned, suggested, completed and other schools', () => {
    expect(pinTone(create(SchoolPinSchema, { status: 'planned' }))).toBe('planned');
    expect(pinTone(create(SchoolPinSchema, { status: 'completed' }))).toBe('completed');
    expect(pinTone(create(SchoolPinSchema, { status: 'planned' }), 'recommended')).toBe('suggested');
    expect(pinTone(create(SchoolPinSchema, { status: 'other' }))).toBe('other');
  });
});

describe('Save Plan and Start Field Day', () => {
  it('saves before starting, starts only on the day itself, and closes once ended', () => {
    expect(fieldDayState(undefined, '2026-11-18', '2026-11-18')).toEqual({ phase: 'unsaved', running: false, canSave: true, canStart: true });
    expect(fieldDayState(undefined, '2026-11-19', '2026-11-18')).toEqual({ phase: 'unsaved', running: false, canSave: true, canStart: false });
    const saved = create(SavedFieldDaySchema, { savedAt: '2026-11-18T05:00:00Z' });
    expect(fieldDayState(saved, '2026-11-18', '2026-11-18')).toEqual({ phase: 'saved', running: false, canSave: true, canStart: true });
    const started = create(SavedFieldDaySchema, { savedAt: '2026-11-18T05:00:00Z', startedAt: '2026-11-18T05:02:00Z' });
    expect(fieldDayState(started, '2026-11-18', '2026-11-18')).toEqual({ phase: 'started', running: true, canSave: false, canStart: false });
    const ended = create(SavedFieldDaySchema, { startedAt: '2026-11-18T05:02:00Z', endedAt: '2026-11-18T13:15:00Z' });
    expect(fieldDayState(ended, '2026-11-18', '2026-11-18')).toEqual({ phase: 'ended', running: false, canSave: false, canStart: false });
  });

  it('formats recorded times on the Kampala clock', () => {
    expect(dayClock('2026-11-18T05:02:00Z')).toBe('08:02');
    expect(dayClock('')).toBe('');
  });
});

describe('Smart Route Planner menu and home links', () => {
  it('places Smart Route Planner straight after My Plan for a planner role only', () => {
    const sections = [
      create(NavSectionSchema, {
        label: 'Daily',
        items: [create(NavItemSchema, { label: 'My Plan', url: '/my-plan' }), create(NavItemSchema, { label: 'Calendar', url: '/calendar' })],
      }),
    ];
    const forCceo = withRoutePlanner(sections, 'CCEO')[0]!.items.map((i) => i.url);
    expect(forCceo).toEqual(['/my-plan', ROUTE_PLANNER_PATH, '/calendar']);
    const forHr = withRoutePlanner(sections, 'HR')[0]!.items.map((i) => i.url);
    expect(forHr).toEqual(['/my-plan', '/calendar']);
  });

  it('switches Home Quick access from My Plan to Smart Route for planner roles', () => {
    const shortcuts = [create(HomeShortcutSchema, { label: 'My Plan', url: '/my-plan' })];
    expect(withRouteShortcut(shortcuts, 'CCEO')[0]).toMatchObject({ label: 'Smart Route', url: ROUTE_PLANNER_PATH });
    expect(withRouteShortcut(shortcuts, 'HR')[0]).toMatchObject({ label: 'My Plan', url: '/my-plan' });
  });
});

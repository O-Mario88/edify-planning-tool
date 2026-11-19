import { create } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { isSafeIcon } from './icon';
import { RouteLegSchema, RouteTotalsSchema, SavedFieldDaySchema, SchoolPinSchema } from '@/gen/edify/routes/v1/routes_pb';
import { NavItemSchema, NavSectionSchema } from '@/gen/edify/screens/v1/navigation_pb';
import { HomeShortcutSchema } from '@/gen/edify/screens/v1/home_pb';

import { ROUTE_PLANNER_PATH, withRoutePlanner, withRouteShortcut, dayClock, directionsUrl, fieldDayState, hoursMinutes, hrMin, km, legFigures, measureLabel, pinTone, totalFigures } from './routePlanner';

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

describe('the sidebar links the planner below My Plan', () => {
  const sections = [
    create(NavSectionSchema, {
      label: 'Daily',
      items: [
        create(NavItemSchema, { label: 'Dashboard', url: '/dashboard' }),
        create(NavItemSchema, { label: 'My Plan', url: '/my-plan' }),
        create(NavItemSchema, { label: 'School Directory', url: '/schools' }),
      ],
    }),
  ];

  it('puts Smart Route Planner straight after My Plan for a role that plans', () => {
    const [daily] = withRoutePlanner(sections, 'CCEO');
    expect(daily?.items.map((item) => item.label)).toEqual(['Dashboard', 'My Plan', 'Smart Route Planner', 'School Directory']);
    expect(daily?.items[2]?.url).toBe(ROUTE_PLANNER_PATH);
    expect(isSafeIcon(daily?.items[2]?.iconSvg ?? '')).toBe(true);
    // The gateway's answer is left as it was.
    expect(sections[0]?.items).toHaveLength(3);
  });

  it('adds nothing for a role that does not plan, or where the link is already given', () => {
    expect(withRoutePlanner(sections, 'HR')).toBe(sections);
    const given = withRoutePlanner(sections, 'CCEO');
    expect(withRoutePlanner(given, 'CCEO')).toBe(given);
  });
});

describe('Home’s Quick access opens Smart Route in My Plan’s place', () => {
  const shortcuts = ['Dashboard:/dashboard', 'Clusters:/clusters', 'My Plan:/my-plan', 'Calendar:/calendar'].map((pair) => {
    const [label, url] = pair.split(':');
    return create(HomeShortcutSchema, { label, url });
  });

  it('swaps My Plan for Smart Route, linked to the planner, for a role that plans', () => {
    const swapped = withRouteShortcut(shortcuts, 'CCEO');
    expect(swapped.map((shortcut) => `${shortcut.label}:${shortcut.url}`)).toEqual(['Dashboard:/dashboard', 'Clusters:/clusters', `Smart Route:${ROUTE_PLANNER_PATH}`, 'Calendar:/calendar']);
    expect(isSafeIcon(swapped[2]?.iconSvg ?? '')).toBe(true);
    expect(shortcuts[2]?.label).toBe('My Plan');
  });

  it('leaves another role’s shortcuts as they were', () => {
    expect(withRouteShortcut(shortcuts, 'HR')).toBe(shortcuts);
  });
});

import { describe, expect, it } from 'vitest';

import type { RoadConditionReportData, SmartRouteResultData, SmartStopData } from './routePlanner';
import { NO_ROAD_LEG_NOTE, hasNoRoadLeg, optionOf, rankOptions, roadSummary, routeInsights, routeKpis, routeNote, ssaCoverage, trafficWords } from './routeView';
import type { RouteOption } from './routeView';

const stop = (id: string, band: string): SmartStopData =>
  ({ school_id: id, school_name: id, priority: { band }, road_meters: 1000, road_seconds: 60 }) as unknown as SmartStopData;

const result = (over: Partial<SmartRouteResultData> = {}): SmartRouteResultData =>
  ({
    mode: 'balanced',
    objective_label: 'Balanced',
    is_recommended: true,
    recommendation_note: 'Balances SSA priority and travel time.',
    stops: [stop('a', 'critical'), stop('b', 'routine'), stop('c', 'core')],
    excluded: [],
    road_alerts: [],
    warnings: [],
    path_is_road: true,
    distance_saved_meters: 0,
    time_saved_seconds: 0,
    confidence: 'high',
    confidence_note: 'Road distances from the routing provider.',
    totals: {
      schools_included: 3, schools_excluded: 0, road_complete: true, road_meters: 42_500, road_seconds: 5_400,
      straight_line_meters: 30_000, visit_minutes: 180, break_minutes: 30, field_minutes: 300, traffic_state: 'unknown', traffic_delay_seconds: 0,
    },
    ...over,
  }) as SmartRouteResultData;

const option = (mode: RouteOption['mode'], meters: number, seconds: number, included = 3): RouteOption => ({
  mode, label: mode, meters, seconds, included, roadComplete: true, coverage: '2 of 2', traffic: 'Unavailable', recommended: false,
});

describe('routeKpis', () => {
  it('reads the six figures from the route', () => {
    const kpis = routeKpis(result());
    expect(kpis.map((kpi) => kpi.label)).toEqual(['Schools in Route', 'Total Road Distance', 'Driving Time', 'Field Day Duration', 'SSA Priority Coverage', 'Traffic Status']);
    expect(kpis[0]?.value).toBe('3');
    expect(kpis[1]?.value).toBe('42.5 km');
    expect(kpis[2]?.value).toBe('1h 30min');
    expect(kpis[3]?.value).toBe('5h');
  });

  it('never shows a road figure the provider did not confirm', () => {
    const base = result();
    const kpis = routeKpis(result({ totals: { ...base.totals, road_complete: false } }));
    expect(kpis[1]?.value).toBe('Verification needed');
    expect(kpis[2]?.value).toBe('—');
  });

  it('shows no road figure for a single stop with no leg', () => {
    const base = result();
    const kpis = routeKpis(result({ totals: { ...base.totals, schools_included: 1, road_meters: 0, road_seconds: 0 } }));
    expect(kpis[1]?.value).toBe('—');
    expect(kpis[2]?.value).toBe('—');
  });

  it('has an honest empty day', () => {
    const kpis = routeKpis(null);
    expect(kpis[0]?.value).toBe('0');
    expect(kpis[1]?.value).toBe('—');
    expect(kpis[5]?.value).toBe('Unavailable');
  });
});

describe('trafficWords', () => {
  it('says unavailable unless the provider reported traffic', () => {
    expect(trafficWords('unknown')).toBe('Unavailable');
    expect(trafficWords('')).toBe('Unavailable');
    expect(trafficWords('normal')).toBe('Normal');
    expect(trafficWords('slow')).toBe('Slow');
    expect(trafficWords('traffic_jam')).toBe('Heavy');
  });
});

describe('ssaCoverage', () => {
  it('counts the priority schools reached, excluded ones included in the total', () => {
    const coverage = ssaCoverage(result({
      excluded: [{ school_id: 'd', priority: { band: 'high' } }] as unknown as SmartRouteResultData['excluded'],
    }));
    expect(coverage.reached).toBe(2);
    expect(coverage.total).toBe(3);
    expect(coverage.percent).toBe(67);
  });

  it('has no percentage when no school is a priority', () => {
    const coverage = ssaCoverage(result({ stops: [stop('a', 'routine')] }));
    expect(coverage.total).toBe(0);
    expect(coverage.percent).toBeNull();
  });
});

describe('optionOf', () => {
  it('carries the road traffic and recommendation Go gave that route', () => {
    const base = result();
    const option = optionOf('fastest', 'Fastest', result({ is_recommended: false, totals: { ...base.totals, traffic_state: 'slow' } }));
    expect(option.traffic).toBe('Slow');
    expect(option.recommended).toBe(false);
    expect(optionOf('balanced', 'Balanced', result()).recommended).toBe(true);
  });

  it('never invents traffic the provider did not report', () => {
    expect(optionOf('balanced', 'Balanced', result()).traffic).toBe('Unavailable');
  });
});

describe('rankOptions', () => {
  it('names the fastest and shortest only from the measured figures', () => {
    const ranked = rankOptions([option('balanced', 50_000, 5_000), option('fastest', 60_000, 4_000), option('shortest', 45_000, 5_500)]);
    expect(ranked.find((item) => item.mode === 'fastest')?.badges).toContain('Fastest');
    expect(ranked.find((item) => item.mode === 'shortest')?.badges).toContain('Shortest');
    expect(ranked.find((item) => item.mode === 'balanced')?.badges).toEqual([]);
  });

  it('does not call the Fastest mode fastest when it is not', () => {
    const ranked = rankOptions([option('balanced', 50_000, 3_900), option('fastest', 60_000, 4_000)]);
    expect(ranked.find((item) => item.mode === 'fastest')?.badges).not.toContain('Fastest');
    expect(ranked.find((item) => item.mode === 'balanced')?.badges).toContain('Fastest');
  });

  it('names no winner among routes with no confirmed road figures', () => {
    const ranked = rankOptions([{ ...option('fastest', 0, 0), roadComplete: false }, { ...option('shortest', 0, 0), roadComplete: false }]);
    expect(ranked.flatMap((item) => item.badges)).toEqual([]);
  });

  it('names no winner when every route has the same figures', () => {
    const ranked = rankOptions([option('balanced', 9_000, 900), option('fastest', 9_000, 900), option('shortest', 9_000, 900)]);
    expect(ranked.flatMap((item) => item.badges)).toEqual([]);
  });

  it('only compares routes that reach the same number of schools', () => {
    const ranked = rankOptions([option('balanced', 50_000, 5_000, 4), option('fastest', 10_000, 1_000, 1)]);
    expect(ranked.find((item) => item.mode === 'fastest')?.badges).toEqual([]);
    expect(ranked.find((item) => item.mode === 'balanced')?.badges).toEqual([]);
  });
});

describe('roadSummary', () => {
  const alert = (status: string, impact: string): RoadConditionReportData =>
    ({ id: status + impact, road_name: 'R', verification_status: status, impact_level: impact }) as RoadConditionReportData;

  it('counts only what was reported, saying which reports are unverified', () => {
    const summary = roadSummary([alert('verified', 'impassable'), alert('unverified', 'delay'), alert('unverified', 'advisory')]);
    expect(summary.closed).toBe(1);
    expect(summary.delay).toBe(1);
    expect(summary.advisory).toBe(1);
    expect(summary.unverified).toBe(2);
  });

  it('reports nothing when nothing was reported', () => {
    expect(roadSummary([])).toEqual({ closed: 0, delay: 0, advisory: 0, unverified: 0, total: 0 });
  });
});

describe('routeNote', () => {
  it('does not ask for routing to be configured on a day with one school', () => {
    const day = result({ stops: [stop('a', 'routine')], recommendation_note: 'Road geometry unavailable: configure OSRM.' });
    expect(hasNoRoadLeg(day)).toBe(true);
    expect(routeNote(day)).toBe(NO_ROAD_LEG_NOTE);
    expect(routeInsights(day).join(' ')).not.toContain('configure');
  });

  it('keeps the warning when one school has a set start, because that leg is real', () => {
    const day = result({ stops: [stop('a', 'routine')], start: { lat: 0.3, lng: 32.5 }, recommendation_note: 'Road geometry unavailable.' });
    expect(routeNote(day)).toBe('Road geometry unavailable.');
  });

  it('keeps the note on a day with several schools', () => {
    expect(routeNote(result())).toBe('Balances SSA priority and travel time.');
  });
});

describe('routeInsights', () => {
  it('says what the optimizer found, and nothing it did not', () => {
    const lines = routeInsights(result({ distance_saved_meters: 3_000, time_saved_seconds: 600 }));
    expect(lines).toContain('Balances SSA priority and travel time.');
    expect(lines).toContain('Saves 3.0 km and 10 min against the original order.');
  });

  it('warns of schools left out', () => {
    const base = result();
    const lines = routeInsights(result({ totals: { ...base.totals, schools_excluded: 2 } }));
    expect(lines).toContain('2 schools could not be placed on this route.');
  });

  it('claims no saving when none was measured', () => {
    expect(routeInsights(result()).join(' ')).not.toContain('Saves');
  });
});

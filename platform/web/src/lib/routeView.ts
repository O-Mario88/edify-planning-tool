/**
 * The Smart Route Planner's summaries, read from Go's optimized route: its
 * six figures, SSA priority coverage, the comparison of route options and
 * what was reported on the road. Nothing is estimated here: a figure the
 * provider did not confirm is said to be unconfirmed.
 */
import { hoursMinutes, km } from './routePlanner';
import type { RoadConditionReportData, SmartOptimizationMode, SmartRouteResultData } from './routePlanner';

/** The SSA priority bands that make a school a priority to reach. */
const PRIORITY_BANDS = new Set(['critical', 'high', 'missing_ssa', 'core']);

const TRAFFIC_WORDS: Readonly<Record<string, string>> = { normal: 'Normal', slow: 'Slow', traffic_jam: 'Heavy' };

/** Traffic as the provider reported it; anything else is unavailable, never assumed clear. */
export function trafficWords(state: string): string {
  return TRAFFIC_WORDS[state] ?? 'Unavailable';
}

export interface SsaCoverage {
  readonly reached: number;
  readonly total: number;
  /** Null when no school on the day is a priority. */
  readonly percent: number | null;
}

export function ssaCoverage(result: SmartRouteResultData | null): SsaCoverage {
  if (!result) return { reached: 0, total: 0, percent: null };
  const reached = result.stops.filter((stop) => PRIORITY_BANDS.has(stop.priority?.band ?? '')).length;
  const missed = result.excluded.filter((school) => PRIORITY_BANDS.has(school.priority?.band ?? '')).length;
  const total = reached + missed;
  return { reached, total, percent: total ? Math.round((reached * 100) / total) : null };
}

export interface RouteKpi {
  readonly key: string;
  readonly label: string;
  readonly value: string;
  readonly note: string;
}

export function routeKpis(result: SmartRouteResultData | null, plannedStops = 0): RouteKpi[] {
  const totals = result?.totals;
  const coverage = ssaCoverage(result);
  const road = totals?.road_complete;
  const hasStops = Boolean(totals?.schools_included);
  const unconfirmed = hasStops ? 'Verification needed' : '—';
  return [
    {
      key: 'schools',
      label: 'Schools in Route',
      value: String(totals?.schools_included ?? plannedStops),
      note: totals?.schools_excluded ? `${totals.schools_excluded} excluded` : '',
    },
    { key: 'distance', label: 'Total Road Distance', value: road ? (totals.road_meters > 0 ? km(totals.road_meters) : '—') : unconfirmed, note: '' },
    { key: 'driving', label: 'Driving Time', value: road && totals.road_seconds > 0 ? hoursMinutes(totals.road_seconds) : '—', note: '' },
    { key: 'field', label: 'Field Day Duration', value: hasStops && totals ? hoursMinutes(totals.field_minutes * 60) : '—', note: '' },
    {
      key: 'coverage',
      label: 'SSA Priority Coverage',
      value: coverage.percent === null ? '—' : `${coverage.percent}%`,
      note: coverage.total ? `${coverage.reached} of ${coverage.total} priority schools` : 'No priority schools',
    },
    { key: 'traffic', label: 'Traffic Status', value: trafficWords(totals?.traffic_state ?? ''), note: '' },
  ];
}

export interface RouteOption {
  readonly mode: SmartOptimizationMode;
  readonly label: string;
  readonly meters: number;
  readonly seconds: number;
  readonly included: number;
  readonly roadComplete: boolean;
  readonly coverage: string;
}

export interface RankedOption extends RouteOption {
  /** "Fastest", "Shortest": earned by this comparison's measured figures. */
  readonly badges: readonly string[];
}

export function optionOf(mode: SmartOptimizationMode, label: string, result: SmartRouteResultData): RouteOption {
  const coverage = ssaCoverage(result);
  return {
    mode,
    label,
    meters: result.totals.road_meters,
    seconds: result.totals.road_seconds,
    included: result.totals.schools_included,
    roadComplete: result.totals.road_complete,
    coverage: coverage.total ? `${coverage.reached} of ${coverage.total} priority` : 'No priority schools',
  };
}

/**
 * Which option really is the fastest and the shortest. Only routes with
 * confirmed road figures that reach the most schools are compared: a route
 * that drops schools is not "fastest" for it.
 */
export function rankOptions(options: readonly RouteOption[]): RankedOption[] {
  const complete = options.filter((option) => option.roadComplete);
  const most = Math.max(0, ...complete.map((option) => option.included));
  const fair = complete.filter((option) => option.included === most);
  // A figure every route shares names no winner.
  const least = (figure: (option: RouteOption) => number) => {
    const values = fair.map(figure);
    return values.length > 1 && new Set(values).size > 1 ? Math.min(...values) : null;
  };
  const fastest = least((option) => option.seconds);
  const shortest = least((option) => option.meters);
  return options.map((option) => {
    const counted = fair.includes(option);
    const badges = [
      ...(counted && option.seconds === fastest ? ['Fastest'] : []),
      ...(counted && option.meters === shortest ? ['Shortest'] : []),
    ];
    return { ...option, badges };
  });
}

export interface RoadSummary {
  readonly closed: number;
  readonly delay: number;
  readonly advisory: number;
  readonly unverified: number;
  readonly total: number;
}

/** What staff or a provider reported on the route; an empty list is "nothing reported", not "clear". */
export function roadSummary(alerts: readonly RoadConditionReportData[]): RoadSummary {
  const count = (impact: string) => alerts.filter((alert) => alert.impact_level === impact).length;
  return {
    closed: count('impassable'),
    delay: count('delay'),
    advisory: count('advisory'),
    unverified: alerts.filter((alert) => alert.verification_status === 'unverified').length,
    total: alerts.length,
  };
}

/** The optimizer's own findings about this route, in words. */
export function routeInsights(result: SmartRouteResultData | null): string[] {
  if (!result) return [];
  const lines: string[] = [];
  if (result.recommendation_note) lines.push(result.recommendation_note);
  if (result.distance_saved_meters > 0 || result.time_saved_seconds > 0) {
    lines.push(`Saves ${km(result.distance_saved_meters)} and ${hoursMinutes(result.time_saved_seconds)} against the original order.`);
  }
  const left = result.totals.schools_excluded;
  if (left > 0) lines.push(`${left} school${left === 1 ? '' : 's'} could not be placed on this route.`);
  if (!result.path_is_road && result.stops.length > 1) lines.push('Road distances could not be confirmed for this route.');
  if (result.confidence_note) lines.push(result.confidence_note);
  return lines;
}

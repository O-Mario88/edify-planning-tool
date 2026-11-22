/**
 * The Smart Route Planner's words and links. Road figures are the routing
 * provider's; where it gave none the straight line is shown and labelled, with
 * the existing route engine's planning estimate for time. Nothing here makes
 * a figure up.
 */
import { create } from '@bufbuild/protobuf';

import { NavItemSchema } from '@/gen/edify/screens/v1/navigation_pb';
import type { NavSection } from '@/gen/edify/screens/v1/navigation_pb';
import { HomeShortcutSchema } from '@/gen/edify/screens/v1/home_pb';
import type { HomeShortcut } from '@/gen/edify/screens/v1/home_pb';
import type { Itinerary, RouteLeg, RouteTotals, SavedFieldDay, SchoolPin } from '@/gen/edify/routes/v1/routes_pb';

export type Measure = 'road' | 'straight_line';

export interface Figures {
  meters: number;
  seconds: number;
  measure: Measure;
}

/** "12.4 km" (one decimal, as the design writes it). */
export function km(meters: number | bigint): string {
  return `${(Number(meters) / 1000).toFixed(1)} km`;
}

/** "2h 15min", "34 min" (the web design's way). */
export function hoursMinutes(seconds: number | bigint): string {
  const total = Math.round(Number(seconds) / 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h}h` : `${h}h ${m}min`;
}

/** "1 hr 25 min", "18 min" (the mobile design's way). */
export function hrMin(seconds: number | bigint): string {
  const total = Math.round(Number(seconds) / 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} hr` : `${h} hr ${m} min`;
}

/** A leg's distance and time: by road where measured, else the straight line. */
export function legFigures(leg: RouteLeg | undefined): Figures | null {
  if (!leg || (!leg.roadAvailable && Number(leg.straightLineMeters) === 0)) return null;
  if (leg.roadAvailable) return { meters: Number(leg.roadMeters), seconds: Number(leg.roadSeconds), measure: 'road' };
  return { meters: Number(leg.straightLineMeters), seconds: Number(leg.estimateSeconds), measure: 'straight_line' };
}

/**
 * The route's totals: by road only when every leg was measured by road; a
 * partly measured route is never totalled as if it were whole.
 */
export function totalFigures(totals: RouteTotals | undefined): Figures {
  if (totals?.roadComplete) {
    return { meters: Number(totals.roadMeters), seconds: Number(totals.roadSeconds), measure: 'road' };
  }
  return {
    meters: Number(totals?.straightLineMeters ?? 0),
    seconds: Number(totals?.estimateSeconds ?? 0),
    measure: 'straight_line',
  };
}

/** The label under a figure, so a straight line is never read as a road. */
export function measureLabel(measure: Measure): string {
  return measure === 'road' ? 'Estimated road distance' : 'Straight-line distance';
}

/** Travel plus time at the schools, in seconds. */
export function fieldSeconds(itinerary: Itinerary | undefined): number {
  return Number(itinerary?.totals?.fieldMinutes ?? 0) * 60;
}

/** The placed stops in order. */
export function placedStops(itinerary: Itinerary | undefined): SchoolPin[] {
  return (itinerary?.stops ?? []).map((s) => s.school).filter((s): s is SchoolPin => Boolean(s?.point));
}

/**
 * In-app navigation URL inside Edify (Section 6 — zero external map redirects).
 * Opens Edify's embedded Smart Route Planner turn-by-turn navigation panel for
 * the selected school(s) without ever leaving Edify for Google Maps, Apple Maps,
 * or Waze.
 */
export function inAppDirectionsPath(stops: readonly SchoolPin[], date?: string): string | null {
  const placed = stops.filter((s) => Boolean(s.point));
  if (placed.length === 0) return null;
  const q = new URLSearchParams();
  if (date) q.set('date', date);
  q.set('navigate', placed.map((s) => s.schoolId).join(','));
  return `${ROUTE_PLANNER_PATH}?${q.toString()}`;
}

/**
 * Legacy helper retained for type compatibility: strictly returns Edify's
 * internal navigation path (never an external Google/Apple Maps/Waze URL).
 */
export function directionsUrl(stops: readonly SchoolPin[]): string | null {
  return inAppDirectionsPath(stops);
}

export type SmartOptimizationMode = 'balanced' | 'fastest' | 'shortest' | 'max_schools' | 'priority_schools' | 'as_given';

export interface LatLngPoint {
  lat: number;
  lng: number;
}

export interface RouteStep {
  instruction: string;
  road_name?: string;
  maneuver?: string;
  distance_meters: number;
  duration_seconds: number;
  start: LatLngPoint;
  end: LatLngPoint;
}

export interface TrafficInterval {
  start_index: number;
  end_index: number;
  speed: 'NORMAL' | 'SLOW' | 'TRAFFIC_JAM' | string;
}

export interface AlternativeRouteData {
  id: string;
  summary: string;
  meters: number;
  seconds: number;
  static_seconds?: number;
  traffic_state: 'normal' | 'slow' | 'traffic_jam' | 'unavailable' | string;
  traffic_delay_seconds: number;
  path: LatLngPoint[];
  leg_steps?: RouteStep[][];
  traffic_intervals?: TrafficInterval[];
  warnings?: string[];
}

export interface SchoolPriorityInfo {
  school_id: string;
  band: 'critical' | 'high' | 'core' | 'routine' | 'missing_ssa' | string;
  score: number;
  ssa_average?: number;
  has_confirmed_ssa: boolean;
  is_core: boolean;
  reason: string;
}

export interface RoadConditionReportData {
  id: string;
  road_name: string;
  lat: number;
  lng: number;
  radius_meters: number;
  category: string;
  source: string;
  verification_status: 'unverified' | 'verified' | 'expired' | 'resolved' | string;
  impact_level: 'advisory' | 'delay' | 'impassable' | string;
  notes?: string;
  reported_by_name?: string;
  reported_at: string;
  expires_at: string;
  distance_to_route_meters?: number;
  applicability_note?: string;
}

export interface SmartStopData {
  order: number;
  school_id: string;
  school_code: string;
  school_name: string;
  district: string;
  cluster: string;
  category: string;
  planned_activity_id?: string;
  status: string;
  kind: 'planned' | 'recommended' | string;
  point?: LatLngPoint;
  entrance?: LatLngPoint;
  location_status: string;
  location_version: number;
  arrival: string;
  departure: string;
  visit_minutes: number;
  locked: boolean;
  from_label: string;
  road_available: boolean;
  road_status?: string;
  road_meters: number;
  road_seconds: number;
  straight_line_meters: number;
  steps?: RouteStep[];
  priority: SchoolPriorityInfo;
  inclusion_reason: string;
  conflict?: string;
  warnings?: string[];
}

export interface ExcludedSchoolData {
  school_id: string;
  school_code: string;
  school_name: string;
  district: string;
  planned_activity_id?: string;
  location_status: string;
  reason_code: string;
  reason: string;
  priority: SchoolPriorityInfo;
}

export interface SmartRouteMetrics {
  schools_included: number;
  schools_excluded: number;
  road_complete: boolean;
  road_meters: number;
  road_seconds: number;
  straight_line_meters: number;
  visit_minutes: number;
  break_minutes: number;
  field_minutes: number;
  traffic_state: string;
  traffic_delay_seconds: number;
}

export interface SmartRouteResultData {
  date: string;
  mode: SmartOptimizationMode;
  objective_label: string;
  is_recommended: boolean;
  recommendation_note: string;
  transport_mode: string;
  start?: LatLngPoint;
  start_label?: string;
  end?: LatLngPoint;
  end_label?: string;
  work_start: string;
  work_end: string;
  stops: SmartStopData[];
  excluded: ExcludedSchoolData[];
  path: LatLngPoint[];
  path_is_road: boolean;
  return_leg_meters?: number;
  return_leg_seconds?: number;
  totals: SmartRouteMetrics;
  baseline: SmartRouteMetrics;
  distance_saved_meters: number;
  time_saved_seconds: number;
  alternatives: AlternativeRouteData[];
  traffic_intervals?: TrafficInterval[];
  road_alerts: RoadConditionReportData[];
  warnings: string[];
  provider: string;
  provider_configured: boolean;
  confidence: 'high' | 'medium' | 'limited' | string;
  confidence_note: string;
  input_hash: string;
  calculated_at: string;
}

export interface InAppDirectionsData {
  in_app: boolean;
  road_available: boolean;
  needs_origin?: boolean;
  road_status?: string;
  message?: string;
  provider: string;
  provider_source?: string;
  summary?: string;
  total_meters?: number;
  total_seconds?: number;
  static_seconds?: number;
  traffic_state: string;
  traffic_delay_seconds?: number;
  eta_final?: string;
  path: LatLngPoint[];
  stops: Array<{
    school_id: string;
    school_code: string;
    school_name: string;
    district: string;
    point: LatLngPoint;
    entrance?: LatLngPoint;
    using_entrance: boolean;
    location_status: string;
  }>;
  legs: Array<{
    index: number;
    from_label: string;
    to_label: string;
    distance_meters: number;
    duration_seconds: number;
    eta: string;
    steps?: RouteStep[];
  }>;
  alternatives: AlternativeRouteData[];
  road_alerts: RoadConditionReportData[];
  warnings?: string[];
  calculated_at: string;
}

export interface CalendarRulesData {
  country_code: string;
  timezone: string;
  today: string;
  current_fy: string;
  fy_start: string;
  fy_end: string;
  sundays_disabled: boolean;
  saturdays_enabled: boolean;
  holidays: Array<{ date: string; name: string }>;
  approved_leave_dates: string[];
  blackout_dates: string[];
}

/** The pin's colour key, as the design's legend has them. */
export function pinTone(pin: SchoolPin, kind?: string): 'planned' | 'suggested' | 'completed' | 'other' {
  if (kind === 'location') return 'planned'; // a profile's own school: the plain blue pin
  if (pin.status === 'completed') return 'completed';
  if (kind === 'recommended' || pin.status === 'suggested') return 'suggested';
  if (pin.status === 'planned') return 'planned';
  return 'other';
}

/** Where the reader's field day stands, and what they may press next. */
export interface FieldDayState {
  phase: 'unsaved' | 'saved' | 'started' | 'ended';
  /** Started and not ended: stops can be arrived at and left. */
  running: boolean;
  canSave: boolean;
  canStart: boolean;
}

/** The field day as Save Plan and Start Field Day read it (2026-11-16). */
export function fieldDayState(saved: SavedFieldDay | undefined, date: string, today: string): FieldDayState {
  if (saved?.endedAt) return { phase: 'ended', running: false, canSave: false, canStart: false };
  if (saved?.startedAt) return { phase: 'started', running: true, canSave: false, canStart: false };
  return { phase: saved?.savedAt ? 'saved' : 'unsaved', running: false, canSave: true, canStart: date === today };
}

const KAMPALA_CLOCK = new Intl.DateTimeFormat('en-GB', { timeZone: 'Africa/Kampala', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const KAMPALA_DAY = new Intl.DateTimeFormat('en-CA', { timeZone: 'Africa/Kampala', year: 'numeric', month: '2-digit', day: '2-digit' });

/** "08:02": a recorded time on the Kampala clock; empty for none. */
export function dayClock(rfc3339: string): string {
  if (!rfc3339) return '';
  const at = new Date(rfc3339);
  return Number.isNaN(at.getTime()) ? '' : KAMPALA_CLOCK.format(at);
}

/** Today's date in Kampala ("2026-11-18"), as the gateway's days are. */
export function kampalaToday(now: Date = new Date()): string {
  return KAMPALA_DAY.format(now);
}

/** The planner's page in this web app. */
export const ROUTE_PLANNER_PATH = '/my-plan/smart-route';

/** Who plans routes (routeplan.PlannerRoles; the app's PLANNER_ROLES): the gateway decides. */
const PLANNER_ROLES = new Set(['CCEO', 'Program Lead', 'ProjectCoordinator', 'CountryDirector', 'ImpactAssessment', 'Admin', 'PartnerAdmin', 'PartnerFieldOfficer', 'Accountant']);

/** The app's route icon (lucide "route"), as the sidebar draws icons. */
const ROUTE_ICON =
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/></svg>';

/**
 * The reader's navigation with Smart Route Planner straight after My Plan
 * (owner, 2026-11-19), for a role that plans routes, as the app adds it to its
 * own menu. The gateway's sections are left as they are.
 */
export function withRoutePlanner(sections: NavSection[], role: string): NavSection[] {
  if (!PLANNER_ROLES.has(role)) return sections;
  if (sections.some((section) => section.items.some((item) => item.url === ROUTE_PLANNER_PATH))) return sections;
  const link = create(NavItemSchema, { label: 'Smart Route Planner', url: ROUTE_PLANNER_PATH, iconSvg: ROUTE_ICON, pageKey: 'smart_route_planner', native: true });
  return sections.map((section) => {
    const at = section.items.findIndex((item) => item.url === '/my-plan');
    if (at < 0) return section;
    return { ...section, items: [...section.items.slice(0, at + 1), link, ...section.items.slice(at + 1)] };
  });
}

/**
 * Home's Quick access with Smart Route in My Plan's place (owner, 2026-11-19:
 * "on the quick access change My Plan to Smart Route … link it to route
 * planner"), for a role that plans routes. Another role's shortcuts are left
 * as the gateway gave them.
 */
export function withRouteShortcut(shortcuts: HomeShortcut[], role: string): HomeShortcut[] {
  if (!PLANNER_ROLES.has(role)) return shortcuts;
  return shortcuts.map((shortcut) =>
    shortcut.url.replace(/\/$/, '') === '/my-plan' ? create(HomeShortcutSchema, { label: 'Smart Route', url: ROUTE_PLANNER_PATH, iconSvg: ROUTE_ICON }) : shortcut,
  );
}

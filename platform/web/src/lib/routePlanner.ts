/**
 * The Smart Route Planner's words and links. Road figures are the routing
 * provider's; where it gave none the straight line is shown and labelled, with
 * the existing route engine's planning estimate for time. Nothing here makes
 * a figure up.
 */
import { create } from '@bufbuild/protobuf';

import { NavItemSchema } from '@/gen/edify/screens/v1/navigation_pb';
import type { NavSection } from '@/gen/edify/screens/v1/navigation_pb';
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

const coord = (p: { lat: number; lng: number }) => `${p.lat.toFixed(6)},${p.lng.toFixed(6)}`;

/** The placed stops in order. */
export function placedStops(itinerary: Itinerary | undefined): SchoolPin[] {
  return (itinerary?.stops ?? []).map((s) => s.school).filter((s): s is SchoolPin => Boolean(s?.point));
}

export type MapsApp = 'google' | 'apple' | 'waze';

/**
 * Directions in the staff member's own maps app, keyless: Google Maps takes
 * the whole route (the next stops as waypoints); Apple Maps and Waze take the
 * next stop. No key, no Edify account: the app uses the person's own sign-in.
 */
export function directionsUrl(stops: readonly SchoolPin[], app: MapsApp = 'google'): string | null {
  const points = stops.map((s) => s.point).filter((p): p is NonNullable<SchoolPin['point']> => Boolean(p));
  const next = points[0];
  const last = points[points.length - 1];
  if (!next || !last) return null;
  if (app === 'apple') return `https://maps.apple.com/?daddr=${coord(next)}&dirflg=d`;
  if (app === 'waze') return `https://waze.com/ul?ll=${coord(next)}&navigate=yes`;
  const waypoints = points.slice(0, -1).slice(0, 9).map(coord).join('|');
  const q = new URLSearchParams({ api: '1', destination: coord(last), travelmode: 'driving' });
  if (waypoints) q.set('waypoints', waypoints);
  return `https://www.google.com/maps/dir/?${q.toString()}`;
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

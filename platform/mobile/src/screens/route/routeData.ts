/**
 * The Smart Route Planner in the app: where it is listed, the words its
 * figures are written in, and directions handed to the person's own maps
 * app. Road figures are the routing provider's; with none, the straight line
 * is shown and labelled. The gateway decides who may plan and what they see.
 */
import { create } from '@bufbuild/protobuf';

import type { Itinerary, RouteLeg, RouteTotals, SchoolPin } from '../../gen/edify/routes/v1/routes_pb';
import type { NavSection } from '../../gen/edify/screens/v1/navigation_pb';
import { NavItemSchema, NavSectionSchema } from '../../gen/edify/screens/v1/navigation_pb';

export const ROUTE_URL = 'route:planner';
export const ROUTE_DETAILS_URL = 'route:details';
/** The reviewer's list of location reports (Verify Location). */
export const LOCATION_REPORTS_URL = 'route:location-reports';

/** The design's dark teal (the planner's chosen controls). */
export const ROUTE_TEAL = '#0f4f52';
export const PIN_TONES = { planned: '#1d6fe0', suggested: '#f59e0b', completed: '#1e3a8a', start: '#0284c7', nearby: '#0284c7', other: '#94a3b8' } as const;

/**
 * Who plans field days: My Plan's readers (routeplan rules, planner_roles).
 * The gateway refuses anyone else whatever the menu shows.
 */
const PLANNER_ROLES = new Set(['CCEO', 'Program Lead', 'ProjectCoordinator', 'CountryDirector', 'ImpactAssessment', 'Admin', 'PartnerAdmin', 'PartnerFieldOfficer', 'Accountant']);

/** The day a route URL carries (route:planner?date=YYYY-MM-DD), or ''. */
export function dateOf(url: string): string {
  const at = url.indexOf('?');
  const date = at < 0 ? '' : (new URLSearchParams(url.slice(at + 1)).get('date') ?? '');
  return /^\d{4}-\d{2}-\d{2}$/.test(date) ? date : '';
}

/** The school a route URL is around (route:planner?near=<id>), or ''. */
export function nearOf(url: string): string {
  const at = url.indexOf('?');
  return at < 0 ? '' : (new URLSearchParams(url.slice(at + 1)).get('near') ?? '').slice(0, 64);
}

/** A route URL with its day and, when there is one, the school it is around. */
export function routeUrl(base: string, date: string, near: string): string {
  const q = new URLSearchParams({ date });
  if (near) q.set('near', near);
  return `${base}?${q.toString()}`;
}

export function isRouteUrl(url: string): boolean {
  return url === ROUTE_URL || url.startsWith(`${ROUTE_URL}?`) || url === ROUTE_DETAILS_URL || url.startsWith(`${ROUTE_DETAILS_URL}?`);
}

/** Who reviews location reports (routeplan.ReviewerRoles); the gateway decides. */
const REVIEWER_ROLES = new Set(['Program Lead', 'CountryDirector', 'Admin']);

/** The planner's menu section, or null for a role that neither plans nor reviews locations. */
export function routeSection(role: string): NavSection | null {
  const items = [
    ...(PLANNER_ROLES.has(role) ? [create(NavItemSchema, { label: 'Smart Route Planner', url: ROUTE_URL, native: true })] : []),
    ...(REVIEWER_ROLES.has(role) ? [create(NavItemSchema, { label: 'Location Reports', url: LOCATION_REPORTS_URL, native: true })] : []),
  ];
  return items.length ? create(NavSectionSchema, { label: 'Field Routes', items }) : null;
}

export interface Figures {
  meters: number;
  seconds: number;
  road: boolean;
}

export const km = (meters: number | bigint) => `${(Number(meters) / 1000).toFixed(1)} km`;

/** "1 hr 25 min", "18 min" (the design's way). */
export function hrMin(seconds: number | bigint): string {
  const total = Math.round(Number(seconds) / 60);
  const h = Math.floor(total / 60);
  const m = total % 60;
  if (h === 0) return `${m} min`;
  return m === 0 ? `${h} hr` : `${h} hr ${m} min`;
}

export function legFigures(leg: RouteLeg | undefined): Figures | null {
  if (!leg || (!leg.roadAvailable && Number(leg.straightLineMeters) === 0)) return null;
  if (leg.roadAvailable) return { meters: Number(leg.roadMeters), seconds: Number(leg.roadSeconds), road: true };
  return { meters: Number(leg.straightLineMeters), seconds: Number(leg.estimateSeconds), road: false };
}

/** Road totals only when every leg was measured by road. */
export function totalFigures(totals: RouteTotals | undefined): Figures {
  if (totals?.roadComplete) return { meters: Number(totals.roadMeters), seconds: Number(totals.roadSeconds), road: true };
  return { meters: Number(totals?.straightLineMeters ?? 0), seconds: Number(totals?.estimateSeconds ?? 0), road: false };
}

/** "12.5 km • 22 min", with a straight line said to be one. */
export function legText(leg: RouteLeg | undefined): string {
  const f = legFigures(leg);
  if (!f) return '';
  return `${km(f.meters)} • ${hrMin(f.seconds)}${f.road ? '' : ' (straight line)'}`;
}

export type MapsApp = 'google' | 'apple' | 'waze';

const coord = (p: { lat: number; lng: number }) => `${p.lat.toFixed(6)},${p.lng.toFixed(6)}`;

/**
 * Directions in the person's own maps app, keyless: Google Maps takes the
 * route (later stops as waypoints); Apple Maps and Waze take the next stop.
 */
export function directionsUrl(stops: readonly SchoolPin[], app: MapsApp): string | null {
  const points = stops.map((s) => s.point).filter((p): p is NonNullable<SchoolPin['point']> => Boolean(p));
  const next = points[0];
  const last = points[points.length - 1];
  if (!next || !last) return null;
  if (app === 'apple') return `https://maps.apple.com/?daddr=${coord(next)}&dirflg=d`;
  if (app === 'waze') return `https://waze.com/ul?ll=${coord(next)}&navigate=yes`;
  const q = new URLSearchParams({ api: '1', destination: coord(last), travelmode: 'driving' });
  const waypoints = points.slice(0, -1).slice(0, 9).map(coord).join('|');
  if (waypoints) q.set('waypoints', waypoints);
  return `https://www.google.com/maps/dir/?${q.toString()}`;
}

/** The placed stops in order, for directions. */
export function placedStops(itinerary: Itinerary | undefined): SchoolPin[] {
  return (itinerary?.stops ?? []).map((s) => s.school).filter((s): s is SchoolPin => Boolean(s?.point));
}

/** "Nakasero P/S": the design's short name on a map card. */
export function shortName(name: string): string {
  return name.replace(/\bPrimary School\b/i, 'P/S').replace(/\bPrimary\b$/i, 'P/S');
}

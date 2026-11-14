/*
 * Verify Location (Smart Route brief, parts 2 and 11): the words and checks
 * the report form and the review queue share. The gateway checks everything
 * again; these only spare the person a round trip.
 */
import type { LocationReport } from '@/gen/edify/routes/v1/routes_pb';

export type ReportKind = 'wrong' | 'missing';

/** A school with no usable point is reported missing; one with a point, wrong. */
export function kindFor(locationStatus: string): ReportKind {
  return locationStatus === 'verified' || locationStatus === 'recorded' ? 'wrong' : 'missing';
}

export interface TypedPoint {
  readonly lat: number;
  readonly lng: number;
}

/** Uganda's extent with a margin, as the gateway checks it. */
const BOUNDS = { minLat: -1.6, maxLat: 4.4, minLng: 29.4, maxLng: 35.2 };

/** A typed latitude and longitude, or why they will not do. */
export function parsePoint(latText: string, lngText: string): TypedPoint | string {
  const lat = Number(latText.trim());
  const lng = Number(lngText.trim());
  if (latText.trim() === '' || lngText.trim() === '' || Number.isNaN(lat) || Number.isNaN(lng)) {
    return 'Type the latitude and longitude as numbers, like 0.347600 and 32.582500.';
  }
  if ((lat === 0 && lng === 0) || lat < BOUNDS.minLat || lat > BOUNDS.maxLat || lng < BOUNDS.minLng || lng > BOUNDS.maxLng) {
    return 'That point is not in Uganda. Check the latitude and longitude.';
  }
  return { lat, lng };
}

/** "0.402100, 32.640200". */
export function pointText(point: { lat: number; lng: number } | undefined): string {
  return point ? `${point.lat.toFixed(6)}, ${point.lng.toFixed(6)}` : 'No point given';
}

/** How far the proposed point is from the one shown, in words. */
export function movedText(report: Pick<LocationReport, 'previous' | 'proposed' | 'movedMeters'>): string {
  if (!report.proposed) return 'No new point proposed';
  if (!report.previous) return 'No usable point was on record';
  const m = Number(report.movedMeters);
  return m < 1000 ? `${m} m from the point on record (straight line)` : `${(m / 1000).toFixed(1)} km from the point on record (straight line)`;
}

/** "Device location, accurate to 12 m" and the like. */
export function sourceText(report: Pick<LocationReport, 'pointSource' | 'accuracyM'>): string {
  if (report.pointSource === 'device') return `Device location, accurate to ${Math.round(report.accuracyM)} m`;
  if (report.pointSource === 'typed') return 'Typed in';
  return 'No point given';
}

const DATE = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Africa/Kampala' });

/** "Paul N. on 14 Nov 2026". */
export function reportedText(report: Pick<LocationReport, 'reportedByName' | 'reportedAt'>): string {
  const when = report.reportedAt ? DATE.format(new Date(report.reportedAt)) : '';
  return [report.reportedByName || 'Someone', when ? `on ${when}` : ''].filter(Boolean).join(' ');
}

/** A key for one report, so a retried send never files a second. */
export function reportKey(): string {
  return typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** The longest a device may wait for a fix. */
export const LOCATE_TIMEOUT_MS = 20_000;
/** A device reading coarser than this is refused, as the gateway refuses it. */
export const DEVICE_ACCURACY_MAX_M = 200;

/** Why a capture waits for review, in words (routeplan.Decide's flags). */
export const FLAG_TEXT: Record<string, string> = {
  entrance: 'Entrance point',
  correction: 'Replaces the point on record',
  version_conflict: 'The location changed after this was captured',
  reporter_role: 'Sent by a role that does not capture locations',
  competing: 'Another report on this school is waiting',
  no_point: 'No point given',
  typed_point: 'Typed, not captured by GPS',
  accuracy_poor: 'Poor GPS accuracy',
  accuracy_fair: 'GPS accuracy needed confirming',
  unstable: 'Readings did not agree',
  stale_capture: 'Captured long before it was sent',
  clock_skew: 'The phone’s clock was ahead',
  large_move: 'Moves the school a long way',
  far_from_district: 'Far from the district’s other schools',
};

export const flagsText = (flags: readonly string[]): string => flags.map((f) => FLAG_TEXT[f] ?? f).join(' · ');

/** What happened to a capture or report, in words. */
export const DECISION_TEXT: Record<string, string> = {
  accepted: 'Accepted at once (first location, good GPS)',
  approved: 'Approved',
  rejected: 'Rejected',
  pending: 'Waiting for review',
  noted: 'Confirmed correct on a visit',
};

/** "First location", "Correction", "Entrance point", "Location confirmed". */
export function captureKindText(report: Pick<LocationReport, 'captureKind' | 'kind' | 'target'>): string {
  if (report.captureKind === 'confirm') return 'Location confirmed';
  const first = report.captureKind === 'new' || report.kind === 'missing';
  if (report.target === 'entrance') return first ? 'Entrance point (first)' : 'Entrance point (correction)';
  return first ? 'First location' : 'Correction';
}

/** "14 Nov 2026", or "". */
export function dayText(iso: string): string {
  return iso ? DATE.format(new Date(iso)) : '';
}

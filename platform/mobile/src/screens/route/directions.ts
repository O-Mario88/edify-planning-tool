/**
 * In-app navigation launcher (Section 6): keeps 100% of field navigation inside
 * Edify. External redirects to Google Maps, Apple Maps, and Waze are prohibited.
 */
import type { SchoolPin } from '../../gen/edify/routes/v1/routes_pb';

type Listener = (stops: readonly SchoolPin[]) => void;

const listeners = new Set<Listener>();

/** Subscribe to in-app navigation requests from anywhere in the mobile app. */
export function subscribeInAppDirections(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Triggers Edify's embedded in-app navigation modal for the given placed stops.
 * Never opens an external maps application or external URL scheme.
 */
export function chooseDirections(stops: readonly SchoolPin[]): void {
  const placed = stops.filter((s) => Boolean(s.point));
  if (placed.length === 0) return;
  for (const fn of listeners) fn(placed);
}

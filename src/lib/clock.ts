// The single, swappable "now" for the whole app.
//
// Every FY / quarter / cycle / pace computation derives its sense of "today"
// from here, so the demo is deterministic and tests are stable. The app is
// pinned to a frozen demo date (Nov 15, 2025) rather than the real clock.
//
// Production swap is one line: return `new Date().toISOString().slice(0, 10)`.
// Pure functions across the app accept a `now`/`todayIso` param defaulting to
// `engineNowIso()` so they stay testable.
//
// Client-safe (no `server-only`) so client components can use it too.

/** Frozen demo "today" as an ISO date (YYYY-MM-DD). */
export const ENGINE_NOW_ISO = "2025-11-15";

/** The app's current date as an ISO `YYYY-MM-DD` string. */
export function engineNowIso(): string {
  return ENGINE_NOW_ISO;
}

/** The app's current date as a Date (UTC midnight). */
export function engineNow(): Date {
  return new Date(`${ENGINE_NOW_ISO}T00:00:00Z`);
}

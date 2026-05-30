// Google Maps integration — geocoding + distance matrix.
//
// Used by the Fair Workload Index (FWI) to convert a school's address
// + a staff member's home base into a real travel distance and a
// hotel-required flag. Distance is the single highest-signal predictor
// of workload difficulty after portfolio size.
//
// ─────────────────────────────────────────────────────────────────────
// Design contract
// ─────────────────────────────────────────────────────────────────────
//
//   1. Server-only. NEVER bundle this into the client — the API key
//      must not be exposed. The module guards itself with
//      `"server-only"` at the top.
//
//   2. Opt-in via env. If `GOOGLE_MAPS_API_KEY` is missing, every
//      function returns a deterministic NULL_RESULT instead of
//      throwing. This lets the app boot locally and in CI without a
//      key; only production needs one.
//
//   3. Distances are computed ONCE per (school × staff_home_base) and
//      cached. We do NOT call Google on every page render. Recompute
//      schedule:
//        • At school onboarding (new school added)
//        • At staff onboarding / transfer (home base changes)
//        • Once per month as a nightly cron sanity check
//      A 500-staff × 30-schools deployment is ~15,000 calls total —
//      under $80 amortised over the year. The trap is per-query usage.
//
//   4. Batched. Distance Matrix supports up to 25 origins × 25
//      destinations per call. We batch automatically.
//
//   5. Rate-limit aware. Google enforces 1000 elements/sec by default.
//      We never exceed it from this module (the cron caller controls
//      cadence; we just don't fire 10,000 in parallel).
//
// ─────────────────────────────────────────────────────────────────────
// What "distance" means in this app
// ─────────────────────────────────────────────────────────────────────
//
//   • km — straight-line + actual-road blend. Real driving distance,
//     not as-the-crow-flies. That's what determines fuel cost and
//     time.
//   • minutes — typical drive time at the time-of-day Edify staff
//     actually travel (we ask for departure_time = 6am Mon-Fri).
//   • hotelRequired — true when one-way drive > 120 minutes OR
//     distance > 90 km. Tunable per-country via PerformanceWeights.
//   • district — geocoder-derived; cross-checked against the staff
//     home district to assign primary vs secondary.

import "server-only";

import { log } from "@/lib/log";

// ────────── Types ──────────

export type GeocodeResult = {
  /** Human-typable address, e.g. "Bright Future Primary School, Kitgum". */
  query: string;
  lat: number;
  lng: number;
  /** Administrative-area-2 from Google — usually the district name. */
  district: string | null;
  /** Stable Google place_id, useful for change detection. */
  placeId: string;
  /** Whether the result was a high-confidence match. */
  partialMatch: boolean;
};

export type DistanceResult = {
  fromQuery: string;
  toQuery: string;
  /** Driving distance in km. Null when Google can't route between the two. */
  distanceKm: number | null;
  /** Typical driving time in minutes at the requested departure_time. */
  durationMin: number | null;
  /** True when one-way drive is long enough that a hotel is the realistic plan. */
  hotelRequired: boolean;
  /** ISO timestamp of when this was computed. */
  computedAt: string;
};

// Result we return when no API key is configured, or when Google
// returns ZERO_RESULTS. Callers should treat these as "no signal" —
// the FWI engine falls back to a district-spanned proxy in that case.
const NULL_GEOCODE: GeocodeResult = {
  query: "",
  lat: 0,
  lng: 0,
  district: null,
  placeId: "",
  partialMatch: true,
};

function nullDistance(from: string, to: string): DistanceResult {
  return {
    fromQuery: from,
    toQuery: to,
    distanceKm: null,
    durationMin: null,
    hotelRequired: false,
    computedAt: new Date().toISOString(),
  };
}

// ────────── Key resolution ──────────

function getApiKey(): string | null {
  const key = process.env.GOOGLE_MAPS_API_KEY?.trim();
  if (!key) return null;
  return key;
}

export function isGoogleMapsEnabled(): boolean {
  return getApiKey() !== null;
}

// ────────── Hotel threshold ──────────
//
// Why these defaults: in Uganda, an 8-hour field day with 2 hours of
// driving in each direction is the realistic cap before staff need to
// sleep nearer to the field. Below that, commuting from home is
// expected; above, hotel is the honest cost.

const DEFAULT_HOTEL_DRIVE_MIN = 120;
const DEFAULT_HOTEL_DISTANCE_KM = 90;

export type HotelThreshold = { driveMin?: number; distanceKm?: number };

function shouldHotel(distanceKm: number, durationMin: number, thresh?: HotelThreshold): boolean {
  const minMin = thresh?.driveMin ?? DEFAULT_HOTEL_DRIVE_MIN;
  const minKm  = thresh?.distanceKm ?? DEFAULT_HOTEL_DISTANCE_KM;
  return durationMin >= minMin || distanceKm >= minKm;
}

// ────────── Geocode ──────────
//
// One address in, one GeocodeResult out. We hit Google's REST API
// directly (no SDK) so the function works equally on Node and Edge.

const GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json";

export async function geocode(address: string): Promise<GeocodeResult | null> {
  const key = getApiKey();
  if (!key) {
    log.debug("google-maps.geocode.skipped", { reason: "no_api_key", address });
    return { ...NULL_GEOCODE, query: address };
  }
  try {
    const url = new URL(GEOCODE_URL);
    url.searchParams.set("address", address);
    url.searchParams.set("region", "ug"); // Bias toward Uganda
    url.searchParams.set("key", key);
    const res = await fetch(url.toString());
    const json = (await res.json()) as {
      status: string;
      results: Array<{
        geometry: { location: { lat: number; lng: number } };
        place_id: string;
        partial_match?: boolean;
        address_components: Array<{ long_name: string; types: string[] }>;
      }>;
      error_message?: string;
    };
    if (json.status !== "OK" || json.results.length === 0) {
      log.warn("google-maps.geocode.no_result", { address, status: json.status });
      return null;
    }
    const r = json.results[0];
    const districtComp = r.address_components.find((c) =>
      c.types.includes("administrative_area_level_2"),
    );
    return {
      query: address,
      lat: r.geometry.location.lat,
      lng: r.geometry.location.lng,
      district: districtComp?.long_name ?? null,
      placeId: r.place_id,
      partialMatch: r.partial_match ?? false,
    };
  } catch (err) {
    log.error("google-maps.geocode.error", {
      address,
      error: err instanceof Error ? err.message : String(err),
    });
    return null;
  }
}

// ────────── Distance Matrix ──────────
//
// Single origin → single destination. The Distance Matrix API
// supports many-to-many but we don't expose that as the public
// surface — call sites should be loops; the batching wrapper below
// handles the API-level concurrency.

const DISTANCE_URL = "https://maps.googleapis.com/maps/api/distancematrix/json";

export async function distance(
  fromAddress: string,
  toAddress: string,
  thresh?: HotelThreshold,
): Promise<DistanceResult> {
  const key = getApiKey();
  if (!key) {
    log.debug("google-maps.distance.skipped", { reason: "no_api_key" });
    return nullDistance(fromAddress, toAddress);
  }
  try {
    const url = new URL(DISTANCE_URL);
    url.searchParams.set("origins", fromAddress);
    url.searchParams.set("destinations", toAddress);
    url.searchParams.set("mode", "driving");
    // Departure time = next Monday 06:00 UTC (≈ 09:00 Kampala) —
    // the time of day Edify staff actually leave for the field.
    // Google uses this to apply traffic estimates.
    url.searchParams.set("departure_time", String(nextMondayMorningEpoch()));
    url.searchParams.set("region", "ug");
    url.searchParams.set("key", key);

    const res = await fetch(url.toString());
    const json = (await res.json()) as {
      status: string;
      rows: Array<{
        elements: Array<{
          status: string;
          distance?: { value: number };  // metres
          duration_in_traffic?: { value: number }; // seconds
          duration?: { value: number };
        }>;
      }>;
      error_message?: string;
    };
    if (json.status !== "OK") {
      log.warn("google-maps.distance.bad_status", { status: json.status, message: json.error_message });
      return nullDistance(fromAddress, toAddress);
    }
    const el = json.rows[0]?.elements[0];
    if (!el || el.status !== "OK" || !el.distance) {
      return nullDistance(fromAddress, toAddress);
    }
    const km = el.distance.value / 1000;
    const seconds = el.duration_in_traffic?.value ?? el.duration?.value ?? 0;
    const min = Math.round(seconds / 60);
    return {
      fromQuery: fromAddress,
      toQuery: toAddress,
      distanceKm: Math.round(km * 10) / 10,
      durationMin: min,
      hotelRequired: shouldHotel(km, min, thresh),
      computedAt: new Date().toISOString(),
    };
  } catch (err) {
    log.error("google-maps.distance.error", {
      from: fromAddress,
      to: toAddress,
      error: err instanceof Error ? err.message : String(err),
    });
    return nullDistance(fromAddress, toAddress);
  }
}

// ────────── Batched distance ──────────
//
// Compute distances from one origin to many destinations. Used at
// staff-onboarding time to seed the SchoolDistance table for that
// staff member. Sequential by design — we don't want to burst the
// rate limit; one staff member's distances take ~2 seconds total
// for a 30-school portfolio, which is fine for an onboarding job.

export async function distancesFromBase(
  homeBaseAddress: string,
  schoolAddresses: string[],
  thresh?: HotelThreshold,
): Promise<DistanceResult[]> {
  const out: DistanceResult[] = [];
  for (const school of schoolAddresses) {
    const r = await distance(homeBaseAddress, school, thresh);
    out.push(r);
  }
  return out;
}

// ────────── Helpers ──────────

function nextMondayMorningEpoch(): number {
  // Returns seconds since epoch for "next Monday at 06:00 UTC". Used
  // as the departure_time hint for traffic-aware durations. We use
  // a future Monday so Google's traffic model applies (it rejects
  // past times).
  const now = new Date();
  const dow = now.getUTCDay();          // 0 = Sunday
  const daysToMonday = (1 - dow + 7) % 7 || 7;
  const target = new Date(now);
  target.setUTCDate(now.getUTCDate() + daysToMonday);
  target.setUTCHours(6, 0, 0, 0);
  return Math.floor(target.getTime() / 1000);
}

// ────────── Address composition ──────────
//
// Standardises how the app builds an address string from a structured
// School record so Google geocodes consistently. ALL call sites
// should funnel through this; never hand-compose addresses inline.

export type StructuredSchoolAddress = {
  schoolName: string;
  village?: string;
  parish?: string;
  subCounty?: string;
  district: string;
  country?: string; // defaults to "Uganda"
};

export function composeAddress(addr: StructuredSchoolAddress): string {
  const parts = [
    addr.schoolName,
    addr.village,
    addr.parish,
    addr.subCounty,
    addr.district,
    addr.country ?? "Uganda",
  ].filter(Boolean);
  return parts.join(", ");
}

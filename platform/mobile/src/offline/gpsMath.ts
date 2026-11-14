/**
 * Reading a school's position from the phone's GPS (offline capture brief,
 * 2026-11-14, part 3): several fresh readings are taken, the stale ones
 * (a cached fix from before the capture began) are dropped, and the result
 * is the middle of the best readings with how far apart they were. The
 * accuracy shown is what the phone reported; it is never claimed to be
 * guaranteed.
 */

export interface GpsSample {
  readonly lat: number;
  readonly lng: number;
  /** The phone's reported horizontal accuracy, metres. */
  readonly accuracy: number;
  /** When the phone took the reading (ms since the epoch). */
  readonly at: number;
}

export interface GpsPolicy {
  /** At or better than goodM a fix is Good. */
  readonly goodM: number;
  /** Up to confirmM the person confirms it; beyond, recapture is recommended. */
  readonly confirmM: number;
}

export const DEFAULT_POLICY: GpsPolicy = { goodM: 20, confirmM: 50 };

/** A reading taken this long before the capture began is a cached, stale fix. */
export const STALE_BEFORE_START_MS = 2_000;
/** Enough readings to settle on a point. */
export const SAMPLES_WANTED = 5;
/** Stop waiting for better readings after this. */
export const CAPTURE_TIMEOUT_MS = 30_000;
/** Readings worse than this are not used at all. */
export const SAMPLE_USELESS_M = 500;

export type AccuracyBand = 'good' | 'confirm' | 'recapture';

export function bandOf(accuracy: number, policy: GpsPolicy = DEFAULT_POLICY): AccuracyBand {
  if (accuracy <= policy.goodM) return 'good';
  if (accuracy <= policy.confirmM) return 'confirm';
  return 'recapture';
}

export const BAND_TEXT: Record<AccuracyBand, string> = {
  good: 'Good',
  confirm: 'Fair: check it before saving',
  recapture: 'Poor: capture again in the open',
};

const EARTH_M = 6_371_000;

/** Straight-line metres between two points (haversine). */
export function metersBetween(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLng = (b.lng - a.lng) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_M * Math.asin(Math.sqrt(h));
}

/** The readings usable for this capture: fresh, and not wildly off. */
export function freshSamples(samples: readonly GpsSample[], startedAt: number): GpsSample[] {
  return samples.filter(
    (s) => s.at >= startedAt - STALE_BEFORE_START_MS && Number.isFinite(s.accuracy) && s.accuracy > 0 && s.accuracy <= SAMPLE_USELESS_M,
  );
}

const median = (values: readonly number[]) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

export interface GpsFix {
  readonly lat: number;
  readonly lng: number;
  /** The best reported accuracy among the readings used, metres. */
  readonly accuracy: number;
  /** The furthest a used reading was from the result, metres. */
  readonly spread: number;
  readonly sampleCount: number;
  /** When the newest used reading was taken (ms since the epoch). */
  readonly at: number;
}

/**
 * The point from the readings: the better half (by accuracy, at least
 * three when there are three), their per-axis median, the best accuracy
 * among them and their spread. Null when there is no fresh reading.
 */
export function summarize(samples: readonly GpsSample[], startedAt: number): GpsFix | null {
  const fresh = freshSamples(samples, startedAt);
  if (fresh.length === 0) return null;
  const ranked = [...fresh].sort((a, b) => a.accuracy - b.accuracy);
  const used = ranked.slice(0, Math.max(Math.min(3, ranked.length), Math.ceil(ranked.length / 2)));
  const point = { lat: median(used.map((s) => s.lat)), lng: median(used.map((s) => s.lng)) };
  const spread = Math.max(...used.map((s) => metersBetween(point, s)));
  return {
    lat: point.lat,
    lng: point.lng,
    accuracy: used[0].accuracy,
    spread: Math.round(spread * 10) / 10,
    sampleCount: used.length,
    at: Math.max(...used.map((s) => s.at)),
  };
}

/** Whether the capture can stop: enough good readings that agree. */
export function isSettled(samples: readonly GpsSample[], startedAt: number, policy: GpsPolicy = DEFAULT_POLICY): boolean {
  const fix = summarize(samples, startedAt);
  return fix !== null && fix.sampleCount >= 3 && freshSamples(samples, startedAt).length >= SAMPLES_WANTED && fix.accuracy <= policy.goodM && fix.spread <= policy.goodM;
}

/** Uganda's extent with a margin, as the gateway checks it. */
export function inUganda(lat: number, lng: number): boolean {
  return !(lat === 0 && lng === 0) && lat >= -1.6 && lat <= 4.4 && lng >= 29.4 && lng <= 35.2;
}

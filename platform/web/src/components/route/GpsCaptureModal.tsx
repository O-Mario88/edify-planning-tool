'use client';

/**
 * Mobile-First School GPS Coordinate Capture & Update Modal (Sections 1–10).
 *
 * - Requests browser high-accuracy GPS (`enableHighAccuracy: true, maximumAge: 0`)
 *   ONLY when the user taps the GPS capture action (zero background tracking).
 * - Collects multiple fresh samples (up to 4 readings / 5s) selecting the
 *   tightest accuracy, rejecting stale readings (> 120s old).
 * - Displays full Section 4 confirmation preview (School, School ID, Latitude,
 *   Longitude, GPS accuracy ±m, GPS timestamp, Source: Device location services)
 *   + embedded map showing detected pin (and Old vs Proposed New pin + distance
 *   when updating existing coordinates).
 * - Requires explicit on-premises confirmation before saving.
 * - Supports safe offline queueing in localStorage visibly marked "Pending Sync"
 *   (never "Saved to Database") with automatic synchronization on reconnect.
 */
import { create } from '@bufbuild/protobuf';
import {
  AlertTriangle,
  CheckCircle2,
  CloudOff,
  Loader2,
  LocateFixed,
  MapPin,
  RefreshCw,
  ShieldAlert,
  X,
} from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { ItineraryStopSchema, SchoolPinSchema } from '@/gen/edify/routes/v1/routes_pb';
import type { ItineraryStop } from '@/gen/edify/routes/v1/routes_pb';

import { RouteMap } from './RouteMap';

export interface SavedGpsLocation {
  school_id: string;
  school_code: string;
  school_name: string;
  has_coordinates: boolean;
  latitude?: number;
  longitude?: number;
  accuracy_meters?: number;
  location_status: string;
  source: string;
  version: number;
  verified_at?: string;
  verified_by_name?: string;
}

export interface QueuedOfflineGps {
  capture_id: string;
  school_id: string;
  school_code: string;
  school_name: string;
  latitude: number;
  longitude: number;
  accuracy_meters: number;
  captured_at: string;
  sample_count: number;
  spread_meters: number;
  base_version: number;
  reason: string;
  status: 'pending_sync';
}

const OFFLINE_QUEUE_KEY = 'edify_gps_offline_queue_v1';
const UPDATE_REASONS = [
  'Existing pin was inaccurate',
  'Captured closer to main school compound',
  'School relocated to new campus',
  'Other',
] as const;

export function readOfflineGpsQueue(): QueuedOfflineGps[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(OFFLINE_QUEUE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function writeOfflineGpsQueue(items: QueuedOfflineGps[]) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(items));
  } catch {
    // ignore storage quota failures
  }
}

export async function syncOfflineGpsItem(item: QueuedOfflineGps): Promise<{ ok: boolean; location?: SavedGpsLocation; error?: string }> {
  try {
    const res = await fetch(`/api/schools/${encodeURIComponent(item.school_id)}/gps-location`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        capture_id: item.capture_id,
        latitude: item.latitude,
        longitude: item.longitude,
        accuracy_meters: item.accuracy_meters,
        captured_at: item.captured_at,
        sample_count: item.sample_count,
        spread_meters: item.spread_meters,
        base_version: item.base_version,
        confirmed_at_school: true,
        reason: item.reason,
        is_offline_sync: true,
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, error: typeof data?.error === 'string' ? data.error : 'Sync failed' };
    }
    const rest = readOfflineGpsQueue().filter((q) => q.capture_id !== item.capture_id);
    writeOfflineGpsQueue(rest);
    return { ok: true, location: data.location as SavedGpsLocation };
  } catch {
    return { ok: false, error: 'Still offline' };
  }
}

function haversineM(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const R = 6371000;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const s1 = Math.sin(dLat / 2);
  const s2 = Math.sin(dLng / 2);
  const h = s1 * s1 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * s2 * s2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

function makeUuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

interface Sample {
  lat: number;
  lng: number;
  accuracy: number;
  timestamp: number;
}

export interface GpsCaptureModalProps {
  schoolId: string;
  schoolCode: string;
  schoolName: string;
  existingPoint?: { lat: number; lng: number } | null;
  baseVersion?: number;
  capturedByName?: string;
  onClose: () => void;
  onSaved: (result: { outcome: 'saved' | 'pending_review' | 'pending_sync'; message: string; location?: SavedGpsLocation; queued?: QueuedOfflineGps }) => void;
}

export function GpsCaptureModal({
  schoolId,
  schoolCode,
  schoolName,
  existingPoint = null,
  baseVersion = 0,
  capturedByName = 'Authenticated Staff',
  onClose,
  onSaved,
}: GpsCaptureModalProps) {
  const isUpdate = Boolean(existingPoint);
  const [phase, setPhase] = useState<'capturing' | 'preview' | 'error' | 'saving'>('capturing');
  const [samples, setSamples] = useState<Sample[]>([]);
  const [bestSample, setBestSample] = useState<Sample | null>(null);
  const [errorMsg, setErrorMsg] = useState('');
  const [errorKind, setErrorKind] = useState<'denied' | 'unavailable' | 'timeout' | 'stale' | 'save' | ''>('');
  const [confirmedAtSchool, setConfirmedAtSchool] = useState(false);
  const [reasonChoice, setReasonChoice] = useState<string>(UPDATE_REASONS[0]);
  const [otherReason, setOtherReason] = useState('');
  const [offlineAvailable, setOfflineAvailable] = useState(false);

  const watchRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const stopWatch = useCallback(() => {
    if (watchRef.current !== null && typeof navigator !== 'undefined' && navigator.geolocation) {
      navigator.geolocation.clearWatch(watchRef.current);
      watchRef.current = null;
    }
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const beginCapture = useCallback(() => {
    stopWatch();
    setPhase('capturing');
    setSamples([]);
    setBestSample(null);
    setErrorMsg('');
    setErrorKind('');
    setOfflineAvailable(false);
    setConfirmedAtSchool(false);

    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setErrorKind('unavailable');
      setErrorMsg('Device location services are unavailable in this browser. Open Edify on a GPS-enabled smartphone or HTTPS browser.');
      setPhase('error');
      return;
    }

    const collected: Sample[] = [];
    const finish = () => {
      stopWatch();
      if (collected.length === 0) {
        setErrorKind('timeout');
        setErrorMsg('Timed out waiting for a GPS fix. Move outdoors with a clear view of the sky and retry.');
        setPhase('error');
        return;
      }
      // Pick the freshest reading with the best (smallest) horizontal accuracy.
      const sorted = [...collected].sort((a, b) => a.accuracy - b.accuracy);
      const winner = sorted[0]!;
      const ageMs = Date.now() - winner.timestamp;
      if (ageMs > 120_000) {
        setErrorKind('stale');
        setErrorMsg(`Device returned a stale cached location (${Math.round(ageMs / 1000)}s old). Retake a fresh GPS reading.`);
        setPhase('error');
        return;
      }
      setBestSample(winner);
      setPhase('preview');
    };

    timerRef.current = setTimeout(finish, 4500);

    watchRef.current = navigator.geolocation.watchPosition(
      (pos) => {
        const ts = pos.timestamp || Date.now();
        // Reject obviously stale OS-cached readings (> 120s old).
        if (Date.now() - ts > 120_000) return;
        const next: Sample = {
          lat: pos.coords.latitude,
          lng: pos.coords.longitude,
          accuracy: Math.max(1, pos.coords.accuracy || 15),
          timestamp: ts,
        };
        collected.push(next);
        setSamples([...collected]);
        // Stop early once we have an optimal <= 20m fix and at least 2 readings (or 4 samples total).
        if ((collected.length >= 2 && next.accuracy <= 20) || collected.length >= 4) {
          finish();
        }
      },
      (err) => {
        stopWatch();
        if (err.code === err.PERMISSION_DENIED) {
          setErrorKind('denied');
          setErrorMsg('Location permission was denied. Enable location access for Edify in your device/browser settings, then tap Retry.');
        } else if (err.code === err.TIMEOUT) {
          setErrorKind('timeout');
          setErrorMsg('GPS timed out while acquiring satellites. Move outdoors into the open and tap Retry.');
        } else {
          setErrorKind('unavailable');
          setErrorMsg('Device GPS signal is currently unavailable. Check that Location Services are turned on and tap Retry.');
        }
        setPhase('error');
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 10_000 },
    );
  }, [stopWatch]);

  useEffect(() => {
    beginCapture();
    return stopWatch;
  }, [beginCapture, stopWatch]);

  const spreadMeters = useMemo(() => {
    if (samples.length < 2) return 0;
    let maxDist = 0;
    for (let i = 0; i < samples.length; i++) {
      for (let j = i + 1; j < samples.length; j++) {
        maxDist = Math.max(maxDist, haversineM(samples[i]!, samples[j]!));
      }
    }
    return Math.round(maxDist);
  }, [samples]);

  const displacementMeters = useMemo(() => {
    if (!existingPoint || !bestSample) return null;
    return Math.round(haversineM(existingPoint, { lat: bestSample.lat, lng: bestSample.lng }));
  }, [existingPoint, bestSample]);

  const previewStops = useMemo<ItineraryStop[]>(() => {
    const list: ItineraryStop[] = [];
    if (existingPoint) {
      list.push(
        create(ItineraryStopSchema, {
          order: 0,
          kind: 'planned',
          school: create(SchoolPinSchema, {
            schoolId: `${schoolId}-old`,
            name: 'Existing Location',
            status: 'completed',
            point: { lat: existingPoint.lat, lng: existingPoint.lng },
          }),
        }),
      );
    }
    if (bestSample) {
      list.push(
        create(ItineraryStopSchema, {
          order: 1,
          kind: 'recommended',
          school: create(SchoolPinSchema, {
            schoolId: `${schoolId}-new`,
            name: isUpdate ? 'New GPS Reading' : schoolName,
            status: 'suggested',
            point: { lat: bestSample.lat, lng: bestSample.lng },
          }),
        }),
      );
    }
    return list;
  }, [existingPoint, bestSample, isUpdate, schoolId, schoolName]);

  const accuracyBand = !bestSample
    ? 'good'
    : bestSample.accuracy <= 20
      ? 'good'
      : bestSample.accuracy <= 50
        ? 'fair'
        : 'poor';

  const buildPayload = () => {
    const why = isUpdate ? (reasonChoice === 'Other' ? otherReason.trim() || 'On-site GPS correction' : reasonChoice) : 'Initial on-site GPS capture';
    return {
      capture_id: makeUuid(),
      latitude: bestSample!.lat,
      longitude: bestSample!.lng,
      accuracy_meters: Math.round(bestSample!.accuracy * 10) / 10,
      captured_at: new Date(bestSample!.timestamp).toISOString(),
      sample_count: Math.max(1, samples.length),
      spread_meters: spreadMeters,
      base_version: baseVersion,
      confirmed_at_school: true,
      reason: why,
      source: 'device',
    };
  };

  const handleSave = async () => {
    if (!bestSample || !confirmedAtSchool) return;
    setPhase('saving');
    setErrorMsg('');
    const payload = buildPayload();
    try {
      const res = await fetch(`/api/schools/${encodeURIComponent(schoolId)}/gps-location`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        if (res.status >= 500) setOfflineAvailable(true);
        setErrorKind('save');
        setErrorMsg(typeof data?.error === 'string' ? data.error : 'Could not save school GPS coordinates.');
        setPhase('preview');
        return;
      }
      onSaved({
        outcome: data.outcome === 'pending_review' ? 'pending_review' : 'saved',
        message: data.message || 'School GPS coordinates saved.',
        location: data.location as SavedGpsLocation,
      });
    } catch {
      setOfflineAvailable(true);
      setErrorKind('save');
      setErrorMsg('Network connection interrupted. You can queue this confirmed GPS reading locally as Pending Sync.');
      setPhase('preview');
    }
  };

  const handleQueueOffline = () => {
    if (!bestSample || !confirmedAtSchool) return;
    const p = buildPayload();
    const item: QueuedOfflineGps = {
      capture_id: p.capture_id,
      school_id: schoolId,
      school_code: schoolCode,
      school_name: schoolName,
      latitude: p.latitude,
      longitude: p.longitude,
      accuracy_meters: p.accuracy_meters,
      captured_at: p.captured_at,
      sample_count: p.sample_count,
      spread_meters: p.spread_meters,
      base_version: p.base_version,
      reason: p.reason,
      status: 'pending_sync',
    };
    const next = [item, ...readOfflineGpsQueue().filter((q) => q.school_id !== schoolId)];
    writeOfflineGpsQueue(next);
    onSaved({
      outcome: 'pending_sync',
      message: 'Queued locally as Pending Sync. Will synchronize automatically when connectivity returns.',
      queued: item,
    });
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-slate-900/60 p-0 sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={isUpdate ? 'Update GPS Coordinates' : 'Add GPS Coordinates'}
      data-modal="gps-capture"
    >
      <div className="flex max-h-[94vh] w-full max-w-lg flex-col overflow-hidden rounded-t-[20px] bg-white shadow-2xl sm:rounded-[18px]">
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 bg-[#0f2942] px-5 py-4 text-white">
          <div className="flex items-start gap-2.5">
            <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-[10px] bg-white/15">
              <LocateFixed className="h-5 w-5 text-sky-300" aria-hidden="true" />
            </span>
            <div>
              <h2 className="text-[17px] font-bold leading-snug text-white" style={{ color: '#ffffff' }}>
                {isUpdate ? 'Update GPS Coordinates' : 'Capture School GPS Coordinates'}
              </h2>
              <p className="text-[12px] text-sky-200" style={{ color: '#bae6fd' }}>
                {schoolName} · School ID {schoolCode || '—'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close GPS capture"
            className="grid h-8 w-8 place-items-center rounded-full bg-white/10 text-white hover:bg-white/20"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {phase === 'capturing' ? (
            <div className="flex flex-col items-center gap-3 py-8 text-center" role="status" aria-live="polite">
              <Loader2 className="h-10 w-10 animate-spin text-[var(--brand-primary)]" aria-hidden="true" />
              <p className="text-[16px] font-bold text-slate-900">Reading device GPS…</p>
              <p className="max-w-xs text-[13px] text-slate-600">
                {samples.length === 0
                  ? 'Requesting high-accuracy satellite fix from your device. Stand outdoors in the school compound.'
                  : `Collected ${samples.length} fresh reading${samples.length === 1 ? '' : 's'} — best accuracy ±${Math.round(Math.min(...samples.map((s) => s.accuracy)))} m`}
              </p>
              <p className="text-[11px] text-slate-400">Edify reads GPS once on your action and never tracks personal movement.</p>
            </div>
          ) : null}

          {phase === 'error' ? (
            <div className="space-y-4 py-4">
              <div className="flex items-start gap-3 rounded-[12px] border border-red-200 bg-red-50 p-4 text-[13px] text-red-900" role="alert">
                <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-red-600" aria-hidden="true" />
                <div>
                  <p className="font-bold">
                    {errorKind === 'denied'
                      ? 'Location Permission Denied'
                      : errorKind === 'stale'
                        ? 'Stale GPS Reading Rejected'
                        : 'GPS Reading Unavailable'}
                  </p>
                  <p className="mt-1">{errorMsg}</p>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={beginCapture}
                  className="flex h-11 flex-1 items-center justify-center gap-2 rounded-[10px] bg-[var(--brand-primary)] text-[14px] font-bold text-white hover:bg-[var(--brand-primary-hover)]"
                >
                  <RefreshCw className="h-4 w-4" aria-hidden="true" /> Retry GPS Capture
                </button>
                <button
                  type="button"
                  onClick={onClose}
                  className="h-11 rounded-[10px] border border-slate-300 px-4 text-[14px] font-semibold text-slate-700"
                >
                  Cancel
                </button>
              </div>
            </div>
          ) : null}

          {(phase === 'preview' || phase === 'saving') && bestSample ? (
            <>
              {/* Embedded Map Preview (New pin, or Old vs New on Update) */}
              <div className="relative h-[190px] overflow-hidden rounded-[12px] border border-slate-200">
                <RouteMap
                  stops={previewStops}
                  path={[]}
                  pathIsRoad={false}
                  others={[]}
                  chip={null}
                  onSelect={() => undefined}
                  showLegend={false}
                  showControls={false}
                  className="absolute inset-0"
                />
              </div>

              {/* Accuracy & Displacement Warnings */}
              {accuracyBand === 'poor' ? (
                <div className="flex items-start gap-2.5 rounded-[12px] border border-amber-300 bg-amber-50 p-3 text-[12px] text-amber-950" role="status">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" aria-hidden="true" />
                  <div>
                    <p className="font-bold">Low GPS Accuracy (±{Math.round(bestSample.accuracy)} m)</p>
                    <p>Target accuracy is ±20 m (rural tolerance ±50 m). Move outdoors and tap Retake GPS Reading, or save for supervisor review.</p>
                  </div>
                </div>
              ) : null}

              {displacementMeters !== null ? (
                <div
                  className={`flex items-start gap-2.5 rounded-[12px] border p-3 text-[12px] ${
                    displacementMeters > 1000
                      ? 'border-amber-300 bg-amber-50 text-amber-950'
                      : 'border-blue-200 bg-blue-50 text-blue-950'
                  }`}
                >
                  <MapPin className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  <div>
                    <p className="font-bold">
                      Distance from stored location:{' '}
                      {displacementMeters < 1000 ? `${displacementMeters} m` : `${(displacementMeters / 1000).toFixed(2)} km`}
                    </p>
                    <p className="mt-0.5">
                      Previous: {existingPoint!.lat.toFixed(6)}, {existingPoint!.lng.toFixed(6)} → Proposed: {bestSample.lat.toFixed(6)}, {bestSample.lng.toFixed(6)}
                    </p>
                    {displacementMeters > 1000 ? (
                      <p className="mt-1 font-semibold">
                        Large move (&gt;1 km): will be preserved in audit history and queued for supervisor verification. District assignment is never altered automatically.
                      </p>
                    ) : null}
                  </div>
                </div>
              ) : null}

              {/* Section 4 Metadata Preview Table */}
              <div className="rounded-[12px] border border-slate-200 bg-slate-50/70 p-3.5 text-[13px]" data-block="gps-preview-table">
                <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
                  <div>
                    <dt className="text-[11px] font-semibold uppercase text-slate-500">School</dt>
                    <dd className="font-semibold text-slate-900">{schoolName}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase text-slate-500">School ID</dt>
                    <dd className="font-semibold tabular-nums text-slate-900">{schoolCode || schoolId}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase text-slate-500">Latitude (WGS84)</dt>
                    <dd className="font-bold tabular-nums text-slate-900" data-preview-lat={bestSample.lat.toFixed(6)}>
                      {bestSample.lat.toFixed(6)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase text-slate-500">Longitude (WGS84)</dt>
                    <dd className="font-bold tabular-nums text-slate-900" data-preview-lng={bestSample.lng.toFixed(6)}>
                      {bestSample.lng.toFixed(6)}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase text-slate-500">GPS Accuracy</dt>
                    <dd>
                      <span
                        className={`inline-flex rounded-full px-2 py-0.5 text-[12px] font-bold ${
                          accuracyBand === 'good'
                            ? 'bg-emerald-100 text-emerald-800'
                            : accuracyBand === 'fair'
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-red-100 text-red-800'
                        }`}
                      >
                        ±{Math.round(bestSample.accuracy)} m ({accuracyBand === 'good' ? 'Optimal' : accuracyBand === 'fair' ? 'Rural OK' : 'Poor'})
                      </span>
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase text-slate-500">GPS Timestamp</dt>
                    <dd className="font-medium text-slate-800">
                      {new Date(bestSample.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase text-slate-500">Captured By</dt>
                    <dd className="font-medium text-slate-800">{capturedByName}</dd>
                  </div>
                  <div>
                    <dt className="text-[11px] font-semibold uppercase text-slate-500">Source</dt>
                    <dd className="font-medium text-slate-800">Device location services ({samples.length} reading{samples.length === 1 ? '' : 's'})</dd>
                  </div>
                </dl>
              </div>

              {/* Correction Reason (Updates Only) */}
              {isUpdate ? (
                <div className="space-y-1.5">
                  <label className="block text-[12px] font-bold text-slate-700">
                    Reason for Updating Coordinates
                    <select
                      value={reasonChoice}
                      onChange={(e) => setReasonChoice(e.target.value)}
                      className="mt-1 h-9 w-full rounded-[8px] border border-slate-300 bg-white px-2.5 text-[13px] font-medium"
                    >
                      {UPDATE_REASONS.map((r) => (
                        <option key={r} value={r}>
                          {r}
                        </option>
                      ))}
                    </select>
                  </label>
                  {reasonChoice === 'Other' ? (
                    <input
                      type="text"
                      value={otherReason}
                      onChange={(e) => setOtherReason(e.target.value)}
                      placeholder="Explain why the school coordinates are being updated"
                      className="h-9 w-full rounded-[8px] border border-slate-300 px-3 text-[13px]"
                    />
                  ) : null}
                </div>
              ) : null}

              {/* Mandatory Physical-Presence Confirmation */}
              <label className="flex cursor-pointer items-start gap-2.5 rounded-[10px] border border-slate-200 bg-white p-3 text-[13px] font-medium text-slate-800">
                <input
                  type="checkbox"
                  checked={confirmedAtSchool}
                  onChange={(e) => setConfirmedAtSchool(e.target.checked)}
                  data-confirm-at-school="true"
                  className="mt-0.5 h-4 w-4 shrink-0 accent-[var(--brand-primary)]"
                />
                <span>I confirm that I am physically at <strong>{schoolName}</strong> premises right now.</span>
              </label>

              {errorMsg ? (
                <div className="rounded-[10px] border border-red-200 bg-red-50 px-3 py-2 text-[12px] font-medium text-red-800" role="alert">
                  {errorMsg}
                </div>
              ) : null}

              {/* Section 4 Primary & Secondary Actions */}
              <div className="flex flex-col gap-2 pt-1">
                <button
                  type="button"
                  disabled={!confirmedAtSchool || phase === 'saving'}
                  onClick={() => void handleSave()}
                  data-action="save-school-location"
                  style={
                    confirmedAtSchool && phase !== 'saving'
                      ? { backgroundColor: '#0c569c', color: '#ffffff' }
                      : { backgroundColor: '#e2e8f0', color: '#64748b' }
                  }
                  className="flex h-12 w-full items-center justify-center gap-2 rounded-[12px] text-[14px] font-bold shadow-sm transition-colors hover:brightness-95 disabled:cursor-not-allowed"
                >
                  {phase === 'saving' ? (
                    <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  ) : (
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                  )}
                  {phase === 'saving' ? 'Saving to PostgreSQL…' : 'Save School Location'}
                </button>

                {offlineAvailable || (typeof navigator !== 'undefined' && !navigator.onLine) ? (
                  <button
                    type="button"
                    disabled={!confirmedAtSchool}
                    onClick={handleQueueOffline}
                    data-action="queue-offline-gps"
                    className="flex h-11 w-full items-center justify-center gap-2 rounded-[10px] border border-amber-400 bg-amber-50 text-[13px] font-bold text-amber-950 hover:bg-amber-100 disabled:opacity-45"
                  >
                    <CloudOff className="h-4 w-4" aria-hidden="true" /> Save Offline (Pending Sync)
                  </button>
                ) : null}

                <button
                  type="button"
                  disabled={phase === 'saving'}
                  onClick={beginCapture}
                  data-action="retake-gps-reading"
                  className="flex h-10 w-full items-center justify-center gap-2 rounded-[10px] border border-slate-300 bg-white text-[13px] font-semibold text-slate-700 hover:bg-slate-50"
                >
                  <RefreshCw className="h-4 w-4" aria-hidden="true" /> Retake GPS Reading
                </button>
              </div>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}

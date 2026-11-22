'use client';

/**
 * InAppNavigationPanel — 100% In-App Turn-by-Turn Road Directions inside Edify
 * (Sections 6 & 14).
 *
 * Replaces all external redirects to Google Maps / Apple Maps / Waze.
 * Provides:
 *   - Embedded road directions synchronized with the center map
 *   - Next maneuver hero banner, road names, distance, ETA
 *   - Controlled, debounced device GPS tracking (min 30m / 10s between reroute checks)
 *   - Route deviation detection with one-tap Recalculate
 *   - Alternative route switching & verified/unverified road-condition warnings
 *   - Direct link to open each school's planned activity in My Plan
 */
import Link from 'next/link';
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Compass,
  CornerUpRight,
  LocateFixed,
  Navigation,
  RefreshCw,
  Route,
  X,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { hoursMinutes, km } from '@/lib/routePlanner';
import type { AlternativeRouteData, InAppDirectionsData, LatLngPoint, RouteStep } from '@/lib/routePlanner';

function haversineMeters(a: LatLngPoint, b: LatLngPoint): number {
  const toRad = (d: number) => (d * Math.PI) / 180;
  const R = 6371000;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const sinLat = Math.sin(dLat / 2);
  const sinLng = Math.sin(dLng / 2);
  const x = sinLat * sinLat + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * sinLng * sinLng;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(x)));
}

function minDistanceToPath(pt: LatLngPoint, path: readonly LatLngPoint[]): number {
  if (path.length === 0) return 0;
  const stride = Math.max(1, Math.floor(path.length / 120));
  let best = Number.POSITIVE_INFINITY;
  for (let i = 0; i < path.length; i += stride) {
    const d = haversineMeters(pt, path[i]!);
    if (d < best) best = d;
  }
  return best;
}

export interface InAppNavigationPanelProps {
  directions: InAppDirectionsData | null;
  loading: boolean;
  error: string | null;
  activeAlternativeId: string | null;
  onSelectAlternative: (id: string | null) => void;
  onRecalculateFromGps: (origin: LatLngPoint) => void;
  onUserLocationChange: (loc: LatLngPoint | null) => void;
  onClose: () => void;
}

export function InAppNavigationPanel({
  directions,
  loading,
  error,
  activeAlternativeId,
  onSelectAlternative,
  onRecalculateFromGps,
  onUserLocationChange,
  onClose,
}: InAppNavigationPanelProps) {
  const [tracking, setTracking] = useState(false);
  const [gpsStatus, setGpsStatus] = useState<string>('');
  const [userPos, setUserPos] = useState<LatLngPoint | null>(null);
  const [offRoute, setOffRoute] = useState(false);
  const [activeLegIdx, setActiveLegIdx] = useState(0);
  const lastUpdateRef = useRef<{ at: number; pos: LatLngPoint | null }>({ at: 0, pos: null });
  const watchIdRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (watchIdRef.current !== null && typeof navigator !== 'undefined' && navigator.geolocation) {
        navigator.geolocation.clearWatch(watchIdRef.current);
      }
    };
  }, []);

  const stopTracking = () => {
    if (watchIdRef.current !== null && navigator.geolocation) {
      navigator.geolocation.clearWatch(watchIdRef.current);
      watchIdRef.current = null;
    }
    setTracking(false);
    setGpsStatus('GPS tracking paused.');
  };

  const startTracking = () => {
    if (typeof navigator === 'undefined' || !navigator.geolocation) {
      setGpsStatus('Device GPS is unavailable in this browser. Road steps remain visible below.');
      return;
    }
    setTracking(true);
    setGpsStatus('Acquiring GPS fix…');
    watchIdRef.current = navigator.geolocation.watchPosition(
      ({ coords }) => {
        const now = Date.now();
        const next: LatLngPoint = { lat: coords.latitude, lng: coords.longitude };
        const prev = lastUpdateRef.current;
        // Controlled debouncing: ignore micro-jitter (< 30m within 10s) to protect battery & API quota.
        if (prev.pos && now - prev.at < 10_000 && haversineMeters(prev.pos, next) < 30) {
          return;
        }
        lastUpdateRef.current = { at: now, pos: next };
        setUserPos(next);
        onUserLocationChange(next);
        setGpsStatus(`Live GPS active (±${Math.round(coords.accuracy)} m)`);
        if (directions?.path && directions.path.length >= 2) {
          const drift = minDistanceToPath(next, directions.path);
          setOffRoute(drift > 180);
        }
      },
      (err) => {
        setTracking(false);
        setGpsStatus(
          err.code === err.PERMISSION_DENIED
            ? 'Location permission denied. Road overview and turn-by-turn steps remain available.'
            : 'GPS signal temporarily unavailable. Showing calculated road instructions.',
        );
      },
      { enableHighAccuracy: true, timeout: 12_000, maximumAge: 10_000 },
    );
  };

  const selectedAlt: AlternativeRouteData | undefined = directions?.alternatives.find((a) => a.id === activeAlternativeId);
  const displayMeters = selectedAlt ? selectedAlt.meters : (directions?.total_meters ?? 0);
  const displaySeconds = selectedAlt ? selectedAlt.seconds : (directions?.total_seconds ?? 0);
  const displayTraffic = selectedAlt ? selectedAlt.traffic_state : (directions?.traffic_state ?? 'unavailable');
  const activeLeg = directions?.legs[activeLegIdx] ?? directions?.legs[0];
  const legSteps: RouteStep[] = selectedAlt?.leg_steps?.[activeLegIdx] ?? activeLeg?.steps ?? [];
  const nextStep = legSteps[0];

  const trafficBadge = (state: string) => {
    switch (state) {
      case 'normal':
        return { label: 'Normal traffic', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' };
      case 'slow':
        return { label: 'Slow traffic', cls: 'bg-amber-50 text-amber-800 border-amber-200' };
      case 'traffic_jam':
        return { label: 'Traffic jam', cls: 'bg-red-50 text-red-700 border-red-200' };
      default:
        return { label: 'Live traffic unavailable', cls: 'bg-slate-100 text-slate-600 border-slate-200' };
    }
  };
  const tBadge = trafficBadge(displayTraffic);

  return (
    <div className="flex flex-col gap-3.5" data-block="in-app-navigation">
      <div className="flex items-center justify-between gap-2 border-b border-[var(--edify-border)] pb-3">
        <div className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-[10px] bg-[var(--brand-primary)] text-white">
            <Navigation className="h-4 w-4" aria-hidden="true" />
          </span>
          <div>
            <h2 className="text-[16px] font-bold text-[var(--edify-text)]">In-App Navigation</h2>
            <p className="text-[12px] text-[var(--edify-text-muted)]">Turn-by-turn road guidance inside Edify</p>
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Back to itinerary"
          className="grid h-8 w-8 place-items-center rounded-[8px] text-slate-500 hover:bg-slate-100 hover:text-slate-900"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading ? (
        <div className="rounded-[12px] border border-[var(--edify-border)] bg-slate-50 p-5 text-center text-[14px] text-slate-600">
          Calculating road-network directions…
        </div>
      ) : error ? (
        <div className="rounded-[12px] border border-red-200 bg-red-50 p-4 text-[13px] text-red-800" role="alert">
          {error}
        </div>
      ) : !directions ? (
        <div className="rounded-[12px] border border-[var(--edify-border)] bg-slate-50 p-4 text-[13px] text-slate-600">
          Click <strong>Get Directions</strong> on any stop or route to launch in-app road guidance.
        </div>
      ) : (
        <>
          {/* Hero Next-Maneuver Banner */}
          <div className="rounded-[14px] bg-[#0f2942] p-4 text-white shadow-sm">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-[10px] bg-white/15">
                <CornerUpRight className="h-5 w-5 text-sky-300" aria-hidden="true" />
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-sky-300">
                  {directions.road_available ? 'Next Road Maneuver' : 'Navigation Notice'}
                </p>
                <p className="mt-0.5 text-[15px] font-bold leading-snug">
                  {nextStep
                    ? nextStep.instruction
                    : directions.road_available
                      ? `Follow highlighted road to ${activeLeg?.to_label ?? directions.stops[0]?.school_name ?? 'destination'}`
                      : directions.message || 'Road access requires verification'}
                </p>
                {nextStep?.road_name ? (
                  <p className="mt-1 text-[12px] text-slate-300">
                    {nextStep.road_name} · {km(nextStep.distance_meters)} ({hoursMinutes(nextStep.duration_seconds)})
                  </p>
                ) : null}
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-white/15 pt-2.5 text-[12px]">
              <span className="font-semibold">
                {directions.road_available ? `${km(displayMeters)} · ${hoursMinutes(displaySeconds)}` : 'Road access requires verification'}
              </span>
              {directions.eta_final ? <span className="text-sky-200">ETA {directions.eta_final}</span> : null}
            </div>
          </div>

          {/* Live GPS Controls & Route Deviation Rerouting */}
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-[12px] border border-[var(--edify-border)] bg-slate-50/80 px-3 py-2.5">
            <div className="flex items-center gap-2 text-[12px] text-slate-700">
              <Compass className={`h-4 w-4 ${tracking ? 'text-emerald-600' : 'text-slate-400'}`} aria-hidden="true" />
              <span>{gpsStatus || 'Enable live GPS to track progress along the route.'}</span>
            </div>
            <div className="flex items-center gap-1.5">
              {tracking ? (
                <button
                  type="button"
                  onClick={stopTracking}
                  className="rounded-[8px] border border-slate-300 bg-white px-2.5 py-1 text-[12px] font-semibold text-slate-700 hover:bg-slate-100"
                >
                  Pause GPS
                </button>
              ) : (
                <button
                  type="button"
                  onClick={startTracking}
                  className="inline-flex items-center gap-1 rounded-[8px] bg-[var(--brand-primary)] px-2.5 py-1 text-[12px] font-semibold text-white hover:bg-[var(--brand-primary-hover)]"
                >
                  <LocateFixed className="h-3.5 w-3.5" aria-hidden="true" /> Track GPS
                </button>
              )}
              {userPos ? (
                <button
                  type="button"
                  onClick={() => {
                    setOffRoute(false);
                    onRecalculateFromGps(userPos);
                  }}
                  className="inline-flex items-center gap-1 rounded-[8px] border border-[var(--brand-primary)] bg-white px-2.5 py-1 text-[12px] font-semibold text-[var(--brand-primary)] hover:bg-blue-50"
                >
                  <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Reroute
                </button>
              ) : null}
            </div>
          </div>

          {offRoute && userPos ? (
            <div className="flex items-center justify-between gap-2 rounded-[10px] border border-amber-300 bg-amber-50 px-3 py-2 text-[12px] text-amber-900" role="status">
              <span className="font-semibold">You appear off the planned road route.</span>
              <button
                type="button"
                onClick={() => {
                  setOffRoute(false);
                  onRecalculateFromGps(userPos);
                }}
                className="rounded-[7px] bg-amber-600 px-2.5 py-1 font-semibold text-white hover:bg-amber-700"
              >
                Recalculate now
              </button>
            </div>
          ) : null}

          {/* Traffic & Provider Status */}
          <div className="flex flex-wrap items-center gap-2 text-[12px]">
            <span className={`rounded-full border px-2.5 py-0.5 font-semibold ${tBadge.cls}`}>{tBadge.label}</span>
            <span className="rounded-full bg-slate-100 px-2.5 py-0.5 font-medium text-slate-600">
              Provider: {directions.provider === 'none' ? 'Not configured' : directions.provider.toUpperCase()}
            </span>
          </div>

          {/* Alternative Routes Comparison */}
          {directions.alternatives.length > 0 ? (
            <div className="space-y-1.5">
              <p className="text-[12px] font-bold uppercase tracking-wide text-slate-500">Alternative Road Routes</p>
              <div className="grid grid-cols-1 gap-1.5">
                <button
                  type="button"
                  onClick={() => onSelectAlternative(null)}
                  className={`flex items-center justify-between rounded-[10px] border px-3 py-2 text-left text-[13px] ${
                    !activeAlternativeId
                      ? 'border-[var(--brand-primary)] bg-blue-50/70 font-semibold text-[var(--brand-primary)]'
                      : 'border-[var(--edify-border)] bg-white text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  <span>Primary: {directions.summary || 'Recommended Road'}</span>
                  <span className="tabular-nums">
                    {km(directions.total_meters ?? 0)} · {hoursMinutes(directions.total_seconds ?? 0)}
                  </span>
                </button>
                {directions.alternatives.map((alt, i) => (
                  <button
                    key={alt.id}
                    type="button"
                    onClick={() => onSelectAlternative(alt.id)}
                    className={`flex items-center justify-between rounded-[10px] border px-3 py-2 text-left text-[13px] ${
                      activeAlternativeId === alt.id
                        ? 'border-[var(--brand-primary)] bg-blue-50/70 font-semibold text-[var(--brand-primary)]'
                        : 'border-[var(--edify-border)] bg-white text-slate-700 hover:bg-slate-50'
                    }`}
                  >
                    <span>
                      Alt {i + 1}: {alt.summary}
                    </span>
                    <span className="tabular-nums">
                      {km(alt.meters)} · {hoursMinutes(alt.seconds)}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {/* Road Condition Alerts */}
          {directions.road_alerts.length > 0 ? (
            <div className="space-y-1.5 rounded-[12px] border border-amber-300 bg-amber-50 p-3 text-[12px] text-amber-950">
              <p className="flex items-center gap-1.5 font-bold">
                <AlertTriangle className="h-4 w-4 text-amber-700" aria-hidden="true" /> Road Condition Warnings
              </p>
              {directions.road_alerts.map((al) => (
                <div key={al.id} className="rounded-[8px] bg-white/80 px-2.5 py-1.5">
                  <p className="font-semibold">
                    {al.road_name} · {al.category.replaceAll('_', ' ')} ({al.verification_status})
                  </p>
                  <p className="text-[11px] text-amber-900">{al.applicability_note || al.notes}</p>
                </div>
              ))}
            </div>
          ) : null}

          {/* Leg Tabs for Multi-School Routes */}
          {directions.legs.length > 1 ? (
            <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Route legs">
              {directions.legs.map((leg, i) => (
                <button
                  key={leg.index}
                  type="button"
                  role="tab"
                  aria-selected={activeLegIdx === i}
                  onClick={() => setActiveLegIdx(i)}
                  className={`rounded-[8px] px-2.5 py-1 text-[12px] font-semibold ${
                    activeLegIdx === i
                      ? 'bg-[var(--brand-primary)] text-white'
                      : 'border border-[var(--edify-border)] bg-white text-slate-700 hover:bg-slate-50'
                  }`}
                >
                  Leg {i + 1} → {leg.to_label.slice(0, 18)}
                </button>
              ))}
            </div>
          ) : null}

          {/* Turn-by-Turn Steps List */}
          {activeLeg ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between text-[12px] font-bold text-slate-600">
                <span className="flex items-center gap-1.5">
                  <Route className="h-3.5 w-3.5 text-[var(--brand-primary)]" aria-hidden="true" />
                  {activeLeg.from_label} → {activeLeg.to_label}
                </span>
                <span>ETA {activeLeg.eta}</span>
              </div>
              {legSteps.length > 0 ? (
                <ol className="max-h-[280px] space-y-1.5 overflow-y-auto pr-1">
                  {legSteps.map((st, idx) => (
                    <li
                      key={`${idx}-${st.instruction}`}
                      className="flex items-start gap-2.5 rounded-[10px] border border-slate-100 bg-slate-50/70 px-3 py-2 text-[13px]"
                    >
                      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-[var(--brand-primary)]/12 text-[11px] font-bold text-[var(--brand-primary)]">
                        {idx + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="font-medium text-slate-800">{st.instruction}</p>
                        <p className="text-[11px] text-slate-500">
                          {km(st.distance_meters)} · {hoursMinutes(st.duration_seconds)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className="rounded-[10px] bg-slate-50 px-3 py-2 text-[12px] text-slate-600">
                  Detailed turn steps are unavailable for this leg; follow the highlighted road geometry on the map.
                </p>
              )}
            </div>
          ) : null}

          {/* Destination Schools Quick Actions inside Edify */}
          {directions.stops.length > 0 ? (
            <div className="space-y-1.5 border-t border-[var(--edify-border)] pt-3">
              <p className="text-[12px] font-bold text-slate-600">Destinations (Stay inside Edify)</p>
              {directions.stops.map((st) => (
                <div key={st.school_id} className="flex items-center justify-between gap-2 rounded-[10px] border border-[var(--edify-border)] px-3 py-2 text-[12px]">
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-slate-900">{st.school_name}</p>
                    <p className="text-[11px] text-slate-500">
                      ID {st.school_code} · {st.using_entrance ? 'Routing to verified entrance' : st.location_status}
                    </p>
                  </div>
                  <Link
                    href={`/schools/${encodeURIComponent(st.school_id)}`}
                    className="inline-flex shrink-0 items-center gap-1 rounded-[7px] border border-[var(--brand-primary)] px-2.5 py-1 font-semibold text-[var(--brand-primary)] hover:bg-blue-50"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> Open School <ArrowRight className="h-3 w-3" />
                  </Link>
                </div>
              ))}
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}

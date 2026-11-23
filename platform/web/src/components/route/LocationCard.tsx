'use client';

/*
 * School Location & GPS Coordinate Capture Card (Sections 2, 3, 4, 5, 7, 10):
 * - Conditional UI based on authoritative PostgreSQL coordinates:
 *     A. No coordinates -> "GPS Missing" badge + "Tap to Add GPS Coordinates"
 *     B. Stored coordinates -> "GPS Recorded" badge + lat/lng, accuracy,
 *        verification date, source + "Update GPS Coordinates"
 * - Automatically switches Add -> Update immediately upon server confirmation
 *   without requiring a full page reload.
 * - Offline captures display clearly as "Pending Sync" (never "Saved to Database")
 *   with automatic synchronization when online.
 * - "Get Directions" opens Edify's embedded In-App Navigation (zero external maps).
 */
import { create, fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { AlertTriangle, CheckCircle2, CloudOff, LocateFixed, MapPin, MapPinOff, RefreshCw } from 'lucide-react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import { GetSchoolLocationResponseSchema, ItineraryStopSchema, PointSchema, SchoolPinSchema } from '@/gen/edify/routes/v1/routes_pb';
import type { LocationReport } from '@/gen/edify/routes/v1/routes_pb';
import { dayText } from '@/lib/locationReport';
import { directionsUrl } from '@/lib/routePlanner';

import { GpsCaptureModal, readOfflineGpsQueue, syncOfflineGpsItem } from './GpsCaptureModal';
import type { QueuedOfflineGps } from './GpsCaptureModal';
import { LocationHistory } from './LocationHistory';
import { ReportDetails, ReportForm, ReviewControls } from './LocationReport';
import { RouteIcon } from './RouteIcons';
import { RouteMap } from './RouteMap';

const STATUS: Record<string, string> = {
  verified: 'Verified device GPS',
  recorded: 'School Directory (unverified)',
  missing: 'No location recorded',
  invalid: 'Recorded location looks invalid',
};

interface RailFactsProps {
  readonly point: { readonly lat: number; readonly lng: number };
  readonly status: string;
  readonly accuracy: number | null;
  readonly verifiedAt: string;
  readonly verifiedBy: string;
  readonly source: string;
  readonly nearby: string;
}

/** The narrow card's record: the coordinates with their state, then one labelled row per fact. */
function RailFacts({ point, status, accuracy, verifiedAt, verifiedBy, source, nearby }: RailFactsProps) {
  const verified = status === 'verified';
  const rows: readonly (readonly [string, string])[] = [
    ['Accuracy', accuracy ? `±${Math.round(accuracy)} m` : 'Not recorded'],
    ['Last Verified', verifiedAt ? dayText(verifiedAt) : 'Not verified'],
    ['Source', source || 'Not recorded'],
    ['Verified By', verifiedBy || 'Not verified'],
    ['Nearby Schools', nearby],
  ];
  return (
    <div>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-[12px] font-medium text-[var(--edify-text-muted)]">GPS Coordinates</p>
          <p className="text-[15px] font-bold tabular-nums text-[var(--edify-text)]" data-stored-coords="true">
            {point.lat.toFixed(6)}, {point.lng.toFixed(6)}
          </p>
        </div>
        <span
          data-badge={verified ? 'gps-verified' : 'gps-unverified'}
          className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[12px] font-bold ${
            verified
              ? 'border-[var(--edify-success-border)] bg-[var(--edify-success-light)] text-[var(--edify-success-text)]'
              : 'border-[var(--edify-warning-border)] bg-[var(--edify-warning-light)] text-[var(--edify-warning-text)]'
          }`}
        >
          {verified ? <CheckCircle2 className="h-3.5 w-3.5" aria-hidden="true" /> : <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />}
          {verified ? 'Verified' : 'Unverified'}
        </span>
      </div>
      <dl className="mt-2 divide-y divide-[var(--edify-border)] text-[13px]">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-baseline justify-between gap-3 py-1.5">
            <dt className="shrink-0 text-[var(--edify-text-muted)]">{label}</dt>
            <dd className="min-w-0 text-right font-semibold text-[var(--edify-text)]">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function LocationCard({ answer: json, variant = 'wide' }: { answer: JsonValue; variant?: 'wide' | 'rail' }) {
  const isRail = variant === 'rail';
  const answer = useMemo(() => fromJson(GetSchoolLocationResponseSchema, json), [json]);
  const router = useRouter();
  const baseSchool = answer.school;

  // Live local state so capturing GPS switches Add -> Update immediately without page refresh.
  const [livePoint, setLivePoint] = useState<{ lat: number; lng: number } | null>(
    baseSchool?.point ? { lat: baseSchool.point.lat, lng: baseSchool.point.lng } : null,
  );
  const [liveStatus, setLiveStatus] = useState<string>(baseSchool?.locationStatus ?? 'missing');
  const [liveVersion, setLiveVersion] = useState<number>(answer.version || 0);
  const [liveAccuracy, setLiveAccuracy] = useState<number | null>(answer.accuracyMeters ?? null);
  const [liveVerifiedAt, setLiveVerifiedAt] = useState<string>(answer.verifiedAt || '');
  const [liveVerifiedBy, setLiveVerifiedBy] = useState<string>(answer.verifiedByName || '');
  // The gateway names the source; an older gateway does not, so its status still decides.
  const [liveSource, setLiveSource] = useState<string>(
    answer.locationSource || (baseSchool?.locationStatus === 'verified' ? 'Device location services' : 'School Directory'),
  );

  const [pending, setPending] = useState<LocationReport | undefined>(answer.pendingReport);
  const [isCapturing, setIsCapturing] = useState(false);
  const [isReporting, setIsReporting] = useState(false);
  const [notice, setNotice] = useState('');
  const [isHistoryOpen, setIsHistoryOpen] = useState(false);
  const [offlineQueued, setOfflineQueued] = useState<QueuedOfflineGps | null>(null);
  const [syncingOffline, setSyncingOffline] = useState(false);

  // Check local offline queue & auto-sync on reconnect (Section 10).
  useEffect(() => {
    if (!baseSchool) return;
    const check = () => {
      const hit = readOfflineGpsQueue().find((q) => q.school_id === baseSchool.schoolId) ?? null;
      setOfflineQueued(hit);
    };
    check();
    const onOnline = async () => {
      const hit = readOfflineGpsQueue().find((q) => q.school_id === baseSchool.schoolId);
      if (!hit) return;
      setSyncingOffline(true);
      const res = await syncOfflineGpsItem(hit);
      setSyncingOffline(false);
      if (res.ok && res.location?.latitude !== undefined && res.location?.longitude !== undefined) {
        setOfflineQueued(null);
        setLivePoint({ lat: res.location.latitude, lng: res.location.longitude });
        setLiveStatus(res.location.location_status || 'verified');
        setLiveVersion(res.location.version);
        setLiveAccuracy(res.location.accuracy_meters ?? null);
        setLiveVerifiedAt(res.location.verified_at || new Date().toISOString());
        setLiveVerifiedBy(res.location.verified_by_name || '');
        setLiveSource('Device GPS (Field)');
        setNotice('Offline GPS capture synchronized and saved to PostgreSQL.');
        router.refresh();
      }
    };
    window.addEventListener('online', onOnline);
    return () => window.removeEventListener('online', onOnline);
  }, [baseSchool, router]);

  const effectiveSchool = useMemo(() => {
    if (!baseSchool) return null;
    return create(SchoolPinSchema, {
      ...baseSchool,
      locationStatus: liveStatus,
      locationVersion: liveVersion,
      point: livePoint ? create(PointSchema, { lat: livePoint.lat, lng: livePoint.lng }) : undefined,
    });
  }, [baseSchool, livePoint, liveStatus, liveVersion]);

  const stops = useMemo(
    () => (effectiveSchool?.point ? [create(ItineraryStopSchema, { order: 0, school: effectiveSchool, kind: 'location' })] : []),
    [effectiveSchool],
  );

  if (!effectiveSchool) return null;

  const directions = directionsUrl([
    answer.entrance ? create(SchoolPinSchema, { ...effectiveSchool, point: answer.entrance }) : effectiveSchool,
  ]);

  const handleManualOfflineSync = async () => {
    if (!offlineQueued) return;
    setSyncingOffline(true);
    const res = await syncOfflineGpsItem(offlineQueued);
    setSyncingOffline(false);
    if (res.ok && res.location?.latitude !== undefined && res.location?.longitude !== undefined) {
      setOfflineQueued(null);
      setLivePoint({ lat: res.location.latitude, lng: res.location.longitude });
      setLiveStatus(res.location.location_status || 'verified');
      setLiveVersion(res.location.version);
      setLiveAccuracy(res.location.accuracy_meters ?? null);
      setLiveVerifiedAt(res.location.verified_at || new Date().toISOString());
      setLiveVerifiedBy(res.location.verified_by_name || '');
      setLiveSource('Device GPS (Field)');
      setNotice('Offline GPS capture synchronized and saved to PostgreSQL.');
      router.refresh();
    } else {
      setNotice(res.error || 'Still unable to reach server; capture remains queued as Pending Sync.');
    }
  };

  return (
    <section
      className="card p-5"
      aria-labelledby="location-title"
      data-block="school-location"
      data-has-gps={livePoint ? 'true' : 'false'}
    >
      {/* Header Row with Conditional GPS Missing / GPS Recorded Badge */}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="location-title" className="flex items-center gap-2 text-[17px] font-bold text-[var(--edify-text)]">
          <MapPin className="h-5 w-5 text-[var(--brand-primary)]" aria-hidden="true" /> {isRail ? 'Location & GPS' : 'School Location'}
        </h2>
        <div className="flex items-center gap-2">
          {offlineQueued ? (
            <span className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-[12px] font-bold text-amber-800" data-badge="pending-sync">
              <CloudOff className="h-3.5 w-3.5" aria-hidden="true" /> Pending Sync
            </span>
          ) : null}
          {livePoint ? (
            isRail ? null : (
              <span className="inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 text-[12px] font-bold text-emerald-700" data-badge="gps-recorded">
                GPS Recorded
              </span>
            )
          ) : (
            <span className="inline-flex items-center rounded-full border border-amber-300 bg-amber-50 px-2.5 py-0.5 text-[12px] font-bold text-amber-800" data-badge="gps-missing">
              GPS Missing
            </span>
          )}
        </div>
      </div>

      {/* Offline Pending Sync Banner */}
      {offlineQueued ? (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-[10px] border border-amber-300 bg-amber-50 px-3.5 py-2.5 text-[13px] text-amber-950" role="status">
          <div>
            <p className="font-bold">Pending Sync — Offline GPS Captured ({offlineQueued.latitude.toFixed(6)}, {offlineQueued.longitude.toFixed(6)}, ±{Math.round(offlineQueued.accuracy_meters)} m)</p>
            <p className="text-[12px]">Saved on this device only (not yet persisted to PostgreSQL). Will sync automatically when online.</p>
          </div>
          <button
            type="button"
            disabled={syncingOffline}
            onClick={() => void handleManualOfflineSync()}
            className="rounded-[8px] bg-amber-700 px-3 py-1.5 text-[12px] font-bold text-white hover:bg-amber-800 disabled:opacity-50"
          >
            {syncingOffline ? 'Syncing…' : 'Sync Now'}
          </button>
        </div>
      ) : null}

      {/* STATE B — School WITH Existing Coordinates */}
      {livePoint ? (
        <div className={isRail ? 'mt-3 space-y-3' : 'mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]'}>
          <div className={`relative ${isRail ? 'h-[200px]' : 'h-[260px]'} overflow-hidden rounded-[12px] border border-[var(--edify-border)]`}>
            <RouteMap stops={stops} path={[]} pathIsRoad={false} others={[]} chip={null} onSelect={() => undefined} className="absolute inset-0" showLegend={false} showControls={false} compact={isRail} />
          </div>
          <div className="flex flex-col justify-between gap-3">
            {isRail ? (
              <RailFacts
                point={livePoint}
                status={liveStatus}
                accuracy={liveAccuracy}
                verifiedAt={liveVerifiedAt}
                verifiedBy={liveVerifiedBy}
                source={liveSource}
                nearby={`${answer.nearbySchools} within ${answer.nearbyRadiusKm} km`}
              />
            ) : (
            <dl className="space-y-2.5 text-[14px]">
              <div>
                <dt className="text-[12px] font-semibold uppercase tracking-wide text-[var(--edify-text-muted)]">Stored Coordinates (WGS84)</dt>
                <dd className="mt-0.5 flex items-center gap-1.5 text-[15px] font-bold tabular-nums text-[var(--edify-text)]" data-stored-coords="true">
                  <MapPin className="h-4 w-4 text-[var(--brand-primary)]" aria-hidden="true" />
                  {livePoint.lat.toFixed(6)}, {livePoint.lng.toFixed(6)}
                </dd>
              </div>
              <div>
                <dt className="text-[12px] text-[var(--edify-text-muted)]">Status &amp; Source</dt>
                <dd className="font-medium text-[var(--edify-text)]">
                  {STATUS[liveStatus] ?? liveStatus}
                  {liveVersion > 0 ? ` · v${liveVersion}` : ''}
                  {liveAccuracy ? ` · ±${Math.round(liveAccuracy)} m` : ''}
                  {` · ${liveSource}`}
                </dd>
              </div>
              <div>
                <dt className="text-[12px] text-[var(--edify-text-muted)]">Last Verified</dt>
                <dd className="font-medium text-[var(--edify-text)]">
                  {liveVerifiedAt ? `${dayText(liveVerifiedAt)}${liveVerifiedBy ? ` by ${liveVerifiedBy}` : ''}` : 'Not yet verified by device GPS'}
                </dd>
              </div>
              {answer.entrance ? (
                <div>
                  <dt className="text-[12px] text-[var(--edify-text-muted)]">Verified Road Entrance</dt>
                  <dd className="font-medium tabular-nums">
                    {answer.entrance.lat.toFixed(6)}, {answer.entrance.lng.toFixed(6)}
                  </dd>
                </div>
              ) : null}
              <div>
                <dt className="text-[12px] text-[var(--edify-text-muted)]">Nearby Schools</dt>
                <dd className="font-medium">
                  {answer.nearbySchools} school{answer.nearbySchools === 1 ? '' : 's'} within {answer.nearbyRadiusKm} km
                </dd>
              </div>
            </dl>
            )}

            <div className="space-y-2 pt-1">
              {answer.canCapture || answer.canReport ? (
                <button
                  type="button"
                  onClick={() => {
                    setNotice('');
                    setIsCapturing(true);
                  }}
                  data-action="update-gps"
                  className={
                    isRail
                      ? 'flex h-11 w-full items-center justify-center gap-2 rounded-[10px] bg-[var(--brand-primary)] text-[14px] font-bold text-white hover:bg-[var(--brand-primary-hover)]'
                      : 'flex h-11 w-full items-center justify-center gap-2 rounded-[10px] border-2 border-[var(--brand-primary)] bg-white text-[14px] font-bold text-[var(--brand-primary)] hover:bg-blue-50'
                  }
                >
                  <RefreshCw className="h-4 w-4" aria-hidden="true" /> Update GPS Coordinates
                </button>
              ) : null}
              <div className="grid grid-cols-2 gap-2">
                {directions ? (
                  <Link
                    href={directions}
                    className={
                      isRail
                        ? 'inline-flex h-10 items-center justify-center gap-1.5 rounded-[8px] border border-[var(--brand-primary)] px-2 text-[13px] font-semibold text-[var(--brand-primary)] hover:bg-[var(--edify-surface-muted)]'
                        : 'inline-flex h-10 items-center justify-center gap-1.5 rounded-[8px] bg-[var(--brand-primary)] px-3 text-[13px] font-semibold text-white hover:bg-[var(--brand-primary-hover)]'
                    }
                  >
                    <RouteIcon name="navigate" className="h-4 w-4" /> Get Directions
                  </Link>
                ) : null}
                {answer.canPlan ? (
                  <Link
                    href={`/my-plan/smart-route?near=${encodeURIComponent(effectiveSchool.schoolId)}`}
                    className="inline-flex h-10 items-center justify-center gap-1.5 rounded-[8px] border border-[var(--edify-border)] px-3 text-[13px] font-semibold text-[var(--edify-text)] hover:bg-slate-50"
                  >
                    <RouteIcon name="route" className="h-4 w-4" /> Nearby Schools
                  </Link>
                ) : null}
              </div>
            </div>
          </div>
        </div>
      ) : (
        /* STATE A — School WITHOUT Coordinates */
        <div className="mt-3 space-y-3" data-state="gps-missing">
          <p className="text-[14px] text-[var(--edify-text-muted)]">
            No verified GPS location has been recorded for this school.
          </p>
          <div className="flex flex-col items-center justify-center gap-2 rounded-[12px] border border-dashed border-slate-300 bg-slate-50/80 px-4 py-6 text-center">
            <MapPinOff className="h-10 w-10 text-slate-400" aria-hidden="true" />
            <p className="max-w-sm text-[13px] text-slate-600">
              Capture the school&apos;s location while physically at the premises. Directions and road routing activate immediately once saved.
            </p>
          </div>
          {answer.canCapture || answer.canReport ? (
            <button
              type="button"
              onClick={() => {
                setNotice('');
                setIsCapturing(true);
              }}
              data-action="add-gps"
              className="flex h-12 w-full items-center justify-center gap-2 rounded-[12px] bg-[var(--brand-primary)] text-[15px] font-bold text-white shadow-sm hover:bg-[var(--brand-primary-hover)]"
            >
              <LocateFixed className="h-5 w-5" aria-hidden="true" /> Tap to Add GPS Coordinates
            </button>
          ) : null}
        </div>
      )}

      {answer.accessNote ? (
        <p className="mt-3 text-[13px]">
          <span className="text-[var(--edify-text-muted)]">Directions note: </span>
          <span className="font-medium">{answer.accessNote}</span>
        </p>
      ) : null}

      {notice ? (
        <p className="mt-3 rounded-[10px] border border-blue-200 bg-blue-50 px-3.5 py-2.5 text-[13px] font-medium text-[#0b4a9e]" role="status">
          {notice}
        </p>
      ) : null}

      {pending ? (
        <div className="mt-3 space-y-3 rounded-[10px] border border-[var(--brand-primary)]/40 bg-[#f4f8fe] p-3" data-block="location-report">
          <p className="flex items-center gap-2 text-[14px] font-semibold text-[var(--brand-primary-hover)]">
            <RouteIcon name="hourglass" className="h-4 w-4" /> Location update waiting for supervisor review
          </p>
          <ReportDetails report={pending} />
          {answer.canReview ? (
            <Link href="/schools/location-reports" className="text-[13px] font-semibold text-[var(--brand-primary)] hover:underline">
              All location reports
            </Link>
          ) : null}
          {answer.canReview ? (
            <ReviewControls
              report={pending}
              onDecided={(decided) => {
                setPending(undefined);
                setNotice(decided.status === 'approved' ? 'Approved. This is now the verified school location.' : 'Rejected. Stored coordinates remain unchanged.');
                router.refresh();
              }}
            />
          ) : null}
        </div>
      ) : null}

      {/* Secondary Audit History & Issue Report Controls */}
      <div className="mt-3 flex flex-wrap items-center gap-4 border-t border-slate-100 pt-2.5 text-[13px]">
        <button
          type="button"
          aria-expanded={isHistoryOpen}
          className="inline-flex h-9 items-center gap-1.5 font-semibold text-[var(--brand-primary)] hover:underline"
          onClick={() => setIsHistoryOpen((open) => !open)}
        >
          <RouteIcon name="clock" className="h-4 w-4" /> {isHistoryOpen ? 'Hide location history' : 'Location audit history'}
        </button>
        {!pending && answer.canReport && !isReporting ? (
          <button
            type="button"
            className="inline-flex h-9 items-center gap-1.5 font-semibold text-slate-600 hover:text-[var(--brand-primary)]"
            onClick={() => {
              setNotice('');
              setIsReporting(true);
            }}
          >
            <RouteIcon name="alert" className="h-4 w-4" /> Flag coordinate issue
          </button>
        ) : null}
      </div>

      {isReporting ? (
        <ReportForm
          school={effectiveSchool}
          onCancel={() => setIsReporting(false)}
          onFiled={(report) => {
            setIsReporting(false);
            setPending(report);
            setNotice('Location issue flagged for supervisor review.');
          }}
        />
      ) : null}
      {isHistoryOpen ? <LocationHistory schoolId={effectiveSchool.schoolId} /> : null}

      {isCapturing ? (
        <GpsCaptureModal
          schoolId={effectiveSchool.schoolId}
          schoolCode={effectiveSchool.code}
          schoolName={effectiveSchool.name}
          existingPoint={livePoint}
          baseVersion={liveVersion}
          onClose={() => setIsCapturing(false)}
          onSaved={(res) => {
            setIsCapturing(false);
            setNotice(res.message);
            if (res.outcome === 'pending_sync' && res.queued) {
              setOfflineQueued(res.queued);
              return;
            }
            if (res.outcome === 'saved' && res.location?.latitude !== undefined && res.location?.longitude !== undefined) {
              // Automatically transition Add -> Update immediately without full page reload.
              setLivePoint({ lat: res.location.latitude, lng: res.location.longitude });
              setLiveStatus(res.location.location_status || 'verified');
              setLiveVersion(res.location.version);
              setLiveAccuracy(res.location.accuracy_meters ?? null);
              setLiveVerifiedAt(res.location.verified_at || new Date().toISOString());
              setLiveVerifiedBy(res.location.verified_by_name || '');
              setLiveSource('Device GPS (Field)');
              router.refresh();
            } else if (res.outcome === 'pending_review') {
              router.refresh();
            }
          }}
        />
      ) : null}
    </section>
  );
}

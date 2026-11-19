'use client';

/*
 * Verify Location (Smart Route brief, parts 2 and 11): the form that
 * reports a school's location as wrong or missing, the open report as the
 * profile shows it, and a reviewer's Approve / Reject. Nothing changes on
 * the map until someone other than the reporter approves; the School
 * Directory's own coordinates are never changed. The device's location is
 * asked for only when the person presses Use my location.
 */
import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { useRef, useState } from 'react';

import { ReportSchoolLocationResponseSchema, ReviewLocationReportResponseSchema } from '@/gen/edify/routes/v1/routes_pb';
import type { LocationReport, SchoolPin } from '@/gen/edify/routes/v1/routes_pb';
import {
  DECISION_TEXT,
  captureKindText,
  flagsText,
  DEVICE_ACCURACY_MAX_M,
  LOCATE_TIMEOUT_MS,
  kindFor,
  movedText,
  parsePoint,
  pointText,
  reportKey,
  reportedText,
  sourceText,
} from '@/lib/locationReport';
import type { ReportKind, TypedPoint } from '@/lib/locationReport';

import { RouteIcon } from './RouteIcons';

const primary = 'inline-flex h-10 items-center gap-2 rounded-[8px] bg-[var(--brand-primary)] px-4 font-semibold text-white disabled:opacity-60';
const secondary = 'inline-flex h-10 items-center gap-2 rounded-[8px] border border-[var(--brand-primary)] px-4 font-semibold text-[var(--brand-primary)] disabled:opacity-60';
const field = 'mt-1 w-full rounded-[8px] border border-[var(--edify-border)] bg-[var(--edify-card-surface)] px-3 py-2 text-[14px]';

export async function askLocation(op: 'report' | 'list' | 'review' | 'history', request: JsonValue): Promise<JsonValue> {
  const res = await fetch('/route-planner/location', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ op, request }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body?.error === 'string' && body.error.length > 12 ? body.error : 'The report could not be sent. Please try again.');
  return body;
}

interface DeviceFix extends TypedPoint {
  readonly accuracy: number;
}

function locate(): Promise<DeviceFix> {
  return new Promise((resolve, reject) => {
    if (!('geolocation' in navigator)) {
      reject(new Error('This browser cannot give your location. Type the point instead.'));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (p) => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
      (e) =>
        reject(
          new Error(
            e.code === e.PERMISSION_DENIED
              ? 'Location permission was not given. Type the point instead, or allow location for this site.'
              : 'Your location could not be found. Move into the open and try again, or type the point.',
          ),
        ),
      { enableHighAccuracy: true, timeout: LOCATE_TIMEOUT_MS, maximumAge: 0 },
    );
  });
}

interface ReportFormProps {
  readonly school: SchoolPin;
  readonly onFiled: (report: LocationReport) => void;
  readonly onCancel: () => void;
}

/** Report Location: what is wrong, the right point (typed or this device's), directions and a note. */
export function ReportForm({ school, onFiled, onCancel }: ReportFormProps) {
  const [kind, setKind] = useState<ReportKind>(() => kindFor(school.locationStatus));
  const [lat, setLat] = useState('');
  const [lng, setLng] = useState('');
  const [fix, setFix] = useState<DeviceFix | null>(null);
  const [access, setAccess] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [isLocating, setIsLocating] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const key = useRef(reportKey());

  const useDevice = async () => {
    setError('');
    setIsLocating(true);
    try {
      const got = await locate();
      if (got.accuracy > DEVICE_ACCURACY_MAX_M) {
        setError(`Your location is only accurate to ${Math.round(got.accuracy)} m. Move into the open and try again, or type the point.`);
        return;
      }
      setFix(got);
      setLat(got.lat.toFixed(6));
      setLng(got.lng.toFixed(6));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Your location could not be found.');
    } finally {
      setIsLocating(false);
    }
  };

  const send = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    if (!note.trim()) {
      setError('Say what is wrong with the location.');
      return;
    }
    const hasPoint = lat.trim() !== '' || lng.trim() !== '';
    let proposed: TypedPoint | undefined;
    if (hasPoint) {
      const parsed = parsePoint(lat, lng);
      if (typeof parsed === 'string') {
        setError(parsed);
        return;
      }
      proposed = parsed;
    } else if (kind === 'missing') {
      setError("Give the school's location: type it or use your location.");
      return;
    }
    // A device fix counts only while the fields still hold it.
    const device = fix !== null && proposed !== undefined && lat === fix.lat.toFixed(6) && lng === fix.lng.toFixed(6) ? fix : null;
    const point = device ?? proposed;
    setIsSending(true);
    try {
      const answer = await askLocation('report', {
        schoolId: school.schoolId,
        kind,
        ...(point ? { proposed: { lat: point.lat, lng: point.lng } } : {}),
        pointSource: device ? 'device' : point ? 'typed' : 'none',
        accuracyM: device ? device.accuracy : 0,
        accessNote: access,
        note,
        idempotencyKey: key.current,
      });
      const report = fromJson(ReportSchoolLocationResponseSchema, answer).report;
      if (report) onFiled(report);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The report could not be sent. Please try again.');
    } finally {
      setIsSending(false);
    }
  };

  const fromDevice = fix !== null && lat === fix.lat.toFixed(6) && lng === fix.lng.toFixed(6);
  return (
    <form onSubmit={send} className="mt-3 space-y-3 rounded-[10px] border border-[var(--edify-border)] p-3 text-[14px]" aria-label="Report location">
      <fieldset>
        <legend className="font-semibold">What is wrong?</legend>
        <div className="mt-1 flex flex-wrap gap-4">
          {(['wrong', 'missing'] as const).map((k) => (
            <label key={k} className="inline-flex items-center gap-2">
              <input type="radio" name="kind" value={k} checked={kind === k} onChange={() => setKind(k)} />
              {k === 'wrong' ? 'The location is wrong' : 'There is no location'}
            </label>
          ))}
        </div>
      </fieldset>
      <div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-[9rem] flex-1">
            <span className="font-semibold">Latitude</span>
            <input className={field} name="lat" inputMode="decimal" value={lat} onChange={(e) => setLat(e.target.value)} placeholder="0.347600" />
          </label>
          <label className="min-w-[9rem] flex-1">
            <span className="font-semibold">Longitude</span>
            <input className={field} name="lng" inputMode="decimal" value={lng} onChange={(e) => setLng(e.target.value)} placeholder="32.582500" />
          </label>
          <button type="button" className={secondary} onClick={useDevice} disabled={isLocating}>
            <RouteIcon name="locate" className="h-4 w-4" /> {isLocating ? 'Finding you…' : 'Use my location'}
          </button>
        </div>
        <p className="mt-1 text-[13px] text-[var(--edify-text-muted)]">
          {fromDevice
            ? `From this device, accurate to ${Math.round(fix.accuracy)} m. Only use it while you are at the school.`
            : 'Type the point, or press Use my location while you are at the school. Your location is read once and never tracked.'}
        </p>
      </div>
      <label className="block">
        <span className="font-semibold">Directions to the school (optional)</span>
        <input className={field} name="access" value={access} maxLength={300} onChange={(e) => setAccess(e.target.value)} placeholder="Turn left at the trading centre" />
      </label>
      <label className="block">
        <span className="font-semibold">What is wrong with the location?</span>
        <textarea className={`${field} min-h-[80px]`} name="note" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error ? (
        <p className="rounded-[8px] bg-red-50 px-3 py-2 text-red-800" role="alert">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button type="submit" className={primary} disabled={isSending}>
          {isSending ? 'Sending…' : 'Send for review'}
        </button>
        <button type="button" className="h-10 rounded-[8px] px-4 font-semibold text-[var(--edify-text-muted)]" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** What a report says, for the profile and the review queue. */
export function ReportDetails({ report }: { readonly report: LocationReport }) {
  return (
    <dl className="grid gap-x-4 gap-y-2 text-[14px] sm:grid-cols-2">
      <div>
        <dt className="text-[var(--edify-text-muted)]">Reported</dt>
        <dd className="font-medium">
          {captureKindText(report)} · {reportedText(report)}
        </dd>
      </div>
      <div>
        <dt className="text-[var(--edify-text-muted)]">Proposed point</dt>
        <dd className="font-medium tabular-nums">{pointText(report.proposed)}</dd>
      </div>
      <div>
        <dt className="text-[var(--edify-text-muted)]">Source</dt>
        <dd className="font-medium">{sourceText(report)}</dd>
      </div>
      <div>
        <dt className="text-[var(--edify-text-muted)]">Change</dt>
        <dd className="font-medium">{movedText(report)}</dd>
      </div>
      <div className="sm:col-span-2">
        <dt className="text-[var(--edify-text-muted)]">Note</dt>
        <dd className="whitespace-pre-wrap font-medium">{report.note}</dd>
      </div>
      {report.accessNote ? (
        <div className="sm:col-span-2">
          <dt className="text-[var(--edify-text-muted)]">Directions</dt>
          <dd className="font-medium">{report.accessNote}</dd>
        </div>
      ) : null}
      {report.flags.length ? (
        <div className="sm:col-span-2">
          <dt className="text-[var(--edify-text-muted)]">Why it needs review</dt>
          <dd className="font-medium">{flagsText(report.flags)}</dd>
        </div>
      ) : null}
      {report.status !== 'pending' ? (
        <div className="sm:col-span-2">
          <dt className="text-[var(--edify-text-muted)]">{DECISION_TEXT[report.status] ?? report.status}</dt>
          <dd className="font-medium">
            {report.reviewedByName || (report.status === 'accepted' ? 'By the capture policy' : '')}
            {report.reviewNote ? ` · ${report.reviewNote}` : ''}
            {report.resultVersion ? ` · version ${report.resultVersion}` : ''}
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

interface ReviewControlsProps {
  readonly report: LocationReport;
  readonly onDecided: (report: LocationReport) => void;
}

/** Approve (the point becomes the verified location) or Reject with a reason. */
export function ReviewControls({ report, onDecided }: ReviewControlsProps) {
  const [note, setNote] = useState('');
  const [error, setError] = useState('');
  const [isSending, setIsSending] = useState(false);
  if (report.isOwn) {
    return <p className="text-[14px] text-[var(--edify-text-muted)]">You reported this, so someone else reviews it.</p>;
  }
  const decide = async (decision: 'approve' | 'reject') => {
    setError('');
    if (decision === 'reject' && !note.trim()) {
      setError('Say why the report is rejected.');
      return;
    }
    setIsSending(true);
    try {
      const answer = await askLocation('review', { reportId: report.id, decision, note });
      const decided = fromJson(ReviewLocationReportResponseSchema, answer).report;
      if (decided) onDecided(decided);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The review could not be saved. Please try again.');
    } finally {
      setIsSending(false);
    }
  };
  return (
    <div className="space-y-2">
      <label className="block text-[14px]">
        <span className="font-semibold">Review note (needed to reject)</span>
        <input className={field} name="review-note" value={note} maxLength={1000} onChange={(e) => setNote(e.target.value)} />
      </label>
      {error ? (
        <p className="rounded-[8px] bg-red-50 px-3 py-2 text-[14px] text-red-800" role="alert">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap gap-2">
        <button type="button" className={primary} disabled={isSending || !report.proposed} onClick={() => decide('approve')}>
          <RouteIcon name="check" className="h-4 w-4" /> Approve location
        </button>
        <button type="button" className={secondary} disabled={isSending} onClick={() => decide('reject')}>
          Reject
        </button>
      </div>
      {!report.proposed ? <p className="text-[13px] text-[var(--edify-text-muted)]">There is no point to approve; reject it with a note.</p> : null}
    </div>
  );
}

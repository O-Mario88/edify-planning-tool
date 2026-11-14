'use client';

/*
 * A school's location history (offline capture brief, 2026-11-14, part 8):
 * every capture and report, newest first, with its point, accuracy, sender,
 * reason, decision and the version it made. Points at the school only;
 * nothing about anyone's movements.
 */
import { fromJson } from '@bufbuild/protobuf';
import { useEffect, useState } from 'react';

import { GetLocationHistoryResponseSchema } from '@/gen/edify/routes/v1/routes_pb';
import type { LocationReport } from '@/gen/edify/routes/v1/routes_pb';
import { DECISION_TEXT, captureKindText, dayText, flagsText, pointText } from '@/lib/locationReport';

import { askLocation } from './LocationReport';

export function LocationHistory({ schoolId }: { readonly schoolId: string }) {
  const [entries, setEntries] = useState<readonly LocationReport[] | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let isCurrent = true;
    askLocation('history', { schoolId })
      .then((json) => isCurrent && setEntries(fromJson(GetLocationHistoryResponseSchema, json).entries))
      .catch((cause: unknown) => isCurrent && setError(cause instanceof Error ? cause.message : 'The history could not be read.'));
    return () => {
      isCurrent = false;
    };
  }, [schoolId]);

  if (error) return <p className="mt-2 text-[14px] text-red-800">{error}</p>;
  if (!entries) return <p className="mt-2 text-[14px] text-[var(--edify-text-muted)]">Loading the history…</p>;
  if (entries.length === 0) return <p className="mt-2 text-[14px] text-[var(--edify-text-muted)]">No location has been captured or reported for this school yet.</p>;
  return (
    <ol className="mt-2 space-y-2" aria-label="Location history">
      {entries.map((e) => (
        <li key={e.id} className="rounded-[8px] border border-[var(--edify-border)] p-3 text-[14px]">
          <p className="font-semibold">
            {captureKindText(e)}
            {e.resultVersion ? ` → version ${e.resultVersion}` : ''} · {DECISION_TEXT[e.status] ?? e.status}
          </p>
          {e.proposed ? (
            <p className="tabular-nums">
              {pointText(e.proposed)}
              {e.pointSource === 'device' ? ` · GPS ${Math.round(e.accuracyM)} m` : e.pointSource === 'typed' ? ' · typed' : ''}
              {e.previous && e.movedMeters ? ` · moved ${Number(e.movedMeters) < 1000 ? `${e.movedMeters} m` : `${(Number(e.movedMeters) / 1000).toFixed(1)} km`}` : ''}
            </p>
          ) : null}
          <p className="text-[var(--edify-text-muted)]">
            {e.reportedByName || 'Someone'} · {dayText(e.capturedAt || e.reportedAt)}
            {e.reviewedByName ? ` · decided by ${e.reviewedByName}${e.reviewedAt ? ` on ${dayText(e.reviewedAt)}` : ''}` : ''}
          </p>
          {e.note ? <p>{e.note}</p> : null}
          {e.reviewNote ? <p className="text-[var(--edify-text-muted)]">Review: {e.reviewNote}</p> : null}
          {e.flags.length ? <p className="text-[var(--edify-text-muted)]">{flagsText(e.flags)}</p> : null}
        </li>
      ))}
    </ol>
  );
}

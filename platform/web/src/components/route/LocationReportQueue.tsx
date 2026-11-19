'use client';

/*
 * The reviewer's queue of location reports: Pending (oldest first),
 * Approved and Rejected (newest first). A decided report leaves the pending
 * list at once.
 */
import { fromJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import Link from 'next/link';
import { useMemo, useState } from 'react';

import { ListLocationReportsResponseSchema } from '@/gen/edify/routes/v1/routes_pb';

import { ReportDetails, ReviewControls } from './LocationReport';

const TABS = [
  { status: 'pending', label: 'Pending' },
  { status: 'approved', label: 'Approved' },
  { status: 'rejected', label: 'Rejected' },
] as const;

interface QueueProps {
  readonly status: string;
  readonly answer: JsonValue;
}

export function LocationReportQueue({ status, answer: json }: QueueProps) {
  const first = useMemo(() => fromJson(ListLocationReportsResponseSchema, json).reports, [json]);
  const [reports, setReports] = useState(first);
  const [notice, setNotice] = useState('');
  return (
    <>
      <nav className="mt-4 inline-flex overflow-x-auto rounded-[10px] border border-[var(--edify-border)]" aria-label="Report status">
        {TABS.map((t, i) => (
          <Link
            key={t.status}
            href={`/schools/location-reports?status=${t.status}`}
            aria-current={t.status === status ? 'page' : undefined}
            className={`h-8 whitespace-nowrap px-4 text-[14px] font-semibold leading-8 ${i ? 'border-l border-[var(--edify-border)]' : ''} ${
              t.status === status ? 'bg-[var(--brand-primary)] text-white' : 'text-[var(--edify-text)]'
            }`}
          >
            {t.label}
          </Link>
        ))}
      </nav>
      {notice ? (
        <p className="mt-4 rounded-[8px] bg-[#e8f1fd] px-3 py-2 text-[14px] text-[var(--brand-primary-hover)]" role="status">
          {notice}
        </p>
      ) : null}
      {reports.length === 0 ? (
        <p className="mt-6 text-[var(--edify-text-muted)]">
          {status === 'pending' ? 'No location reports are waiting for review.' : `No ${status} location reports.`}
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {reports.map((r) => (
            <li key={r.id} className="card p-4" data-block="location-report">
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <Link href={`/schools/${encodeURIComponent(r.school?.schoolId ?? '')}`} className="text-[16px] font-semibold text-[var(--brand-primary)] hover:underline">
                  {r.school?.name}
                </Link>
                <span className="text-[13px] text-[var(--edify-text-muted)]">
                  School ID {r.school?.code || '—'} · {r.school?.district || 'No district'}
                </span>
              </div>
              <ReportDetails report={r} />
              {r.status === 'pending' ? (
                <div className="mt-3 border-t border-[var(--edify-border)] pt-3">
                  <ReviewControls
                    report={r}
                    onDecided={(decided) => {
                      setReports((list) => list.filter((x) => x.id !== decided.id));
                      setNotice(
                        decided.status === 'approved'
                          ? `${decided.school?.name}: approved. This is now its verified location.`
                          : `${decided.school?.name}: rejected. Its location stays as it was.`,
                      );
                    }}
                  />
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

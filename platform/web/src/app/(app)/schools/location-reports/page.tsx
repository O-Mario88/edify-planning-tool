import { toJson } from '@bufbuild/protobuf';
import type { Metadata } from 'next';

import { LocationReportQueue } from '@/components/route/LocationReportQueue';
import { ListLocationReportsResponseSchema, RoutePlannerService } from '@/gen/edify/routes/v1/routes_pb';
import { asReader } from '@/lib/auth';
import { gatewayClient, isNotFound, isUnavailable, messageOf } from '@/lib/gateway';

export const metadata: Metadata = { title: 'Location Reports - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

const STATUSES = ['pending', 'approved', 'rejected'] as const;

/*
 * Location Reports (Verify Location): the reports on school locations a
 * reviewer may decide, from the gateway's RoutePlannerService (Go). An
 * approved point becomes the school's verified location for the route
 * planner; the School Directory's own coordinates are never changed.
 */
export default async function LocationReportsPage({ searchParams }: { searchParams: Search }) {
  const q = await searchParams;
  const raw = Array.isArray(q.status) ? q.status[0] : q.status;
  const status = STATUSES.find((s) => s === raw) ?? 'pending';
  let refused = '';
  let answer;
  try {
    answer = await asReader((token) => gatewayClient(RoutePlannerService, token).listLocationReports({ status }));
  } catch (error) {
    if (!isNotFound(error) && !isUnavailable(error)) throw error;
    refused = messageOf(error, 'This page is not available to your role.');
  }
  return (
    <div className="mx-auto w-full max-w-[1100px] px-4 pb-10 pt-6 sm:px-6">
      <h1 className="text-[length:var(--edify-text-title-size)] font-bold">Location Reports</h1>
      <p className="mt-1 text-[14px] text-[var(--edify-text-muted)]">
        Corrections to school locations sent from the field. An approved point becomes the school&apos;s verified location for route planning.
      </p>
      {answer ? (
        <LocationReportQueue key={status} status={status} answer={toJson(ListLocationReportsResponseSchema, answer)} />
      ) : (
        <p className="mt-6 text-[var(--edify-text-muted)]">{refused}</p>
      )}
    </div>
  );
}

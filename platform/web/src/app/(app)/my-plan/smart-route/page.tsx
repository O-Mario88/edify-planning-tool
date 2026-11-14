import { toJson } from '@bufbuild/protobuf';
import type { Metadata } from 'next';

import { RoutePlanner } from '@/components/route/RoutePlanner';
import { GetFieldDayResponseSchema, RoutePlannerService } from '@/gen/edify/routes/v1/routes_pb';
import { asReader } from '@/lib/auth';
import { environment } from '@/lib/environment';
import { gatewayClient, isNotFound, messageOf } from '@/lib/gateway';

export const metadata: Metadata = { title: 'Smart Route Planner - Edify Command Center' };

type Search = Promise<Record<string, string | string[] | undefined>>;

const one = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v) ?? '';

/*
 * The Smart Route Planner: the reader's field day, asked of the gateway's
 * RoutePlannerService (Go). The page is drawn on the server; the map and
 * the re-ordering run in the browser.
 */
export default async function SmartRoutePage({ searchParams }: { searchParams: Search }) {
  const q = await searchParams;
  const date = one(q.date);
  const district = one(q.district);
  const cluster = one(q.cluster);
  const near = one(q.near).slice(0, 64);
  let answer;
  let refused = '';
  try {
    answer = await asReader((token) =>
      gatewayClient(RoutePlannerService, token).getFieldDay({ date, districtId: district, clusterId: cluster, nearSchoolId: near }),
    );
  } catch (error) {
    if (!isNotFound(error)) throw error;
    refused = messageOf(error, 'This page is not available to your role.');
  }
  if (!answer) {
    return (
      <div className="mx-auto max-w-[900px] px-6 pt-8">
        <h1 className="text-[length:var(--edify-text-title-size)] font-bold">Smart Route Planner</h1>
        <p className="mt-2 text-[var(--edify-text-muted)]">{refused}</p>
      </div>
    );
  }
  return (
    <RoutePlanner
      key={`${answer.date}|${district}|${cluster}|${near}`}
      day={toJson(GetFieldDayResponseSchema, answer)}
      existingWebUrl={environment().existingWebUrl}
      district={district}
      cluster={cluster}
      near={near}
    />
  );
}

import { fromJson, toJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import {
  GetLocationHistoryRequestSchema,
  GetLocationHistoryResponseSchema,
  ListLocationReportsRequestSchema,
  ListLocationReportsResponseSchema,
  ReportSchoolLocationRequestSchema,
  ReportSchoolLocationResponseSchema,
  ReviewLocationReportRequestSchema,
  ReviewLocationReportResponseSchema,
  RoutePlannerService,
} from '@/gen/edify/routes/v1/routes_pb';
import { gatewayClient, httpStatusOf, isUnauthenticated, messageOf } from '@/lib/gateway';
import { isSameOrigin } from '@/lib/routes';
import { ACCESS_COOKIE } from '@/lib/session';

/**
 * Verify Location from the browser: a report on a school's location, the
 * reviewer's queue and a review, asked of the gateway as the reader. Only
 * Go's field_routes tables change; the School Directory's coordinates never
 * do. Posts from another site are refused.
 */
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return NextResponse.json({ error: 'forbidden' }, { status: 403 });
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: 'signed_out' }, { status: 401 });
  let body: { op?: string; request?: JsonValue };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: 'bad_request' }, { status: 400 });
  }
  const client = gatewayClient(RoutePlannerService, token);
  const headers = { 'Cache-Control': 'no-store' };
  try {
    switch (body.op) {
      case 'report': {
        const answer = await client.reportSchoolLocation(fromJson(ReportSchoolLocationRequestSchema, body.request ?? {}));
        return NextResponse.json(toJson(ReportSchoolLocationResponseSchema, answer), { headers });
      }
      case 'list': {
        const answer = await client.listLocationReports(fromJson(ListLocationReportsRequestSchema, body.request ?? {}));
        return NextResponse.json(toJson(ListLocationReportsResponseSchema, answer), { headers });
      }
      case 'history': {
        const answer = await client.getLocationHistory(fromJson(GetLocationHistoryRequestSchema, body.request ?? {}));
        return NextResponse.json(toJson(GetLocationHistoryResponseSchema, answer), { headers });
      }
      case 'review': {
        const answer = await client.reviewLocationReport(fromJson(ReviewLocationReportRequestSchema, body.request ?? {}));
        return NextResponse.json(toJson(ReviewLocationReportResponseSchema, answer), { headers });
      }
      default:
        return NextResponse.json({ error: 'not_found' }, { status: 404 });
    }
  } catch (error) {
    if (isUnauthenticated(error)) return NextResponse.json({ error: 'signed_out' }, { status: 401 });
    return NextResponse.json({ error: messageOf(error, 'The report could not be sent. Please try again.') }, { status: httpStatusOf(error) });
  }
}


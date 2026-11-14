import { fromJson, toJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import {
  GetSchoolDistanceRequestSchema,
  GetSchoolDistanceResponseSchema,
  GetSchoolPinsRequestSchema,
  GetSchoolPinsResponseSchema,
  PlanRouteRequestSchema,
  PlanRouteResponseSchema,
  RoutePlannerService,
} from '@/gen/edify/routes/v1/routes_pb';
import { gatewayClient, isNotFound, isUnauthenticated, messageOf } from '@/lib/gateway';
import { ACCESS_COOKIE } from '@/lib/session';

/**
 * The Route Planner's reads from the page as it is used (a new order, the
 * schools in view, a pair's distance), asked of the gateway as the reader.
 * Reads only: nothing here schedules or changes a plan.
 */
export async function POST(request: NextRequest) {
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
      case 'plan': {
        const answer = await client.planRoute(fromJson(PlanRouteRequestSchema, body.request ?? {}));
        return NextResponse.json(toJson(PlanRouteResponseSchema, answer), { headers });
      }
      case 'pins': {
        const answer = await client.getSchoolPins(fromJson(GetSchoolPinsRequestSchema, body.request ?? {}));
        return NextResponse.json(toJson(GetSchoolPinsResponseSchema, answer), { headers });
      }
      case 'distance': {
        const answer = await client.getSchoolDistance(fromJson(GetSchoolDistanceRequestSchema, body.request ?? {}));
        return NextResponse.json(toJson(GetSchoolDistanceResponseSchema, answer), { headers });
      }
      default:
        return NextResponse.json({ error: 'not_found' }, { status: 404 });
    }
  } catch (error) {
    if (isUnauthenticated(error)) return NextResponse.json({ error: 'signed_out' }, { status: 401 });
    if (isNotFound(error)) return NextResponse.json({ error: messageOf(error, 'not_found') }, { status: 404 });
    return NextResponse.json({ error: messageOf(error, 'The route could not be worked out.') }, { status: 502 });
  }
}

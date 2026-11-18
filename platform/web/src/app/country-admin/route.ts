import { fromJson, toJson } from '@bufbuild/protobuf';
import type { JsonValue } from '@bufbuild/protobuf';
import { cookies } from 'next/headers';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import {
  AssignCountryRoleRequestSchema,
  AssignCountryRoleResponseSchema,
  CountryService,
  GrantMembershipRequestSchema,
  GrantMembershipResponseSchema,
  ListMembershipsRequestSchema,
  ListMembershipsResponseSchema,
  RecordCountryConfigRequestSchema,
  RecordCountryConfigResponseSchema,
  RevokeCountryRoleRequestSchema,
  RevokeCountryRoleResponseSchema,
  RevokeMembershipRequestSchema,
  RevokeMembershipResponseSchema,
} from '@/gen/edify/countries/v1/countries_pb';
import { gatewayClient, httpStatusOf, isUnauthenticated, messageOf } from '@/lib/gateway';
import { isSameOrigin } from '@/lib/routes';
import { ACCESS_COOKIE } from '@/lib/session';

/**
 * Country administration from the browser (docs/migration/80, §11 and §12):
 * a new settings version, a grant, a revocation, an account's memberships,
 * and the roles an account holds in a country,
 * asked of the gateway's CountryService as the reader. The gateway decides
 * who may (an Admin, never on their own account) and writes only Go's
 * country_registry tables. Posts from another site are refused.
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
  const client = gatewayClient(CountryService, token);
  const headers = { 'Cache-Control': 'no-store' };
  const asked = body.request ?? {};
  try {
    switch (body.op) {
      case 'record': {
        const answer = await client.recordCountryConfig(fromJson(RecordCountryConfigRequestSchema, asked));
        return NextResponse.json(toJson(RecordCountryConfigResponseSchema, answer), { headers });
      }
      case 'memberships': {
        const answer = await client.listMemberships(fromJson(ListMembershipsRequestSchema, asked));
        return NextResponse.json(toJson(ListMembershipsResponseSchema, answer), { headers });
      }
      case 'grant': {
        const answer = await client.grantMembership(fromJson(GrantMembershipRequestSchema, asked));
        return NextResponse.json(toJson(GrantMembershipResponseSchema, answer), { headers });
      }
      case 'revoke': {
        const answer = await client.revokeMembership(fromJson(RevokeMembershipRequestSchema, asked));
        return NextResponse.json(toJson(RevokeMembershipResponseSchema, answer), { headers });
      }
      case 'assignRole': {
        const answer = await client.assignCountryRole(fromJson(AssignCountryRoleRequestSchema, asked));
        return NextResponse.json(toJson(AssignCountryRoleResponseSchema, answer), { headers });
      }
      case 'revokeRole': {
        const answer = await client.revokeCountryRole(fromJson(RevokeCountryRoleRequestSchema, asked));
        return NextResponse.json(toJson(RevokeCountryRoleResponseSchema, answer), { headers });
      }
      default:
        return NextResponse.json({ error: 'not_found' }, { status: 404 });
    }
  } catch (error) {
    if (isUnauthenticated(error)) return NextResponse.json({ error: 'signed_out' }, { status: 401 });
    return NextResponse.json({ error: messageOf(error, 'The change could not be saved. Please try again.') }, { status: httpStatusOf(error) });
  }
}

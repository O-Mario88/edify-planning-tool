/*
 * The country Admin pages' one way to the gateway from the browser: a post
 * to /country-admin (src/app/country-admin/route.ts), which asks
 * CountryService as the reader. A refusal comes back as the gateway's own
 * words, which the page shows.
 */
import type { JsonValue } from '@bufbuild/protobuf';

export type CountryAdminOp = 'record' | 'memberships' | 'grant' | 'revoke' | 'assignRole' | 'revokeRole';

const FALLBACK = 'The change could not be saved. Please try again.';

export async function postCountryAdmin(op: CountryAdminOp, request: JsonValue): Promise<JsonValue> {
  let res: Response;
  try {
    res = await fetch('/country-admin', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ op, request }),
    });
  } catch {
    throw new Error('The platform could not be reached. Check the connection and try again.');
  }
  const body: unknown = await res.json().catch(() => ({}));
  if (res.ok) return body as JsonValue;
  if (res.status === 401) throw new Error('Your session has ended. Reload the page to sign in again.');
  const error = typeof body === 'object' && body !== null && 'error' in body ? (body as { error: unknown }).error : '';
  // The route's own short codes (forbidden, bad_request) are not words for a person.
  throw new Error(typeof error === 'string' && error.includes(' ') ? error : FALLBACK);
}

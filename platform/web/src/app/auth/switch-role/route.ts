import type { NextRequest } from 'next/server';

import { AccountService } from '@/gen/edify/identity/v1/accounts_pb';
import { gatewayClient } from '@/lib/gateway';
import { formFields, isSameOrigin, seeOther, setSession } from '@/lib/routes';
import { ACCESS_COOKIE, safeNext } from '@/lib/session';

/**
 * Work in another role the account holds, as the web's role switcher does.
 * The gateway decides whether the account holds it; its answer is a token in
 * that role.
 */
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return seeOther(request, '/schools');
  const { role = '', next: rawNext } = await formFields(request, ['role', 'next'], 128);
  const next = safeNext(rawNext);
  const token = request.cookies.get(ACCESS_COOKIE)?.value;
  if (!token) return seeOther(request, `/auth/refresh?next=${encodeURIComponent(next)}`);
  try {
    const answer = await gatewayClient(AccountService, token).switchRole({ role });
    const response = seeOther(request, next);
    setSession(response, request, answer.accessToken);
    return response;
  } catch {
    return seeOther(request, next);
  }
}

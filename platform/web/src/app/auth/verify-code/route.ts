import type { NextRequest } from 'next/server';

import { SignInService } from '@/gen/edify/identity/v1/sign_in_pb';
import { gatewayClient } from '@/lib/gateway';
import { formFields, isSameOrigin, seeOther, setSession } from '@/lib/routes';
import { CHALLENGE_COOKIE, safeNext } from '@/lib/session';
import { signInErrorCode } from '@/lib/signInErrors';

/** The code a stopped sign-in waits on. */
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return seeOther(request, '/login?error=forbidden');
  const { code = '', next: rawNext } = await formFields(request, ['code', 'next'], 32);
  const next = safeNext(rawNext);
  const challengeToken = request.cookies.get(CHALLENGE_COOKIE)?.value;
  if (!challengeToken) return seeOther(request, `/login?error=expired&next=${encodeURIComponent(next)}`);
  try {
    const client = gatewayClient(SignInService, undefined, request.headers.get('user-agent') ?? undefined);
    const answer = await client.verifySignInCode({ challengeToken, code: code.replace(/\D/g, '') });
    if (!answer.session?.accessToken) throw new Error('no session');
    const response = seeOther(request, next);
    setSession(response, request, answer.session.accessToken, answer.session.refreshToken);
    return response;
  } catch (error) {
    return seeOther(request, `/login?step=code&error=${signInErrorCode(error, 'code')}&next=${encodeURIComponent(next)}`);
  }
}

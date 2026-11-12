import type { NextRequest } from 'next/server';

import { SignInService } from '@/gen/edify/identity/v1/sign_in_pb';
import { gatewayClient } from '@/lib/gateway';
import { formFields, isSameOrigin, seeOther, setSession } from '@/lib/routes';
import { CHALLENGE_COOKIE, challengeCookie, isSecureOrigin, safeNext } from '@/lib/session';
import { signInErrorCode } from '@/lib/signInErrors';

/** Email and password, through the gateway's SignInService. */
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return seeOther(request, '/login?error=forbidden');
  const { email = '', password = '', next: rawNext } = await formFields(request, ['email', 'password', 'next']);
  const next = safeNext(rawNext);
  const back = (error: string) => seeOther(request, `/login?error=${error}&next=${encodeURIComponent(next)}`);
  if (!email.trim() || !password) return back('credentials');
  try {
    const client = gatewayClient(SignInService, undefined, request.headers.get('user-agent') ?? undefined);
    const answer = await client.signIn({ email: email.trim().toLowerCase(), password });
    const result = answer.result;
    if (result.case === 'codeRequired') {
      const response = seeOther(request, `/login?step=code&next=${encodeURIComponent(next)}`);
      response.cookies.set(CHALLENGE_COOKIE, result.value.challengeToken, challengeCookie(isSecureOrigin(request.nextUrl)));
      return response;
    }
    if (result.case !== 'session' || !result.value.accessToken) return back('unavailable');
    const response = seeOther(request, next);
    setSession(response, request, result.value.accessToken, result.value.refreshToken);
    return response;
  } catch (error) {
    return back(signInErrorCode(error, 'credentials'));
  }
}

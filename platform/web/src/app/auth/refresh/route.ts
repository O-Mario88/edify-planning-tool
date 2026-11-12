import { Code, ConnectError } from '@connectrpc/connect';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

import { SignInService } from '@/gen/edify/identity/v1/sign_in_pb';
import { gatewayClient } from '@/lib/gateway';
import { clearSession, setSession } from '@/lib/routes';
import { REFRESH_COOKIE, safeNext } from '@/lib/session';

/**
 * Renews the access token from the refresh cookie and goes back to the page.
 * Refresh tokens rotate: each is presented once, and the new pair replaces
 * it. Without one, or when the gateway ends the session, the reader signs in.
 */
export async function GET(request: NextRequest) {
  const next = safeNext(request.nextUrl.searchParams.get('next'));
  const signIn = () => {
    const response = NextResponse.redirect(new URL(`/login?next=${encodeURIComponent(next)}`, request.url));
    clearSession(response);
    return response;
  };
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (!refreshToken) return signIn();
  try {
    const answer = await gatewayClient(SignInService).refreshSession({ refreshToken });
    if (!answer.accessToken || !answer.refreshToken) return signIn();
    const response = NextResponse.redirect(new URL(next, request.url));
    setSession(response, request, answer.accessToken, answer.refreshToken);
    return response;
  } catch (error) {
    if (error instanceof ConnectError && error.code === Code.Unauthenticated) return signIn();
    return new NextResponse('Could not reach the server to renew your session. Reload to try again.', { status: 503 });
  }
}

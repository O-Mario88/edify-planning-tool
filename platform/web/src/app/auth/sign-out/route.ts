import type { NextRequest } from 'next/server';

import { SignInService } from '@/gen/edify/identity/v1/sign_in_pb';
import { gatewayClient } from '@/lib/gateway';
import { clearSession, isSameOrigin, seeOther } from '@/lib/routes';
import { REFRESH_COOKIE } from '@/lib/session';

/** Ends the session on the gateway too (best effort) and clears the cookies. */
export async function POST(request: NextRequest) {
  if (!isSameOrigin(request)) return seeOther(request, '/schools');
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (refreshToken) {
    try {
      await gatewayClient(SignInService).signOut({ refreshToken });
    } catch {
      // The tokens still expire on their own schedule.
    }
  }
  const response = seeOther(request, '/login');
  clearSession(response);
  return response;
}

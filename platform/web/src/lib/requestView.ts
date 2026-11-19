/**
 * The reading this request gets (lib/viewport), from its cookie and hints.
 * Server only: it reads the request.
 */
import { cookies, headers } from 'next/headers';

import { VIEW_COOKIE, viewFrom } from './viewport';
import type { View } from './viewport';

export async function requestView(): Promise<View> {
  const [jar, request] = await Promise.all([cookies(), headers()]);
  return viewFrom({
    cookie: jar.get(VIEW_COOKIE)?.value,
    mobileHint: request.get('sec-ch-ua-mobile'),
    userAgent: request.get('user-agent'),
  });
}

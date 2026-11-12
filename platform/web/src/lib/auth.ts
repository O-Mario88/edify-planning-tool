/**
 * The signed-in reader, on the server. A page asks the gateway as the reader;
 * when the gateway no longer accepts the access token the reader is sent to
 * /auth/refresh, which renews it or ends at the sign-in page.
 */
import { cookies, headers } from 'next/headers';
import { redirect } from 'next/navigation';

import { isUnauthenticated } from './gateway';
import { ACCESS_COOKIE, safeNext } from './session';

/** The path being drawn (set by src/proxy.ts). */
export async function currentPath(): Promise<string> {
  return safeNext((await headers()).get('x-edify-path'), '/schools');
}

export async function accessToken(): Promise<string> {
  const token = (await cookies()).get(ACCESS_COOKIE)?.value;
  if (!token) redirect(`/auth/refresh?next=${encodeURIComponent(await currentPath())}`);
  return token;
}

/** Runs a gateway call as the reader; an expired session renews or signs in. */
export async function asReader<T>(call: (token: string) => Promise<T>): Promise<T> {
  const token = await accessToken();
  try {
    return await call(token);
  } catch (error) {
    if (isUnauthenticated(error)) redirect(`/auth/refresh?next=${encodeURIComponent(await currentPath())}`);
    throw error;
  }
}

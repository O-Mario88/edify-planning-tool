/**
 * Sign-in against the EXISTING Edify identity system (POST /api/auth/login).
 *
 * The app and the gateway issue no credentials of their own: passwords, MFA,
 * lockout and refresh rotation stay where they are. This client only carries
 * the person's email and password to that endpoint and returns its tokens.
 */
import type { Tokens } from './tokenStore';

export interface IdentityResponse {
  readonly ok: boolean;
  readonly status: number;
  json(): Promise<unknown>;
}

export type IdentityFetch = (
  url: string,
  init: { method: string; headers: Record<string, string>; body?: string },
) => Promise<IdentityResponse>;

export type SignInFailure = 'rejected' | 'mfa_required' | 'network' | 'unexpected';

export class SignInError extends Error {
  constructor(
    message: string,
    readonly kind: SignInFailure,
  ) {
    super(message);
    this.name = 'SignInError';
  }
}

const MFA_NOT_YET =
  'This account needs a sign-in code, which this app does not support yet. Use the Edify web app.';

function field(body: unknown, name: string): unknown {
  return typeof body === 'object' && body !== null ? (body as Record<string, unknown>)[name] : undefined;
}

export async function signIn(
  identityUrl: string,
  fetchImpl: IdentityFetch,
  email: string,
  password: string,
): Promise<Tokens> {
  let response: IdentityResponse;
  try {
    response = await fetchImpl(`${identityUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase(), password }),
    });
  } catch {
    throw new SignInError('Could not reach the server.', 'network');
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new SignInError('The server sent an unreadable answer.', 'unexpected');
  }

  if (!response.ok) {
    const message = field(body, 'message');
    throw new SignInError(
      typeof message === 'string' && message ? message : 'The email or password is not right.',
      'rejected',
    );
  }
  if (field(body, 'mfaRequired') === true) {
    throw new SignInError(MFA_NOT_YET, 'mfa_required');
  }
  const accessToken = field(body, 'accessToken');
  const refreshToken = field(body, 'refreshToken');
  if (typeof accessToken !== 'string' || typeof refreshToken !== 'string' || !accessToken) {
    throw new SignInError('The server sent no session.', 'unexpected');
  }
  return { accessToken, refreshToken };
}

/**
 * Exchange a refresh token for a new pair (POST /api/auth/refresh). The
 * existing identity system rotates refresh tokens and treats a reused one as
 * theft, so a token is presented exactly once: callers must not run two
 * refreshes at the same time.
 */
export async function refreshTokens(
  identityUrl: string,
  fetchImpl: IdentityFetch,
  refreshToken: string,
): Promise<Tokens | null> {
  let response: IdentityResponse;
  try {
    response = await fetchImpl(`${identityUrl}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refreshToken }),
    });
  } catch {
    throw new SignInError('Could not reach the server.', 'network');
  }
  if (!response.ok) {
    return null;
  }
  const body: unknown = await response.json().catch(() => null);
  const accessToken = field(body, 'accessToken');
  const nextRefreshToken = field(body, 'refreshToken');
  if (typeof accessToken !== 'string' || typeof nextRefreshToken !== 'string' || !accessToken) {
    return null;
  }
  return { accessToken, refreshToken: nextRefreshToken };
}

/**
 * Ask for a password reset link (POST /api/auth/forgot-password), as the web
 * sign-in's "Forgot password?" does. The answer never says whether the
 * address has an account; true means the request was accepted.
 */
export async function requestPasswordReset(identityUrl: string, fetchImpl: IdentityFetch, email: string): Promise<boolean> {
  try {
    const response = await fetchImpl(`${identityUrl}/api/auth/forgot-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: email.trim().toLowerCase() }),
    });
    return response.ok;
  } catch {
    return false;
  }
}

/**
 * End the session on the server too (POST /api/auth/logout), so the refresh
 * token cannot be used again. Best effort: signing out never waits on it.
 */
export async function revokeSession(identityUrl: string, fetchImpl: IdentityFetch, refreshToken: string): Promise<void> {
  try {
    await fetchImpl(`${identityUrl}/api/auth/logout`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refreshToken }),
    });
  } catch {
    // Offline: the token still expires on its own schedule.
  }
}

export interface SignInFigureValues {
  readonly portfolio: string;
  readonly schoolsReached: string;
  readonly schoolsVisited: string;
  readonly schoolsTrained: string;
  readonly ssaCompleted: string;
}

const FIGURE_KEYS = ['portfolio', 'schoolsReached', 'schoolsVisited', 'schoolsTrained', 'ssaCompleted'] as const;

/** The four figures the web sign-in shows (GET /api/auth/sign-in-figures); null if unreadable. */
export async function signInFigures(identityUrl: string, fetchImpl: IdentityFetch): Promise<SignInFigureValues | null> {
  try {
    const response = await fetchImpl(`${identityUrl}/api/auth/sign-in-figures`, { method: 'GET', headers: { Accept: 'application/json' } });
    if (!response.ok) {
      return null;
    }
    const body = await response.json();
    const values = FIGURE_KEYS.map((key) => field(body, key));
    if (!values.every((value): value is string => typeof value === 'string')) {
      return null;
    }
    const [portfolio, schoolsReached, schoolsVisited, schoolsTrained, ssaCompleted] = values;
    return { portfolio, schoolsReached, schoolsVisited, schoolsTrained, ssaCompleted };
  } catch {
    return null;
  }
}

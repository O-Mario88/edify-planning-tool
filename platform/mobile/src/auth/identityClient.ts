/**
 * Signing in, through the Go gateway's SignInService (owner brief,
 * 2026-11-11: "All authentication and user workflows must be handled by
 * Go"). The gateway checks the password, applies the lockout, asks for the
 * second factor when the account needs one and issues the session; the app
 * only carries what the person typed and keeps the tokens it is given.
 *
 * These calls carry no access token: they are how one is obtained.
 */
import { ApiError, callUnary } from '../api/connect';
import type { ConnectTransport, FetchLike } from '../api/connect';
import { SignInService } from '../gen/edify/identity/v1/sign_in_pb';
import type { SessionGranted } from '../gen/edify/identity/v1/sign_in_pb';
import type { Tokens } from './tokenStore';

export type SignInFailure = 'rejected' | 'rate_limited' | 'network' | 'unexpected';

export class SignInError extends Error {
  constructor(
    message: string,
    readonly kind: SignInFailure,
  ) {
    super(message);
    this.name = 'SignInError';
  }
}

/** A sign-in stopped for its code: where it went, and how to answer it. */
export interface CodeChallenge {
  readonly token: string;
  /** "email", "sms" or "app". */
  readonly channel: string;
  /** Where the code went, masked ("p•••••@edify.org"). */
  readonly hint: string;
  readonly expiresInSeconds: number;
}

export type SignInResult =
  | { readonly kind: 'session'; readonly tokens: Tokens }
  | { readonly kind: 'code'; readonly challenge: CodeChallenge };

/**
 * The gateway, without a session: sign-in calls never send a token. A native
 * build says whether it is a phone or a tablet, for the Staff Activity Log's
 * sign-in record: its HTTP library names itself, not the device.
 */
export function publicTransport(gatewayUrl: string, fetchImpl: FetchLike, device: AppDevice | null = null): ConnectTransport {
  return {
    baseUrl: gatewayUrl,
    fetch: fetchImpl,
    getAccessToken: async () => null,
    headers: device ? { 'X-Edify-Device': device } : undefined,
  };
}

export type AppDevice = 'mobile' | 'tablet';

/** A tablet by the existing rule's spirit: an iPad, or a screen 600 points across at its narrowest. */
export function appDevice(os: string, isPad: boolean, width: number, height: number): AppDevice | null {
  if (os === 'web') {
    return null;
  }
  return isPad || Math.min(width, height) >= TABLET_MIN_SIDE ? 'tablet' : 'mobile';
}

const TABLET_MIN_SIDE = 600;

function failure(error: unknown, fallback: string): SignInError {
  if (!(error instanceof ApiError)) {
    return new SignInError(fallback, 'unexpected');
  }
  switch (error.code) {
    case 'network':
    case 'timeout':
      return new SignInError('Could not reach the server.', 'network');
    case 'unauthenticated':
    case 'invalid_argument':
      return new SignInError(error.message || fallback, 'rejected');
    case 'resource_exhausted':
      return new SignInError(error.message || 'Too many attempts. Wait a minute and try again.', 'rate_limited');
  }
  return new SignInError(error.message || fallback, 'unexpected');
}

function tokensOf(session: SessionGranted | undefined): Tokens {
  if (!session?.accessToken || !session.refreshToken) {
    throw new SignInError('The server sent no session.', 'unexpected');
  }
  return { accessToken: session.accessToken, refreshToken: session.refreshToken };
}

/** Email and password: a session, or the code the account needs first. */
export async function signIn(transport: ConnectTransport, email: string, password: string): Promise<SignInResult> {
  let answer;
  try {
    answer = await callUnary(transport, SignInService.method.signIn, {
      email: email.trim().toLowerCase(),
      password,
    });
  } catch (error) {
    throw failure(error, 'The email or password is not right.');
  }
  const result = answer.result;
  if (result.case === 'codeRequired') {
    const { challengeToken, channel, destinationHint, expiresInSeconds } = result.value;
    if (!challengeToken) {
      throw new SignInError('The server sent no sign-in code.', 'unexpected');
    }
    return { kind: 'code', challenge: { token: challengeToken, channel, hint: destinationHint, expiresInSeconds } };
  }
  return { kind: 'session', tokens: tokensOf(result.case === 'session' ? result.value : undefined) };
}

/** The code a stopped sign-in waits on. */
export async function verifySignInCode(transport: ConnectTransport, challenge: CodeChallenge, code: string): Promise<Tokens> {
  let answer;
  try {
    answer = await callUnary(transport, SignInService.method.verifySignInCode, {
      challengeToken: challenge.token,
      code: code.replace(/\D/g, ''),
    });
  } catch (error) {
    throw failure(error, 'That code is not right, or it has expired.');
  }
  return tokensOf(answer.session);
}

/**
 * Exchange a refresh token for a new pair. Refresh tokens rotate and a reused
 * one ends the session, so a token is presented exactly once: callers must not
 * run two refreshes at the same time. Null means the session is over; an
 * unreachable server throws, and the session is kept.
 */
export async function refreshTokens(transport: ConnectTransport, refreshToken: string): Promise<Tokens | null> {
  try {
    const answer = await callUnary(transport, SignInService.method.refreshSession, { refreshToken });
    if (!answer.accessToken || !answer.refreshToken) {
      return null;
    }
    return { accessToken: answer.accessToken, refreshToken: answer.refreshToken };
  } catch (error) {
    if (error instanceof ApiError && error.code === 'unauthenticated') {
      return null;
    }
    throw failure(error, 'The session could not be renewed.');
  }
}

/**
 * Ask for a password reset link, as the web sign-in's "Forgot password?"
 * does. The answer never says whether the address has an account; true means
 * the request was accepted.
 */
export async function requestPasswordReset(transport: ConnectTransport, email: string): Promise<boolean> {
  try {
    await callUnary(transport, SignInService.method.requestPasswordReset, { email: email.trim().toLowerCase() });
    return true;
  } catch {
    return false;
  }
}

/** End the session on the server too. Best effort: signing out never waits on it. */
export async function revokeSession(transport: ConnectTransport, refreshToken: string): Promise<void> {
  try {
    await callUnary(transport, SignInService.method.signOut, { refreshToken });
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

/** The four figures the web sign-in shows; null if they cannot be read. */
export async function signInFigures(transport: ConnectTransport): Promise<SignInFigureValues | null> {
  try {
    const answer = await callUnary(transport, SignInService.method.getSignInFigures, {});
    const values = [answer.portfolio, answer.schoolsReached, answer.schoolsVisited, answer.schoolsTrained, answer.ssaCompleted];
    if (values.some((value) => !value)) {
      return null;
    }
    const [portfolio, schoolsReached, schoolsVisited, schoolsTrained, ssaCompleted] = values;
    return { portfolio, schoolsReached, schoolsVisited, schoolsTrained, ssaCompleted };
  } catch {
    return null;
  }
}

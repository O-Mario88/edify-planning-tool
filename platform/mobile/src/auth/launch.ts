/**
 * What the app opens at launch when it holds a saved sign-in (owner brief,
 * 2026-11-11: a returning user with a valid session goes straight to their
 * home; an expired one signs in again; startup never bypasses sign-in). The
 * session is always confirmed with the server first, so no one is shown a
 * workspace their sign-in no longer allows.
 */
import { ApiError } from '../api/connect';

export type SessionState =
  | { status: 'loading' }
  | { status: 'signedOut'; notice: string }
  /** A saved sign-in the server could not be asked about: offline, or down. */
  | { status: 'unreachable'; notice: string }
  | { status: 'signedIn'; session: import('../gen/edify/identity/v1/identity_pb').Session };

/** Sign in's notice when the phone's keystore could not be read at launch. */
export const KEYSTORE_UNREADABLE = 'This phone’s secure storage could not be read. Please sign in.';

/** A start slower than this shows "Loading Edify…" under the logo. */
export const LOADING_HINT_AFTER_MS = 700;

const NO_ANSWER = new Set(['network', 'timeout', 'unavailable', 'internal']);

/** The state after the saved sign-in could not be confirmed, and whether to forget it. */
export function afterFailedCheck(error: unknown): { readonly state: SessionState; readonly shouldClear: boolean } {
  const code = error instanceof ApiError ? error.code : '';
  if (code === 'unauthenticated') {
    return { state: { status: 'signedOut', notice: 'Your session has expired. Please sign in again.' }, shouldClear: true };
  }
  if (NO_ANSWER.has(code) || code.startsWith('http_5')) {
    return {
      state: {
        status: 'unreachable',
        notice: code === 'network' || code === 'timeout' ? 'Edify could not be reached. Check your connection and try again.' : 'Edify is not answering right now. Please try again shortly.',
      },
      shouldClear: false,
    };
  }
  return { state: { status: 'signedOut', notice: error instanceof Error ? error.message : 'Something went wrong.' }, shouldClear: false };
}

import { ApiError } from '../api/connect';
import { afterFailedCheck, LOADING_HINT_AFTER_MS } from '../auth/launch';

describe('what the app opens when the saved sign-in cannot be confirmed', () => {
  test('an expired or revoked sign-in goes to Sign in, and the saved one is cleared', () => {
    const next = afterFailedCheck(new ApiError('Signed out', 'unauthenticated', '', ''));
    expect(next).toEqual({ state: { status: 'signedOut', notice: 'Your session has expired. Please sign in again.' }, shouldClear: true });
  });

  test('no connection keeps the sign-in and offers to try again, never Sign in', () => {
    for (const code of ['network', 'timeout', 'unavailable', 'internal', 'http_502']) {
      const next = afterFailedCheck(new ApiError('Could not reach the server.', code, '', ''));
      expect(next.state.status).toBe('unreachable');
      expect(next.shouldClear).toBe(false);
    }
  });

  test('any other refusal is shown on Sign in, keeping the saved sign-in', () => {
    const next = afterFailedCheck(new ApiError('Your account is suspended.', 'permission_denied', '', ''));
    expect(next).toEqual({ state: { status: 'signedOut', notice: 'Your account is suspended.' }, shouldClear: false });
  });

  test('a quick start shows no loading words; a slow one says so', () => {
    expect(LOADING_HINT_AFTER_MS).toBeGreaterThanOrEqual(500);
    expect(LOADING_HINT_AFTER_MS).toBeLessThanOrEqual(1000);
  });
});

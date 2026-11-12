/**
 * Why a sign-in failed, as a fixed code the sign-in page words. The page
 * never echoes text from the address bar.
 */
import { Code, ConnectError } from '@connectrpc/connect';

export const SIGN_IN_MESSAGES = {
  credentials: 'The email or password is not right.',
  code: 'That code is not right, or it has expired.',
  throttled: 'Too many attempts. Wait a minute, then try again.',
  locked: 'This account is locked. Ask your administrator to unlock it.',
  unavailable: 'Could not reach the server. Try again shortly.',
  expired: 'Your session has ended. Sign in again.',
  forbidden: 'This request did not come from the sign-in page.',
} as const;

export type SignInErrorCode = keyof typeof SIGN_IN_MESSAGES;

export function signInErrorCode(error: unknown, wrong: 'credentials' | 'code'): SignInErrorCode {
  if (!(error instanceof ConnectError)) return 'unavailable';
  switch (error.code) {
    case Code.Unauthenticated:
    case Code.InvalidArgument:
    case Code.NotFound:
      return wrong;
    case Code.ResourceExhausted:
      return 'throttled';
    case Code.PermissionDenied:
    case Code.FailedPrecondition:
      return 'locked';
    default:
      return 'unavailable';
  }
}

export function signInMessage(code: string | undefined): string {
  return code && code in SIGN_IN_MESSAGES ? SIGN_IN_MESSAGES[code as SignInErrorCode] : '';
}

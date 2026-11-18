/**
 * The Go gateway, called from the Next.js server only. Requests and answers
 * are the generated contracts (src/gen); the transport is Connect over fetch.
 */
import { Code, ConnectError, createClient } from '@connectrpc/connect';
import type { Client, Interceptor } from '@connectrpc/connect';
import { createConnectTransport } from '@connectrpc/connect-web';
import type { DescService } from '@bufbuild/protobuf';

import { environment } from './environment';

const TIMEOUT_MS = 20_000;

function bearer(token: string | undefined): Interceptor {
  return (next) => async (request) => {
    if (token) request.header.set('Authorization', `Bearer ${token}`);
    return next(request);
  };
}

/** A client for one gateway service, as the caller (or anonymously). */
export function gatewayClient<T extends DescService>(service: T, token?: string, userAgent?: string): Client<T> {
  const transport = createConnectTransport({
    baseUrl: environment().gatewayUrl,
    useBinaryFormat: false,
    defaultTimeoutMs: TIMEOUT_MS,
    interceptors: [bearer(token)],
    fetch: (input, init) => {
      const headers = new Headers(init?.headers);
      if (userAgent) headers.set('User-Agent', userAgent);
      return fetch(input, { ...init, headers, cache: 'no-store' });
    },
  });
  return createClient(service, transport);
}

/** The gateway no longer accepts the access token: renew or sign in again. */
export function isUnauthenticated(error: unknown): boolean {
  return error instanceof ConnectError && error.code === Code.Unauthenticated;
}

/** The page refused the reader (the gateway's 404). */
export function isNotFound(error: unknown): boolean {
  return error instanceof ConnectError && (error.code === Code.NotFound || error.code === Code.PermissionDenied);
}

/**
 * The gateway has no answer for this page yet (Go does not serve it and no
 * existing application stands behind the gateway).
 */
export function isUnavailable(error: unknown): boolean {
  return error instanceof ConnectError && error.code === Code.Unavailable;
}

/** The gateway's message for a person, never a stack or a code. */
export function messageOf(error: unknown, fallback: string): string {
  if (error instanceof ConnectError && error.rawMessage) return error.rawMessage;
  return fallback;
}

/** The HTTP status a browser route answers a gateway refusal with. */
export function httpStatusOf(error: unknown): number {
  if (!(error instanceof ConnectError)) return 502;
  switch (error.code) {
    case Code.InvalidArgument:
    case Code.FailedPrecondition:
      return 400;
    case Code.AlreadyExists:
      return 409;
    case Code.NotFound:
      return 404;
    case Code.PermissionDenied:
      return 403;
    default:
      return 502;
  }
}

/**
 * A small typed client for unary Connect calls (JSON over HTTPS POST).
 *
 * Requests and responses are built and parsed with the message schemas
 * generated from platform/proto, so the wire shape is the contract's and never
 * hand-written here. Plain `fetch` is all it needs, which is what React Native
 * provides on both platforms.
 */
import { create, fromBinary, fromJson, toJson } from '@bufbuild/protobuf';
import type { DescMessage, JsonValue, MessageInitShape, MessageShape } from '@bufbuild/protobuf';
import { base64Decode } from '@bufbuild/protobuf/wire';

import { ErrorDetailSchema } from '../gen/edify/common/v1/common_pb';

export interface FetchResponse {
  readonly ok: boolean;
  readonly status: number;
  json(): Promise<unknown>;
  readonly headers: { get(name: string): string | null };
}

export type FetchLike = (
  url: string,
  init: { method: string; headers: Record<string, string>; body: string; signal?: AbortSignal },
) => Promise<FetchResponse>;

export interface ConnectTransport {
  readonly baseUrl: string;
  readonly fetch: FetchLike;
  /** The current access token, or null when signed out. */
  readonly getAccessToken: () => Promise<string | null>;
  readonly timeoutMs?: number;
  /**
   * Called when the gateway says the access token is no longer good. Resolves
   * true when a fresh one is in place and the call should be tried once more.
   */
  readonly refresh?: () => Promise<boolean>;
}

export interface UnaryMethod<I extends DescMessage, O extends DescMessage> {
  readonly name: string;
  readonly input: I;
  readonly output: O;
  readonly parent: { readonly typeName: string };
}

const DEFAULT_TIMEOUT_MS = 20_000;
const ERROR_DETAIL_TYPE = 'edify.common.v1.ErrorDetail';

/** A failed call, with the gateway's stable reason code when it sent one. */
export class ApiError extends Error {
  constructor(
    message: string,
    /** Connect code, e.g. "unauthenticated", or "network" / "timeout". */
    readonly code: string,
    /** Stable reason from edify.common.v1.ErrorDetail, e.g. "AUTH_TOKEN_EXPIRED". */
    readonly reason: string,
    /** The request id support can search the gateway logs for. */
    readonly requestId: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

interface ConnectErrorBody {
  code?: unknown;
  message?: unknown;
  details?: unknown;
}

function readErrorDetail(body: ConnectErrorBody): { reason: string; requestId: string } {
  const details = Array.isArray(body.details) ? body.details : [];
  for (const detail of details) {
    if (typeof detail !== 'object' || detail === null) {
      continue;
    }
    const { type, value } = detail as { type?: unknown; value?: unknown };
    if (type !== ERROR_DETAIL_TYPE || typeof value !== 'string') {
      continue;
    }
    try {
      const parsed = fromBinary(ErrorDetailSchema, base64Decode(value));
      return { reason: parsed.code, requestId: parsed.requestId };
    } catch {
      // An unreadable detail must not hide the error it came with.
    }
  }
  return { reason: '', requestId: '' };
}

async function toApiError(response: FetchResponse): Promise<ApiError> {
  let body: ConnectErrorBody = {};
  try {
    const parsed = await response.json();
    if (typeof parsed === 'object' && parsed !== null) {
      body = parsed as ConnectErrorBody;
    }
  } catch {
    // A non-JSON error body (a proxy's HTML page, say) is reported by status.
  }
  const detail = readErrorDetail(body);
  return new ApiError(
    typeof body.message === 'string' ? body.message : `The request failed (HTTP ${response.status}).`,
    typeof body.code === 'string' ? body.code : `http_${response.status}`,
    detail.reason,
    detail.requestId || response.headers.get('X-Request-Id') || '',
  );
}

async function sendUnary<I extends DescMessage, O extends DescMessage>(
  transport: ConnectTransport,
  method: UnaryMethod<I, O>,
  request: MessageInitShape<I>,
): Promise<MessageShape<O>> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Connect-Protocol-Version': '1',
  };
  const token = await transport.getAccessToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), transport.timeoutMs ?? DEFAULT_TIMEOUT_MS);
  let response: FetchResponse;
  try {
    response = await transport.fetch(`${transport.baseUrl}/${method.parent.typeName}/${method.name}`, {
      method: 'POST',
      headers,
      body: JSON.stringify(toJson(method.input, create(method.input, request))),
      signal: controller.signal,
    });
  } catch {
    const timedOut = controller.signal.aborted;
    throw new ApiError(
      timedOut ? 'The server took too long to answer.' : 'Could not reach the server.',
      timedOut ? 'timeout' : 'network',
      '',
      '',
    );
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    throw await toApiError(response);
  }
  const body = (await response.json()) as JsonValue;
  // A newer gateway may send fields this build does not know yet.
  return fromJson(method.output, body, { ignoreUnknownFields: true });
}

/**
 * Make one unary call. Access tokens are short-lived by design, so a call
 * refused as unauthenticated is retried once after the session is refreshed.
 */
export async function callUnary<I extends DescMessage, O extends DescMessage>(
  transport: ConnectTransport,
  method: UnaryMethod<I, O>,
  request: MessageInitShape<I>,
): Promise<MessageShape<O>> {
  try {
    return await sendUnary(transport, method, request);
  } catch (error) {
    const isExpired = error instanceof ApiError && error.code === 'unauthenticated';
    if (isExpired && transport.refresh && (await transport.refresh())) {
      return sendUnary(transport, method, request);
    }
    throw error;
  }
}

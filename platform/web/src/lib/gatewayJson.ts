/**
 * Server-only JSON fetch helper for native Go gateway REST endpoints
 * (/api/v1/support/*, /api/v1/messages/*, /api/v1/notifications/preferences,
 * /api/v1/bulk/activities/*). Zero Django dependency.
 */
import { environment } from './environment';

export class GatewayHttpError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function gatewayJson<T>(
  path: string,
  token: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const url = `${environment().gatewayUrl}${path}`;
  const response = await fetch(url, {
    method: init.method ?? 'GET',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
    },
    body: init.body !== undefined ? JSON.stringify(init.body) : undefined,
    cache: 'no-store',
  });
  const text = await response.text();
  let parsed: Record<string, unknown> = {};
  if (text) {
    try {
      parsed = JSON.parse(text) as Record<string, unknown>;
    } catch {
      parsed = {};
    }
  }
  if (!response.ok) {
    const msg = typeof parsed.error === 'string' && parsed.error ? parsed.error : `Request failed (${response.status}).`;
    throw new GatewayHttpError(response.status, msg);
  }
  return parsed as T;
}

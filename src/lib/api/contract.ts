// Data-contract enforcement for backend/live surfaces.
//
// The golden rule: a fetcher may only return `live: true` when the payload is
// FULLY valid against its schema. This module is the single place that:
//   1. validates a raw backend payload against a Zod schema (pure, testable),
//   2. normalizes it (schemas default missing arrays to []), and
//   3. records a structured contract violation (logged + surfaced in System
//      Health) when the payload is off-spec — so the failure is visible, not
//      hidden behind optional chaining or a generic error boundary.
//
// Not `server-only`: the validator + registry are plain in-process logic so
// unit tests can import them directly. Tokens/secrets never pass through here.

import type { ZodType } from "zod";
import { log } from "@/lib/log";

export type ContractErrorType = "DATA_CONTRACT_VIOLATION" | "FETCH_FAILED";

export type ContractViolation = {
  errorType: ContractErrorType;
  severity: "warn" | "error";
  /** Backend path the data came from, e.g. "/leadership/decision-engine". */
  endpoint: string;
  /** App route/page that consumed it, when known. */
  route?: string;
  /** Component/section that rendered it, when known. */
  component?: string;
  /** Active user role, when known (never PII). */
  role?: string;
  /** Correlation id, when available. */
  requestId?: string;
  /** Dotted path of the first invalid field, e.g. "boards.0.insights". */
  missingFieldPath?: string;
  expectedType?: string;
  receivedType?: string;
  /** Human message (first issue). */
  message: string;
  /** Compact sample of the validation error (no raw payload values). */
  sampleError?: string;
  firstSeen: string;
  lastSeen: string;
  count: number;
};

export type ValidationContext = {
  endpoint: string;
  route?: string;
  component?: string;
  role?: string;
  requestId?: string;
};

export type ContractResult<T> =
  | { ok: true; data: T }
  | { ok: false; violation: ContractViolation };

// ── In-process violation registry ───────────────────────────────────
// Bounded, deduplicated by endpoint+field path so a hot SSR loop can't flood
// memory. System Health reads this; tests clear it. This is intentionally
// process-local (best-effort visibility), not a durable store.

const MAX_VIOLATIONS = 200;
const registry = new Map<string, ContractViolation>();

function keyFor(v: Pick<ContractViolation, "endpoint" | "missingFieldPath" | "errorType">): string {
  return `${v.errorType}::${v.endpoint}::${v.missingFieldPath ?? "-"}`;
}

export function recordContractViolation(
  v: Omit<ContractViolation, "firstSeen" | "lastSeen" | "count">,
): ContractViolation {
  const now = new Date().toISOString();
  const k = keyFor(v);
  const existing = registry.get(k);
  const entry: ContractViolation = existing
    ? { ...existing, ...v, firstSeen: existing.firstSeen, lastSeen: now, count: existing.count + 1 }
    : { ...v, firstSeen: now, lastSeen: now, count: 1 };
  registry.set(k, entry);

  // Evict oldest if over cap (insertion order is preserved by Map).
  if (registry.size > MAX_VIOLATIONS) {
    const oldest = registry.keys().next().value;
    if (oldest !== undefined) registry.delete(oldest);
  }

  // Structured log — exact field path, expected vs received type, no payload values.
  log[v.severity === "error" ? "error" : "warn"]("data.contract.violation", {
    errorType: v.errorType,
    endpoint: v.endpoint,
    route: v.route,
    component: v.component,
    role: v.role,
    requestId: v.requestId,
    missingFieldPath: v.missingFieldPath,
    expectedType: v.expectedType,
    receivedType: v.receivedType,
    message: v.message,
  });

  return entry;
}

export function getContractViolations(): ContractViolation[] {
  // Newest first.
  return [...registry.values()].sort((a, b) => (a.lastSeen < b.lastSeen ? 1 : -1));
}

export function clearContractViolations(): void {
  registry.clear();
}

// ── Pure validator ──────────────────────────────────────────────────
// Validates + normalizes raw data against a schema. On failure it builds a
// structured violation (and records it). Pure enough to unit test: pass a
// schema + raw value and assert on the result.

function describeType(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value)) return "array";
  return typeof value;
}

export function validateContract<T>(
  schema: ZodType<T>,
  raw: unknown,
  ctx: ValidationContext,
): ContractResult<T> {
  const parsed = schema.safeParse(raw);
  if (parsed.success) {
    return { ok: true, data: parsed.data };
  }

  const issue = parsed.error.issues[0];
  const missingFieldPath = issue?.path?.map((p) => String(p)).join(".") || undefined;
  // zod invalid_type issues carry `expected`; derive `received` from the raw value at the path.
  const expectedType =
    issue && "expected" in issue ? String((issue as { expected?: unknown }).expected) : undefined;
  const receivedType = (() => {
    if (!issue?.path?.length) return describeType(raw);
    let cur: unknown = raw;
    for (const seg of issue.path) {
      if (cur == null || typeof cur !== "object") return describeType(cur);
      cur = (cur as Record<string | number, unknown>)[seg as string | number];
    }
    return describeType(cur);
  })();

  const violation = recordContractViolation({
    errorType: "DATA_CONTRACT_VIOLATION",
    severity: "error",
    endpoint: ctx.endpoint,
    route: ctx.route,
    component: ctx.component,
    role: ctx.role,
    requestId: ctx.requestId,
    missingFieldPath,
    expectedType,
    receivedType,
    message: issue ? `${missingFieldPath ?? "(root)"}: ${issue.message}` : "schema validation failed",
    sampleError: parsed.error.issues
      .slice(0, 3)
      .map((i) => `${i.path.map(String).join(".") || "(root)"}: ${i.message}`)
      .join(" | "),
  });

  return { ok: false, violation };
}

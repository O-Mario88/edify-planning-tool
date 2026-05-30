// Client-side wrappers around the fund-request workflow mutators.
//
// These are thin pass-throughs that exist so client components can import
// a single, stable surface. In production these would be replaced with
// real server actions (`"use server"`); for the demo they delegate to the
// in-memory mutator in `workflow-mock.ts`.

import {
  transitionFundRequest,
  fundRequestTotal,
  formatUgx,
  type FundRequest,
} from "@/lib/workflow-mock";

export type FundRequestActionResult =
  | { ok: true; request: FundRequest }
  | { ok: false; reason: "NOT_FOUND" | "WRONG_STATUS" };

export function approveFundRequest(id: string): FundRequestActionResult {
  const next = transitionFundRequest(id, "approve");
  if (!next) return { ok: false, reason: "WRONG_STATUS" };
  return { ok: true, request: next };
}

export function returnFundRequest(id: string, note?: string): FundRequestActionResult {
  const next = transitionFundRequest(id, "return", note);
  if (!next) return { ok: false, reason: "WRONG_STATUS" };
  return { ok: true, request: next };
}

export function markFundRequestDisbursed(id: string): FundRequestActionResult {
  const next = transitionFundRequest(id, "disburse");
  if (!next) return { ok: false, reason: "WRONG_STATUS" };
  return { ok: true, request: next };
}

// Convenience for toast messages so all callers share copy.
export function fundRequestSummary(fr: FundRequest): string {
  return `${fr.staff} · ${fr.district} · ${formatUgx(fundRequestTotal(fr))}`;
}

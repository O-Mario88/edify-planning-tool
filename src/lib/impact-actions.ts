// Impact Assessment verification action. Moves an activity from
// "Submitted for Verification" → "Verified". Only Impact Assessment
// or Admin may verify. Currently mutates the cceo-execution-store
// localStorage record so the change is visible within the session.
//
// Real backend would call a Salesforce verification API.
//
// This module is intentionally framework-agnostic — no React, no
// Next.js. It can be imported from client components (the body checks
// `typeof window` before touching localStorage).

export type VerifyResult =
  | { ok: true; activityId: string }
  | { ok: false; reason: "FORBIDDEN" | "WRONG_STATUS" | "NOT_FOUND" };

type StoredCompletion = {
  schoolId?:        string;
  activityId:       string;
  completedAt?:     string;
  salesforceId?:    string;
  salesforceIdKind?:string;
  note?:            string;
  verified?:        boolean;
  verifiedAt?:      string;
  verifiedBy?:      string;
};

const STORAGE_KEY = "cceo.visitCompletions";
const ALLOWED_ROLES = ["ImpactAssessment", "Admin"];

export function verifyActivity(args: {
  activityId: string;
  actor: { role: string; staffId: string };
}): VerifyResult {
  if (!ALLOWED_ROLES.includes(args.actor.role)) {
    return { ok: false, reason: "FORBIDDEN" };
  }
  // The record lives in browser localStorage (the CCEO execution store).
  // On the server there's nothing to read — return NOT_FOUND so callers
  // can fall back appropriately.
  if (typeof window === "undefined") {
    return { ok: false, reason: "NOT_FOUND" };
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ok: false, reason: "NOT_FOUND" };
    const parsed = JSON.parse(raw) as Record<string, StoredCompletion> | StoredCompletion[];

    // The store writes a Record<activityId, VisitCompletion>; tolerate
    // either shape for forward-compat.
    if (Array.isArray(parsed)) {
      const idx = parsed.findIndex((c) => c.activityId === args.activityId);
      if (idx === -1) return { ok: false, reason: "NOT_FOUND" };
      const c = parsed[idx];
      if (!c.salesforceId) return { ok: false, reason: "WRONG_STATUS" };
      parsed[idx] = {
        ...c,
        verified: true,
        verifiedAt: new Date().toISOString(),
        verifiedBy: args.actor.staffId,
      };
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
      return { ok: true, activityId: args.activityId };
    }

    const c = parsed[args.activityId];
    if (!c) return { ok: false, reason: "NOT_FOUND" };
    if (!c.salesforceId) return { ok: false, reason: "WRONG_STATUS" };
    parsed[args.activityId] = {
      ...c,
      verified: true,
      verifiedAt: new Date().toISOString(),
      verifiedBy: args.actor.staffId,
    };
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(parsed));
    return { ok: true, activityId: args.activityId };
  } catch {
    return { ok: false, reason: "NOT_FOUND" };
  }
}

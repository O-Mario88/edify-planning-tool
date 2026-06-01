// Canonical Salesforce Activity ID convention + validation.
//
// Core rule (Salesforce Completion Verification Gate):
//   An activity is not complete until the Salesforce Activity ID is
//   entered and submitted for verification. Evidence proves the work
//   happened; the Salesforce ID proves it was entered into Salesforce.
//
// Two ID formats — one per Salesforce object the activity is logged as:
//
//   • School Visit ID  → must start with "SVE-"  e.g. SVE-88273
//       school visit / follow-up / coaching / classroom observation /
//       partner school visit
//
//   • Training ID      → must start with "TS-"   e.g. TS-50294
//       training / in-school training / cluster meeting / SIT /
//       cluster training
//
// Cluster meetings are entered in Salesforce as TRAINING, so they use
// the TS- prefix and require a participant breakdown.
//
// This module is framework-agnostic (no React, no server-only) so it can
// be imported from client components, server engines, and mock data.

// ────────── Kinds + prefixes ──────────

export type SalesforceActivityKind = "visit" | "training";

/** Human label used on pills / completion records. */
export type SalesforceIdKind = "Visit ID" | "Training ID";

export const SF_PREFIX: Record<SalesforceActivityKind, string> = {
  visit:    "SVE-",
  training: "TS-",
};

export const SF_EXAMPLE: Record<SalesforceActivityKind, string> = {
  visit:    "SVE-88273",
  training: "TS-50294",
};

// Activity types that are logged in Salesforce as a TRAINING (TS-).
// Everything else is a visit (SV-). Matched on the human activity-type
// label so this works for both the typed engine union and the looser
// mobile/plan-item type strings. NB: "Training Follow-Up" is a VISIT
// (a school visit following up on a training), so we match exact labels
// rather than a naive "contains training" test.
const TRAINING_ACTIVITY_TYPES = new Set<string>([
  "Cluster Training",
  "Cluster Meeting",
  "In-School Training",
  "School Improvement Training",
  "SIT",
  "Training",
]);

export function salesforceKindFor(activityType: string): SalesforceActivityKind {
  return TRAINING_ACTIVITY_TYPES.has(activityType) ? "training" : "visit";
}

export function kindLabel(kind: SalesforceActivityKind): SalesforceIdKind {
  return kind === "training" ? "Training ID" : "Visit ID";
}

/** True for the activity types that require a participant breakdown. */
export function requiresParticipantCounts(activityType: string): boolean {
  return salesforceKindFor(activityType) === "training";
}

// ────────── Validation ──────────

export type SfIdValidation = { ok: boolean; message?: string };

const VISIT_MESSAGE =
  "School visit Salesforce ID must start with SVE-, for example SVE-88273.";
const TRAINING_MESSAGE =
  "Training Salesforce ID must start with TS-, for example TS-50294.";

export function sfPrefixMessage(kind: SalesforceActivityKind): string {
  return kind === "training" ? TRAINING_MESSAGE : VISIT_MESSAGE;
}

// A valid ID is the required prefix followed by at least one more
// character (the org's running number, e.g. SVE-88273). Case-insensitive
// on the prefix so "sve-88273" pasted from elsewhere still validates; the
// canonical stored form is upper-cased by `normalizeSalesforceId`.
export function isValidSalesforceId(raw: string, kind: SalesforceActivityKind): boolean {
  const trimmed = raw.trim();
  const prefix = SF_PREFIX[kind];
  if (trimmed.length <= prefix.length) return false;
  return trimmed.toUpperCase().startsWith(prefix);
}

/**
 * Validate a Salesforce Activity ID against the expected kind.
 * Returns `{ ok: true }` for empty input so the form doesn't shout
 * before the user has typed — callers gate submission on `ok` AND
 * non-empty separately.
 */
export function validateSalesforceId(raw: string, kind: SalesforceActivityKind): SfIdValidation {
  const trimmed = raw.trim();
  if (trimmed.length === 0) return { ok: false };
  if (!isValidSalesforceId(trimmed, kind)) {
    return { ok: false, message: sfPrefixMessage(kind) };
  }
  return { ok: true };
}

/** Upper-case the prefix while preserving the rest, for consistent storage. */
export function normalizeSalesforceId(raw: string): string {
  return raw.trim();
}

/** Infer which kind an already-entered ID looks like (for display/audit). */
export function kindFromId(id: string | undefined | null): SalesforceActivityKind | undefined {
  if (!id) return undefined;
  const upper = id.trim().toUpperCase();
  if (upper.startsWith(SF_PREFIX.training)) return "training";
  if (upper.startsWith(SF_PREFIX.visit)) return "visit";
  return undefined;
}

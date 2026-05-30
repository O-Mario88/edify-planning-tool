// Partner Verification Engine.
//
// Two outputs:
//   1. computeVerificationStatus(activity, ctx) — current state of
//      the activity in the verification pipeline.
//   2. shouldCountTowardTargets(activity) — strict yes/no on whether
//      this partner activity counts toward national targets.
//
// The spec is explicit: an activity may be Completed but NOT counted.
// The same target-counting discipline that protects staff numbers
// (only verified activities count) must apply to partner numbers.
// This file enforces that boundary.

import type {
  PartnerActivity,
  PartnerScope,
  VerificationLevel,
  VerificationStatus,
  EvidenceRequirement,
} from "./partner-types";

// ────────── Verification level resolution ──────────
//
// Level comes from scope, then is upgraded if the activity has
// fraud flags or carries a joint-work record. Never downgraded —
// raising the bar is always safe, lowering it isn't.

export function verificationLevelRequired(
  activity: Pick<PartnerActivity, "verificationLevel" | "fraudFlags" | "jointWorkId">,
  scope: Pick<PartnerScope, "defaultVerificationLevel">,
): VerificationLevel {
  // Start with the activity's own level (or scope default if unset).
  let level: VerificationLevel = activity.verificationLevel ?? scope.defaultVerificationLevel;

  // Joint-work always requires JointConfirmation at minimum.
  if (activity.jointWorkId && rank(level) < rank("JointConfirmation")) {
    level = "JointConfirmation";
  }

  // Fraud flags push to SpotCheck.
  if (activity.fraudFlags.length > 0 && rank(level) < rank("SpotCheck")) {
    level = "SpotCheck";
  }

  return level;
}

const LEVEL_RANK: Record<VerificationLevel, number> = {
  Light:             1,
  Standard:          2,
  JointConfirmation: 3,
  SpotCheck:         4,
  CDCertification:   5,
};
function rank(l: VerificationLevel): number { return LEVEL_RANK[l]; }

// ────────── Evidence completeness ──────────
//
// Compares attached evidence kinds against scope.evidenceRequirements.
// Missing required kinds → activity stays in EvidenceMissing.

export function missingRequiredEvidence(
  activity: Pick<PartnerActivity, "evidence">,
  scope: Pick<PartnerScope, "evidenceRequirements">,
): EvidenceRequirement[] {
  const attached = new Set(activity.evidence.map((e) => e.kind));
  return scope.evidenceRequirements.filter((r) => r.required && !attached.has(r.kind));
}

// ────────── computeVerificationStatus ──────────
//
// Single authoritative function. Takes the activity + scope + the
// signals from upstream (M&E review state, staff confirmation, etc.)
// and returns the current VerificationStatus.

export type VerificationContext = {
  /// Has M&E completed their review? (For Standard/SpotCheck/CDCert.)
  meReviewComplete: boolean;
  /// Did M&E mark the record valid? (Only meaningful if reviewed.)
  meReviewValid: boolean;
  /// Has the assigned staff confirmed (for JointConfirmation)?
  staffConfirmed: boolean;
  /// Has the Country Director signed off (for CDCertification)?
  cdCertified: boolean;
  /// Has M&E flagged this for audit?
  auditRequired: boolean;
  /// Has M&E sent back for correction with notes?
  returnedForCorrection: boolean;
};

export function computeVerificationStatus(
  activity: Pick<PartnerActivity, "status" | "evidence" | "fraudFlags" | "jointWorkId" | "verificationLevel">,
  scope: Pick<PartnerScope, "defaultVerificationLevel" | "evidenceRequirements">,
  ctx: VerificationContext,
): VerificationStatus {
  // Pre-completion the verification status is always EvidenceMissing
  // (or UnderReview if there's already evidence + review started).
  if (activity.status !== "Completed") {
    if (activity.evidence.length === 0) return "EvidenceMissing";
    if (ctx.meReviewComplete || ctx.returnedForCorrection) return "UnderReview";
    return "EvidenceMissing";
  }

  // Audit always wins — surfacing audit need is the most important signal.
  if (ctx.auditRequired) return "AuditRequired";

  // Returned-for-correction (most recent state).
  if (ctx.returnedForCorrection) return "ReturnedForCorrection";

  // Required evidence still missing → block.
  const missing = missingRequiredEvidence(activity, scope);
  if (missing.length > 0) return "EvidenceMissing";

  const level = verificationLevelRequired(activity, scope);

  // Light: evidence check only — verified once evidence is in.
  if (level === "Light") {
    // Light still goes through a quick M&E touch; if not reviewed,
    // we hold at UnderReview (avoids "instant approve" race).
    return ctx.meReviewComplete && ctx.meReviewValid ? "Verified" : "UnderReview";
  }

  // Standard: needs M&E review + evidence (we already passed evidence).
  if (level === "Standard") {
    if (!ctx.meReviewComplete) return "UnderReview";
    return ctx.meReviewValid ? "Verified" : "ReturnedForCorrection";
  }

  // Joint Confirmation: needs both M&E + staff confirmation.
  if (level === "JointConfirmation") {
    if (!ctx.meReviewComplete) return "UnderReview";
    if (!ctx.meReviewValid) return "ReturnedForCorrection";
    return ctx.staffConfirmed ? "Verified" : "UnderReview";
  }

  // Spot Check: M&E field check required (modelled here as a
  // reviewer note that explicitly clears).
  if (level === "SpotCheck") {
    if (!ctx.meReviewComplete) return "UnderReview";
    return ctx.meReviewValid ? "Verified" : "ReturnedForCorrection";
  }

  // CD Certification: needs everything below + final CD sign-off.
  if (level === "CDCertification") {
    if (!ctx.meReviewComplete) return "UnderReview";
    if (!ctx.meReviewValid) return "ReturnedForCorrection";
    if (!ctx.cdCertified) return "UnderReview";
    return "Verified";
  }

  return "UnderReview";
}

// ────────── shouldCountTowardTargets ──────────
//
// The strict gate. Partner activities count toward national targets
// only when ALL of these hold:
//   • activity status is Completed
//   • verification status is Verified or Counted
//   • activity passes the scope check at write time (presumed true if
//     the activity exists — scope is enforced on insert)
//   • Salesforce/internal match has resolved successfully
//   • no unresolved fraud-flag warnings
//
// This is the same discipline staff activities follow — the spec is
// emphatic: partner work obeys the same counting rule.

export function shouldCountTowardTargets(
  activity: Pick<
    PartnerActivity,
    "status" | "verificationStatus" | "fraudFlags" | "salesforceMatchStatus"
  >,
): boolean {
  if (activity.status !== "Completed") return false;
  if (activity.verificationStatus !== "Verified" && activity.verificationStatus !== "Counted") return false;
  if (activity.fraudFlags.length > 0) return false;
  if (activity.salesforceMatchStatus && activity.salesforceMatchStatus !== "Verified" && activity.salesforceMatchStatus !== "SmartMatch") return false;
  return true;
}

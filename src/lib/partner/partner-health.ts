// Partner Health Score.
//
// Single number — 0..100 — summarising partner delivery quality.
// Bands map the number to leadership-readable labels.
//
// The formula is intentionally simple: a weighted sum of six positive
// scores, minus two penalties. Keep it linear so the partner can see
// exactly which lever moves their score, and so a country can tune
// the weights without rewriting the engine.

import type {
  PartnerHealthBand,
  PartnerHealthInputs,
  PartnerHealthResult,
} from "./partner-types";

// ────────── Default weights ──────────
//
// Sum to 1.0 across the positive axes. Penalties subtract on top.
// Production stores per-country overrides in a
// PartnerHealthWeights table; engine accepts a custom set for tests.

export type PartnerHealthWeights = {
  verifiedDelivery: number;
  evidenceQuality: number;
  timeliness: number;
  schoolImprovement: number;
  staffCollaboration: number;
  reportingAccuracy: number;
  /// Penalty MULTIPLIERS (how heavily to weigh the penalty value).
  overduePenaltyWeight: number;
  returnedCorrectionPenaltyWeight: number;
};

export const DEFAULT_PARTNER_HEALTH_WEIGHTS: PartnerHealthWeights = {
  verifiedDelivery:                0.25,
  evidenceQuality:                 0.15,
  timeliness:                      0.10,
  schoolImprovement:               0.25,
  staffCollaboration:              0.10,
  reportingAccuracy:               0.15,
  overduePenaltyWeight:            0.30,
  returnedCorrectionPenaltyWeight: 0.20,
};

// ────────── Band thresholds ──────────
//
// Healthy is a wide band — most partners should live here. Excellent
// is a high bar; AtRisk and Suspended are deliberate red flags.

export function bandForScore(score: number): PartnerHealthBand {
  if (score <= 0)  return "Suspended";
  if (score < 50)  return "AtRisk";
  if (score < 70)  return "Watch";
  if (score < 85)  return "Healthy";
  return "Excellent";
}

// ────────── Compute ──────────

export function computePartnerHealth(
  inputs: PartnerHealthInputs,
  weights: PartnerHealthWeights = DEFAULT_PARTNER_HEALTH_WEIGHTS,
): PartnerHealthResult {
  const verifiedDelivery   = inputs.verificationPassRatePct  * weights.verifiedDelivery;
  const evidenceQuality    = inputs.evidenceQualityScore     * weights.evidenceQuality;
  const timeliness         = inputs.timelinessScore          * weights.timeliness;
  const schoolImprovement  = inputs.schoolImprovementScore   * weights.schoolImprovement;
  const staffCollaboration = inputs.staffCollaborationScore  * weights.staffCollaboration;
  const reportingAccuracy  = inputs.reportingAccuracyScore   * weights.reportingAccuracy;

  const overduePenalty           = inputs.overduePenalty           * weights.overduePenaltyWeight;
  const returnedCorrectionPenalty = inputs.returnedCorrectionPenalty * weights.returnedCorrectionPenaltyWeight;

  const raw =
    verifiedDelivery + evidenceQuality + timeliness +
    schoolImprovement + staffCollaboration + reportingAccuracy -
    overduePenalty - returnedCorrectionPenalty;

  // Clamp 0..100 — penalties can mathematically push below zero;
  // we floor at zero so "Suspended" is reachable but the score
  // doesn't render negative.
  const score = clamp(Math.round(raw), 0, 100);

  return {
    partnerId: inputs.partnerId,
    periodIso: inputs.periodIso,
    score,
    band: bandForScore(score),
    breakdown: {
      verifiedDelivery:           round1(verifiedDelivery),
      evidenceQuality:            round1(evidenceQuality),
      timeliness:                 round1(timeliness),
      schoolImprovement:          round1(schoolImprovement),
      staffCollaboration:         round1(staffCollaboration),
      reportingAccuracy:          round1(reportingAccuracy),
      overduePenalty:             round1(overduePenalty),
      returnedCorrectionPenalty:  round1(returnedCorrectionPenalty),
    },
  };
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

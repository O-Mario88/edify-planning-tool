// Quality of Support Score.
//
// The spec is explicit: "Do not reward activity volume without quality."
// This engine measures how well a school is being supported, not how
// many touches it received. A school visited 12 times with no measurable
// improvement scores LOWER than a school visited 4 times where SSA
// improved 1.5 points and follow-up actually closed the loop.
//
// Pure functions. Inputs come from the data the app already collects
// (visits, evidence attachments, debrief records, SSA history, follow-up
// completion, school feedback). Outputs land on the school profile
// AND drive a CPL inbox item when a school's score drops.

// ────────── Inputs ──────────

export type SupportQualityInputs = {
  schoolId: string;
  schoolName: string;
  periodIso: string;

  // Raw activity counts (used as denominators, not scored directly).
  activitiesAttempted: number;
  activitiesCompleted: number;

  // ─── Quality signals (each is a 0..100 sub-score the caller pre-computes) ───
  /// Evidence attached / required ratio, normalised 0..100.
  evidenceCompletenessPct: number;
  /// Debrief quality — caller scores 0..100 from rubric (length,
  /// specificity, action items captured).
  debriefQualityScore: number;
  /// Follow-ups requested / follow-ups completed × 100.
  followUpCompletionPct: number;
  /// School feedback score — average of post-visit school questions.
  schoolFeedbackScore: number;
  /// SSA score change in this period (positive = improvement). Raw
  /// number, the engine scales it.
  ssaDelta: number;
  /// Pre/post training assessment improvement, where applicable
  /// (otherwise pass undefined).
  trainingPrePostDeltaPct?: number;
  /// Classroom observation improvement (lesson quality), where
  /// observations exist.
  observationDeltaPct?: number;
  /// One Test / literacy improvement, where measured.
  literacyDeltaPct?: number;
  /// M&E verification rate on this school's activities (0..100).
  verificationRatePct: number;
  /// Did repeat support land where the engine predicted it was needed?
  /// 100 = every recommended follow-up happened.
  repeatSupportLandedPct: number;
};

// ────────── Weights ──────────
//
// Sum to 1.0. Tunable by country in production. Designed so
// school-outcome improvement weighs more than process-quality.

export type QualityWeights = {
  evidenceCompleteness: number;
  debriefQuality:       number;
  followUpCompletion:   number;
  schoolFeedback:       number;
  ssaImprovement:       number;
  trainingPrePost:      number;
  observationDelta:     number;
  literacyDelta:        number;
  verificationRate:     number;
  repeatSupportLanded:  number;
};

export const DEFAULT_QUALITY_WEIGHTS: QualityWeights = {
  evidenceCompleteness: 0.08,
  debriefQuality:       0.06,
  followUpCompletion:   0.12,
  schoolFeedback:       0.10,
  ssaImprovement:       0.20,    // outcome: heaviest single factor
  trainingPrePost:      0.12,
  observationDelta:     0.10,
  literacyDelta:        0.10,
  verificationRate:     0.06,
  repeatSupportLanded:  0.06,
};

// ────────── Band thresholds ──────────

export type QualityBand =
  | "Excellent"     // 85+
  | "Strong"        // 70..84
  | "Adequate"      // 55..69
  | "Inconsistent"  // 40..54
  | "AtRisk";       // < 40

export function bandForQualityScore(score: number): QualityBand {
  if (score >= 85) return "Excellent";
  if (score >= 70) return "Strong";
  if (score >= 55) return "Adequate";
  if (score >= 40) return "Inconsistent";
  return "AtRisk";
}

// ────────── Result ──────────

export type QualityResult = {
  schoolId: string;
  periodIso: string;
  score: number;       // 0..100
  band: QualityBand;
  breakdown: Record<keyof QualityWeights, number>;
  /// One-sentence reason for the band — surfaced verbatim in the UI.
  reason: string;
};

// ────────── Compute ──────────

export function computeSupportQuality(
  inputs: SupportQualityInputs,
  weights: QualityWeights = DEFAULT_QUALITY_WEIGHTS,
): QualityResult {
  // Scale SSA delta into a 0..100 contribution. SSA scale is 0..10;
  // a +1.0 delta over a period is excellent (→ 90), 0 is neutral (50),
  // -1.0 is bad (10). Engine clamps.
  const ssaImprovementScore = clamp(50 + inputs.ssaDelta * 40, 0, 100);

  // For optional deltas, missing data → neutral 50. Better to be
  // explicit about "we don't have a signal" than to assume zero.
  const trainingPrePostScore  = inputs.trainingPrePostDeltaPct ?? 50;
  const observationDeltaScore = inputs.observationDeltaPct    ?? 50;
  const literacyDeltaScore    = inputs.literacyDeltaPct       ?? 50;

  const breakdown = {
    evidenceCompleteness: round1(inputs.evidenceCompletenessPct * weights.evidenceCompleteness),
    debriefQuality:       round1(inputs.debriefQualityScore     * weights.debriefQuality),
    followUpCompletion:   round1(inputs.followUpCompletionPct   * weights.followUpCompletion),
    schoolFeedback:       round1(inputs.schoolFeedbackScore     * weights.schoolFeedback),
    ssaImprovement:       round1(ssaImprovementScore            * weights.ssaImprovement),
    trainingPrePost:      round1(trainingPrePostScore           * weights.trainingPrePost),
    observationDelta:     round1(observationDeltaScore          * weights.observationDelta),
    literacyDelta:        round1(literacyDeltaScore             * weights.literacyDelta),
    verificationRate:     round1(inputs.verificationRatePct     * weights.verificationRate),
    repeatSupportLanded:  round1(inputs.repeatSupportLandedPct  * weights.repeatSupportLanded),
  };
  const score = clamp(Math.round(Object.values(breakdown).reduce((a, b) => a + b, 0)), 0, 100);
  const band = bandForQualityScore(score);

  return {
    schoolId: inputs.schoolId,
    periodIso: inputs.periodIso,
    score,
    band,
    breakdown,
    reason: reasonForBand(band, inputs),
  };
}

function reasonForBand(band: QualityBand, inputs: SupportQualityInputs): string {
  switch (band) {
    case "Excellent":
      return `${inputs.activitiesCompleted} activities, SSA ${inputs.ssaDelta >= 0 ? "+" : ""}${inputs.ssaDelta.toFixed(1)} — support is landing.`;
    case "Strong":
      return `Solid follow-through. SSA ${inputs.ssaDelta >= 0 ? "+" : ""}${inputs.ssaDelta.toFixed(1)}; ${Math.round(inputs.followUpCompletionPct)}% follow-up complete.`;
    case "Adequate":
      return `Activities happening but outcome signal is mixed — worth a CPL check-in.`;
    case "Inconsistent":
      return `Follow-Up gaps + low feedback. Recommend coaching the assigned CCEO on follow-through.`;
    case "AtRisk":
      return `No measurable improvement despite activity. Pause + diagnose before more visits.`;
  }
}

// ────────── Helpers ──────────

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}
function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

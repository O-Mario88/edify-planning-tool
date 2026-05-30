// Fair Workload Index — the engine.
//
// Pure functions. Same discipline as pace-status.ts / weekly-fund-engine.ts:
// the engine takes inputs, returns results + the by-factor breakdown,
// and never touches I/O. Storage + scheduling are caller concerns.
//
// ─────────────────────────────────────────────────────────────────────
// Why this exists
// ─────────────────────────────────────────────────────────────────────
//
// The old `getPaceStatus` answers: "did this staff hit target?" It's
// fair to leave + holidays + blocked days but blind to the fact that
// two staff with identical pace numbers may have wildly different
// portfolio loads.
//
// FWI separates Output (Layer 1) from Load Difficulty (Layer 2):
//
//   • computePortfolioComplexity(...)   — Layer 2 score per staff
//   • workloadAdjustedPace(...)         — combines Layer 1 + Layer 2
//   • classifyBand(...)                 — turns the combination into a
//                                          performance band (TrueTop /
//                                          Consistent / Overloaded / ...)
//   • buildFairMatrix(...)              — assembles the dashboard row set
//   • generateRebalanceSuggestions(...) — leadership intervention output
//
// All five are independent so each can be tested + reasoned about
// without dragging the others.

import {
  DEFAULT_COMPLEXITY_WEIGHTS,
  type ComplexityResult,
  type ComplexityWeights,
  type FairMatrixRow,
  type PerformanceBand,
  type PortfolioComplexityInputs,
  type RebalanceRecommendation,
} from "./fwi-types";

// ────────── 1. Portfolio Complexity ──────────
//
// A single number summarising how heavy the staff's portfolio is.
// Computed as a weighted sum of system-derived inputs — no self-report.

export function computePortfolioComplexity(
  inputs: PortfolioComplexityInputs,
  weights: ComplexityWeights = DEFAULT_COMPLEXITY_WEIGHTS,
): ComplexityResult {
  const c = {
    schools:            inputs.schoolCount            * weights.schoolWeight,
    partnerSchools:     inputs.partnerSchoolCount     * weights.partnerSchoolWeight,
    districts:          inputs.districtCount          * weights.districtWeight,
    secondaryDistricts: inputs.secondaryDistrictCount * weights.secondaryDistrictWeight,
    highRisk:           inputs.highRiskSchoolCount    * weights.highRiskWeight,
    ssaWeakness:        inputs.avgSsaWeakness         * weights.ssaWeaknessWeight,
    distance:           (inputs.avgDistanceKm / 10)   * weights.distancePer10km,
    hotelTrips:         inputs.hotelTripsCount        * weights.hotelTripWeight,
    partners:           inputs.partnersManaged        * weights.partnerWeight,
    specialProjects:    inputs.specialProjectsActive  * weights.specialProjectWeight,
  };
  const score = round1(
    c.schools + c.partnerSchools + c.districts + c.secondaryDistricts +
    c.highRisk + c.ssaWeakness + c.distance + c.hotelTrips +
    c.partners + c.specialProjects,
  );
  return {
    staffId:   inputs.staffId,
    periodIso: inputs.periodIso,
    score,
    contributions: {
      schools:            round1(c.schools),
      partnerSchools:     round1(c.partnerSchools),
      districts:          round1(c.districts),
      secondaryDistricts: round1(c.secondaryDistricts),
      highRisk:           round1(c.highRisk),
      ssaWeakness:        round1(c.ssaWeakness),
      distance:           round1(c.distance),
      hotelTrips:         round1(c.hotelTrips),
      partners:           round1(c.partners),
      specialProjects:    round1(c.specialProjects),
    },
  };
}

// ────────── 2. Workload-Adjusted Pace ──────────
//
// Output × Load → a single percentage the UI can render on one axis.
// The math is intentionally restrained: a staff in the 95th percentile
// of complexity gets ~14% added to their pace at coefficient 0.3.
// Aggressive enough to matter; gentle enough that it doesn't make
// "everyone in a hard portfolio is suddenly excellent."

export function workloadAdjustedPace(
  rawPacePct: number,
  complexityPercentile: number,
  adjustmentCoefficient: number = 0.3,
): number {
  // Centre on the team median so above-median load is rewarded and
  // below-median load is dampened by the same magnitude. Inputs as
  // 0..1 percentile.
  const centred = clamp(complexityPercentile, 0, 1) - 0.5;
  const adj = 1 + centred * adjustmentCoefficient;
  return Math.max(0, Math.round(rawPacePct * adj));
}

// ────────── 3. Performance Band classification ──────────
//
// The classification rule MUST be unambiguous. The product spec was
// explicit: load percentile is the discriminator between "Overloaded"
// (high load, support warranted) and "Busy but Low Impact" (low load,
// coaching warranted). Both produce moderate output; mis-classifying
// here would send support to the wrong staff.

export type BandInputs = {
  rawPacePct: number;
  complexityPercentile: number; // 0..1
  /// Optional flags the engine uses when present.
  isProbationary?: boolean;
  /// 0..100 — how much this staff has visibly raised others
  /// (mentoring, coaching, special projects). Drives "Hidden Leader".
  teamSupportScore?: number;
  /// 0..100 — quality / impact signal (SSA delta, school improvement).
  /// Drives "Busy but Low Impact" — a staff doing many visits with
  /// no measurable school improvement.
  impactScore?: number;
};

const PROBATIONARY_BAND: PerformanceBand = "Establishing";

export function classifyBand(b: BandInputs): { band: PerformanceBand; reason: string } {
  if (b.isProbationary) {
    return {
      band: PROBATIONARY_BAND,
      reason: "First 90 days — building baseline before scoring.",
    };
  }
  const pct = clamp(b.complexityPercentile, 0, 1);
  const pace = b.rawPacePct;

  // Hidden Leader — moderate personal pace but strong team-support
  // signal. Important: this band must be checked BEFORE the Top
  // Performer / Consistent split so a quiet coach isn't mis-labeled
  // as a mediocre individual contributor.
  if ((b.teamSupportScore ?? 0) >= 75 && pace >= 70 && pace < 95) {
    return {
      band: "HiddenLeader",
      reason: "Moderate personal pace, but consistently raising the team through coaching and special projects.",
    };
  }

  // Busy but Low Impact — high activity, low school improvement.
  // Only triggered when impact signal is present AND below threshold.
  if ((b.impactScore ?? 100) < 50 && pace >= 90) {
    return {
      band: "BusyLowImpact",
      reason: "Strong activity volume, but school improvement is lagging. Quality may be the unlock over quantity.",
    };
  }

  // High output × high load → True Top Performer.
  if (pace >= 85 && pct >= 0.65) {
    return {
      band: "TrueTopPerformer",
      reason: "Strong delivery on a heavier-than-average portfolio.",
    };
  }
  // High output × low/medium load → Consistent.
  if (pace >= 90) {
    return {
      band: "Consistent",
      reason: "Reliable delivery. Portfolio could absorb more responsibility.",
    };
  }
  // Moderate-to-low output × high load → Overloaded (needs support,
  // not punishment).
  if (pct >= 0.65 && pace >= 60) {
    return {
      band: "Overloaded",
      reason: "Carrying above-average load. Output trails — check what support helps.",
    };
  }
  // Low output × low/medium load → Concern (real coaching conversation).
  if (pace < 70) {
    return {
      band: "Concern",
      reason: "Output below where the portfolio would predict. A coaching conversation is recommended.",
    };
  }
  // Default safety net — light/medium load, medium pace.
  return {
    band: "Consistent",
    reason: "Steady delivery in line with portfolio load.",
  };
}

// ────────── 4. Fair Matrix assembly ──────────
//
// Takes a list of staff with their pace + complexity inputs, computes
// percentiles within the group, and returns rows ready for the
// scatter-plot. Percentiles are within-team — a deliberate choice so
// the matrix always shows useful contrast even when the absolute
// load is high across the whole region.

export type FairMatrixInput = {
  staffId: string;
  staffName: string;
  initials: string;
  rawPacePct: number;
  complexityInputs: PortfolioComplexityInputs;
  isProbationary?: boolean;
  teamSupportScore?: number;
  impactScore?: number;
};

export function buildFairMatrix(
  staff: FairMatrixInput[],
  opts: { adjustmentCoefficient?: number; weights?: ComplexityWeights } = {},
): FairMatrixRow[] {
  if (staff.length === 0) return [];

  const weights = opts.weights ?? DEFAULT_COMPLEXITY_WEIGHTS;
  const coeff = opts.adjustmentCoefficient ?? 0.3;

  // 1. Compute complexity for everyone.
  const complexities = staff.map((s) =>
    computePortfolioComplexity(s.complexityInputs, weights),
  );
  // 2. Percentile each within the team. Sort then index — O(n log n)
  //    but n is the team size (≤ 30 typically) so trivial cost.
  const sortedScores = [...complexities.map((c) => c.score)].sort((a, b) => a - b);
  const percentile = (score: number): number => {
    if (sortedScores.length <= 1) return 0.5;
    // Fraction of team strictly below this score; ties handled by
    // taking the *upper* index so the highest-load staff is at ~1.
    let countBelow = 0;
    for (const v of sortedScores) if (v < score) countBelow += 1;
    return countBelow / (sortedScores.length - 1);
  };

  // 3. Build the row set.
  return staff.map((s, idx) => {
    const cx = complexities[idx];
    const pct = percentile(cx.score);
    const { band, reason } = classifyBand({
      rawPacePct: s.rawPacePct,
      complexityPercentile: pct,
      isProbationary: s.isProbationary,
      teamSupportScore: s.teamSupportScore,
      impactScore: s.impactScore,
    });
    return {
      staffId: s.staffId,
      staffName: s.staffName,
      initials: s.initials,
      rawPacePct: s.rawPacePct,
      adjustedPacePct: workloadAdjustedPace(s.rawPacePct, pct, coeff),
      complexityScore: cx.score,
      complexityPercentile: pct,
      band,
      bandReason: reason,
    };
  });
}

// ────────── 5. Rebalance recommendations ──────────
//
// Looks at the team's complexity distribution; if any staff carry
// >1.5× the team median and any others <0.7× the median, the engine
// suggests moving schools from the over-loaded to the under-loaded.
// The specific schools to move are the ones closest to the receiving
// staff's home base — that's the move that minimises new travel cost.
//
// Important: this function does NOT mutate state. It returns
// recommendations the CPL accepts or dismisses. The actedOn boolean
// on the persisted record tracks adoption.

export type RebalanceInput = {
  staffId: string;
  staffName: string;
  complexityScore: number;
  /// School set the staff currently owns. The engine picks from this
  /// list when suggesting moves.
  schools: Array<{
    schoolId: string;
    schoolName: string;
    /// Distance from the *current* owner's home base.
    currentOwnerDistanceKm: number;
    /// Distance from each candidate receiver's home base. Drives the
    /// "which school to move" decision.
    distanceFromCandidates: Record<string, number>;
  }>;
};

export function generateRebalanceSuggestions(
  team: RebalanceInput[],
  opts: { medianMultiplierHigh?: number; medianMultiplierLow?: number } = {},
): RebalanceRecommendation[] {
  if (team.length < 2) return [];
  const HIGH = opts.medianMultiplierHigh ?? 1.5;
  const LOW = opts.medianMultiplierLow ?? 0.7;

  const scores = [...team.map((s) => s.complexityScore)].sort((a, b) => a - b);
  const median = scores[Math.floor(scores.length / 2)];
  if (median <= 0) return [];

  const overloaded = team
    .filter((s) => s.complexityScore > median * HIGH)
    .sort((a, b) => b.complexityScore - a.complexityScore);
  const underloaded = team
    .filter((s) => s.complexityScore < median * LOW)
    .sort((a, b) => a.complexityScore - b.complexityScore);

  if (overloaded.length === 0 || underloaded.length === 0) return [];

  const recs: RebalanceRecommendation[] = [];

  for (const from of overloaded) {
    for (const to of underloaded) {
      // Pick up to 2 schools from `from` whose receiving-side distance
      // is shortest. Avoids "move 8 schools" recs that destabilise
      // both staff at once — small moves are easier to accept and
      // measure.
      const movable = [...from.schools]
        .filter((s) => s.distanceFromCandidates[to.staffId] !== undefined)
        .sort(
          (a, b) =>
            (a.distanceFromCandidates[to.staffId] ?? Infinity) -
            (b.distanceFromCandidates[to.staffId] ?? Infinity),
        )
        .slice(0, 2);

      if (movable.length === 0) continue;

      // Estimate post-move loads. We cap the per-suggestion impact at
      // 15% on either side because (a) a single rebalance shouldn't
      // drop someone's load by more — anything larger is a portfolio
      // overhaul, not a fairness nudge — and (b) the `schools` array
      // here is the candidate set the engine sees, which may be smaller
      // than the staff's full portfolio (depends on the caller). The
      // cap protects against accidental "move 100% of mock schools"
      // recommendations.
      const MAX_SHARE = 0.15;
      const fromShare = Math.min(
        MAX_SHARE,
        from.schools.length > 0 ? movable.length / from.schools.length : 0,
      );
      const fromLoadAfter = round1(from.complexityScore * (1 - fromShare));
      const toShare = Math.min(
        MAX_SHARE,
        movable.length / Math.max(1, to.schools.length + movable.length),
      );
      const toLoadAfter = round1(to.complexityScore * (1 + toShare));

      recs.push({
        fromStaffId: from.staffId,
        fromStaffName: from.staffName,
        toStaffId: to.staffId,
        toStaffName: to.staffName,
        schoolIds: movable.map((s) => s.schoolId),
        schoolNames: movable.map((s) => s.schoolName),
        fromLoadBefore: round1(from.complexityScore),
        fromLoadAfter,
        toLoadBefore: round1(to.complexityScore),
        toLoadAfter,
        reason: composeReason(from, to, movable, fromLoadAfter, toLoadAfter),
      });

      // One suggestion per overloaded staff per cycle — avoid spamming
      // the CPL with five rebalances they can't act on at once.
      break;
    }
  }
  return recs;
}

function composeReason(
  from: RebalanceInput,
  to: RebalanceInput,
  schools: Array<{ schoolName: string }>,
  fromAfter: number,
  toAfter: number,
): string {
  const schoolPhrase = schools.length === 1
    ? `${schools[0].schoolName}`
    : `${schools[0].schoolName} and ${schools.length - 1} other${schools.length > 2 ? "s" : ""}`;
  return (
    `${from.staffName} is carrying load score ${round1(from.complexityScore)}; ` +
    `${to.staffName} is at ${round1(to.complexityScore)}. ` +
    `Moving ${schoolPhrase} would bring both closer to balance ` +
    `(${fromAfter} and ${toAfter}). Schools chosen are nearest to ${to.staffName.split(" ")[0]}'s home base.`
  );
}

// ────────── Helpers ──────────

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

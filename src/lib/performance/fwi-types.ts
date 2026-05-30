// FWI types — shared across engine, mocks, and UI.
//
// Keeping the types in their own file lets the engine stay pure (no
// imports of mock data into the engine surface) and lets UI
// components import shapes without dragging in computation.

export type PerformanceBand =
  | "TrueTopPerformer"
  | "Consistent"
  | "Overloaded"
  | "Concern"
  | "BusyLowImpact"
  | "HiddenLeader"
  | "Establishing";

// Human-friendly labels — never derive these from the enum case
// (which is for the data layer). The dashboard reads these.
export const BAND_LABEL: Record<PerformanceBand, string> = {
  TrueTopPerformer: "True Top Performer",
  Consistent:       "Consistent Performer",
  Overloaded:       "Carrying Heavy Load",
  Concern:          "Needs Coaching Conversation",
  BusyLowImpact:    "Busy but Low Impact",
  HiddenLeader:     "Hidden Leader",
  Establishing:     "Establishing Baseline",
};

// Short blurb shown under the band on profile cards. Phrased so the
// person reading their own profile wouldn't feel insulted — even the
// "Concern" copy frames it as a conversation, not a verdict.
export const BAND_BLURB: Record<PerformanceBand, string> = {
  TrueTopPerformer: "Strong delivery on a heavy portfolio.",
  Consistent:       "Reliable delivery. Portfolio could absorb more.",
  Overloaded:       "Carrying more load than the team average. Worth checking what support helps.",
  Concern:          "Output is below where the portfolio would predict. A coaching conversation is recommended.",
  BusyLowImpact:    "Lots of activity, lower impact on schools. Quality over quantity may be the unlock.",
  HiddenLeader:     "Quietly raising the team — coaching, mentoring, special projects.",
  Establishing:     "First 90 days. Building baseline before scoring.",
};

// Tone for chips / dots in the UI. Tied to the existing design tokens.
export const BAND_TONE: Record<PerformanceBand, "emerald" | "sky" | "amber" | "rose" | "violet" | "slate"> = {
  TrueTopPerformer: "emerald",
  Consistent:       "sky",
  Overloaded:       "amber",
  Concern:          "rose",
  BusyLowImpact:    "amber",
  HiddenLeader:     "violet",
  Establishing:     "slate",
};

// Raw inputs the engine reads. Everything here is either system-derived
// (from a join) or set by the PL — NEVER self-reported by the staff
// being scored. Self-reporting is the #1 gaming risk.
export type PortfolioComplexityInputs = {
  staffId: string;
  staffName: string;
  /// FY-month or quarter string — drives historical comparison.
  periodIso: string;
  schoolCount: number;
  partnerSchoolCount: number;
  districtCount: number;
  /// Subset of districtCount NOT in staff's primary district.
  secondaryDistrictCount: number;
  highRiskSchoolCount: number;
  /// Average SSA weakness across the portfolio, 0 (strong) – 10 (very weak).
  avgSsaWeakness: number;
  /// Average one-way km from home base to schools in portfolio.
  avgDistanceKm: number;
  /// Trips that required overnight stay in the period.
  hotelTripsCount: number;
  /// Total travel km logged in the period (for context, not raw scoring).
  totalTravelKm: number;
  /// Distinct partners the staff coordinates with.
  partnersManaged: number;
  /// Open special-projects assignments at period end.
  specialProjectsActive: number;
};

// Weights for combining raw inputs into a single score. Live in the
// CountryPerformanceWeights row in production; mocked here for the
// engine's local default.
export type ComplexityWeights = {
  schoolWeight: number;
  partnerSchoolWeight: number;
  districtWeight: number;
  secondaryDistrictWeight: number;
  highRiskWeight: number;
  ssaWeaknessWeight: number;
  distancePer10km: number;
  hotelTripWeight: number;
  partnerWeight: number;
  specialProjectWeight: number;
};

export const DEFAULT_COMPLEXITY_WEIGHTS: ComplexityWeights = {
  schoolWeight:           1.0,
  partnerSchoolWeight:    0.75,
  districtWeight:         3.0,
  secondaryDistrictWeight: 5.0,
  highRiskWeight:         2.0,
  ssaWeaknessWeight:      1.5,
  distancePer10km:        0.5,
  hotelTripWeight:        5.0,
  partnerWeight:          4.0,
  specialProjectWeight:   7.0,
};

// Computed result — what goes into PortfolioComplexity row + UI.
export type ComplexityResult = {
  staffId: string;
  periodIso: string;
  score: number;
  /// Contribution-by-factor breakdown so the UI can render a transparent
  /// "this is why your portfolio scores N points" tooltip.
  contributions: {
    schools: number;
    partnerSchools: number;
    districts: number;
    secondaryDistricts: number;
    highRisk: number;
    ssaWeakness: number;
    distance: number;
    hotelTrips: number;
    partners: number;
    specialProjects: number;
  };
};

// One staff member's row in the Fair Matrix. Combines pace
// (target-completion %) with the complexity score, classified into a
// band so the UI doesn't have to reproduce the rule.
export type FairMatrixRow = {
  staffId: string;
  staffName: string;
  initials: string;
  /// 0-100, from target-counting engine. Same number that appears
  /// everywhere else in the app — single source of truth.
  rawPacePct: number;
  /// Pace after the workload adjustment is applied. This is the
  /// number used in the matrix's vertical axis.
  adjustedPacePct: number;
  /// Raw complexity score (engine output, not percentile).
  complexityScore: number;
  /// Where this staff sits relative to the team — drives the
  /// horizontal axis of the matrix.
  complexityPercentile: number;
  band: PerformanceBand;
  /// Short reasons string the matrix shows on hover.
  bandReason: string;
};

// One row of the Rebalance recommendations card.
export type RebalanceRecommendation = {
  fromStaffId: string;
  fromStaffName: string;
  toStaffId: string;
  toStaffName: string;
  /// How many schools the engine suggests moving and which ones.
  /// (Engine picks schools closest to the receiving staff's home base.)
  schoolIds: string[];
  schoolNames: string[];
  /// Predicted complexity score for both staff after the move.
  fromLoadBefore: number;
  fromLoadAfter: number;
  toLoadBefore: number;
  toLoadAfter: number;
  /// Plain-English summary the UI renders verbatim.
  reason: string;
};

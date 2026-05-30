// Donor Reporting Impact — type contract.
//
// These types describe the evidence-backed numbers the analytics surface
// reports up to donors. Every metric is structured so the UI never has
// to guess: counts are split by donor-count status, each metric records
// its data source (live-derived vs awaiting schema), and the snapshot as
// a whole carries the filter context that produced it.

// ── Scope & status enums ────────────────────────────────────────────

export type DonorRoleScope =
  | "CCEO"             // single field officer
  | "ProgramLead"      // CPL — program-scope rollup
  | "ImpactAssessment" // IA — verification-first cut
  | "CountryDirector"  // CD — national rollup
  | "RVP";             // regional/cross-country

/** Status of an individual record's contribution to a donor count. */
export type DonorCountStatus =
  | "included_verified"
  | "included_confirmed"
  | "pending_evidence"
  | "pending_verification"
  | "excluded_duplicate"
  | "excluded_missing_data"
  | "excluded_out_of_period"
  | "excluded_not_eligible";

/** Aggregate status a metric is presented under to leadership. */
export type DonorMetricStatus =
  | "verified"
  | "confirmed"
  | "pending_evidence"
  | "pending_cceo_confirmation"
  | "pending_me_verification"
  | "excluded";

/** Where the number came from — keeps the UI honest. */
export type MetricSource =
  | "derived"         // computed from primary records in the DB
  | "pending_schema"  // schema does not yet capture this; not reportable
  | "estimated";      // computed but with caveats (e.g. enrollment gaps)

/** Visual grouping for KPI cards. */
export type DonorMetricGroup =
  | "reach"
  | "training"
  | "geography"
  | "evidence"
  | "cost"
  | "impact";

// ── Filter context ──────────────────────────────────────────────────

export interface DonorReportingFilters {
  operationalCycleLabel: string;     // "FY 2025/26 Q4"
  dateRangeStart: string;            // ISO date
  dateRangeEnd: string;              // ISO date
  region?: string;
  district?: string;
  subCounty?: string;
  parish?: string;
  cluster?: string;
  schoolType?: "client" | "core" | "all";
  activityType?: string;
  interventionArea?: string;
  deliveredBy?: "staff" | "partner" | "all";
  partner?: string;
  cceo?: string;
  programLead?: string;
  evidenceStatus?: string;
  verificationStatus?: string;
  donorReportingStatus?: string;
}

// ── Single metric ───────────────────────────────────────────────────

/** Count breakdown used by every numeric donor metric. */
export interface DonorMetricBreakdown {
  /** Total before any exclusions — what staff have done in scope. */
  total: number;
  /** Records meeting the donor-reportable bar (verified or confirmed). */
  donorReady: number;
  /** Records that are confirmed by CCEO but not yet IA-verified. */
  confirmed: number;
  /** Records waiting for evidence to be attached. */
  pendingEvidence: number;
  /** Records with evidence attached but not yet IA-verified. */
  pendingVerification: number;
  /** Records intentionally dropped (duplicate / out of period / not eligible). */
  excluded: number;
}

/** A single donor reporting metric — number + provenance. */
export interface DonorMetric {
  key: string;                       // "teachersTrained"
  label: string;                     // donor-friendly label
  group: DonorMetricGroup;
  /** Aggregate display status. */
  status: DonorMetricStatus;
  /** Where the number came from. */
  source: MetricSource;
  /** Headline numeric value for the card (matches breakdown.donorReady when source = derived). */
  value: number | null;
  /** Per-status split. `null` when source is `pending_schema`. */
  breakdown: DonorMetricBreakdown | null;
  /** Short caption shown under the number. */
  caption?: string;
  /** Optional unit (e.g. "people", "schools", "UGX"). */
  unit?: string;
  /** Whether higher is better — controls chip colour on trend. */
  higherIsBetter?: boolean;
  /** Notes that surface as the metric's tooltip — definition + caveats. */
  definition?: string;
  /** Data-quality issues that affect this specific metric. */
  dataQualityNotes?: string[];
}

// ── Donor Reporting Readiness ───────────────────────────────────────

export interface DonorReadinessComponent {
  key: string;
  label: string;
  /** 0..100 */
  pct: number;
  note?: string;
}

export interface DonorReadiness {
  /** 0..100 — weighted average across components. */
  score: number;
  components: DonorReadinessComponent[];
  /** Plain-language summary of where the report stands. */
  summary: string;
}

// ── Intervention & Geography breakdowns ─────────────────────────────

export type InterventionArea =
  | "Teaching & Learning"
  | "Financial Health"
  | "Christlike Behaviour"
  | "Exposure to the Word of God"
  | "Government Requirements & Compliance"
  | "Leadership"
  | "Education Technology"
  | "Learning Environment";

export interface InterventionRow {
  area: InterventionArea;
  trainings: number;
  teachersTrained: number;
  schoolLeadersTrained: number;
  schoolsReached: number;
  studentsImpacted: number | null;
  schoolsImproved: number | null;
  costUgx: number | null;
}

export interface DistrictRow {
  district: string;
  schoolsReached: number;
  teachersTrained: number;
  schoolLeadersTrained: number;
  studentsImpacted: number | null;
  trainings: number;
  visits: number;
  costUgx: number | null;
  schoolsImproved: number | null;
}

// ── Data quality ────────────────────────────────────────────────────

export type DataQualitySeverity = "warning" | "blocker" | "info";

export interface DataQualityWarning {
  severity: DataQualitySeverity;
  title: string;
  detail: string;
  affectedMetricKeys: string[];
}

// ── The full snapshot ───────────────────────────────────────────────

export interface DonorMetricSnapshot {
  roleScope: DonorRoleScope;
  /** Display name shown on the surface ("Daniel Mwangi" / "Uganda"). */
  scopeLabel: string;
  filters: DonorReportingFilters;
  generatedAt: string;              // ISO timestamp
  generatedBy: string;

  /** All numeric KPI tiles, in display order. */
  metrics: DonorMetric[];

  readiness: DonorReadiness;
  interventions: InterventionRow[];
  districts: DistrictRow[];
  warnings: DataQualityWarning[];

  /**
   * Reach summary used for the "Students Impacted" calculation transparency:
   * schools reached vs schools with enrollment data on file.
   */
  enrollmentCoverage: {
    schoolsReached: number;
    schoolsWithEnrollment: number;
    schoolsMissingEnrollment: number;
    note: string;
  };
}

// ── Helpers ─────────────────────────────────────────────────────────

export const METRIC_GROUP_LABELS: Record<DonorMetricGroup, string> = {
  reach: "Reach",
  training: "Training",
  geography: "Geography",
  evidence: "Evidence",
  cost: "Cost",
  impact: "Impact",
};

export const METRIC_STATUS_LABELS: Record<DonorMetricStatus, string> = {
  verified: "Verified",
  confirmed: "Confirmed",
  pending_evidence: "Pending Evidence",
  pending_cceo_confirmation: "Pending CCEO Confirmation",
  pending_me_verification: "Pending M&E Verification",
  excluded: "Excluded from Donor Count",
};

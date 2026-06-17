import "server-only";

// Typed, scoped data surfaces over the edify-api backend.
//
// One place that knows the backend's response shapes and the paths the UI
// pulls from. Every fetcher returns a `LiveResult`: either live backend data
// or a "not live" signal (backend disabled, or unreachable + the reason) so
// callers can fall back to the in-memory mock without each page re-implementing
// the enable-check / error-handling dance that core-schools pioneered.
//
// Server-only — the Bearer token never crosses to the browser.

import { backendFetch, isBackendEnabled, type BackendUser } from "./backend";

export type LiveResult<T> =
  | { live: true; data: T }
  | { live: false; error: string | null };

async function live<T>(path: string, user: BackendUser, init?: RequestInit): Promise<LiveResult<T>> {
  if (!isBackendEnabled()) return { live: false, error: null };
  const r = await backendFetch<T>(path, user, init);
  return r.ok ? { live: true, data: r.data } : { live: false, error: r.error };
}

// ── Backend response shapes (mirror edify-api controllers) ──────────

export type BeSchoolRow = {
  id: string;
  schoolId: string;
  name: string;
  schoolType: string;
  clusterStatus: string;
  clusterId?: string | null;
  currentFySsaStatus: string;
  planningReadiness: string;
  accountOwnerStatus: string;
  accountOwnerNameRaw?: string | null;
  subCountyId?: string | null;
  shippingAddress?: string | null;
  schoolPhone?: string | null;
  primaryContactName?: string | null;
  primaryContactPhone?: string | null;
  enrollment?: number | null;
  duplicateStatus?: string | null;
  region?: { name: string } | null;
  district?: { name: string } | null;
  subCounty?: { name: string } | null;
  parish?: { name: string } | null;
  cluster?: { name: string } | null;
  accountOwner?: { user?: { name?: string } | null } | null;
};

export type BePaginated<T> = {
  data: T[];
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
};

export type BeCoreHeader = {
  fy: string;
  corePlansCount: number;
  championsCount: number;
  awaitingSSACount: number;
  totalCoreSchools: number;
  planningReadyCount: number;
};

export type BeDashboard = {
  role: string;
  scope: { countryScope: boolean; schoolsInScope: number | null };
  schools: number;
  coreSchools: number;
  clientSchools: number;
  planningReady: number;
  unclustered: number;
  ssaDone: number;
};

export type BeLeadershipSummary = {
  countryScope: boolean;
  schools: number; coreSchools: number; clientSchools: number;
  clustered: number; unclustered: number; ssaDone: number; ssaPending: number;
  ssaCompletePct: number; ssaAverage: number;
  byIntervention: { intervention: string; average: number }[];
  weakestInterventions: { intervention: string; average: number }[];
  pipeline: { planned: number; scheduled: number; inProgress: number; evidenceUploaded: number; awaitingIa: number; iaVerified: number; completed: number };
  activitiesTotal: number;
  staffCount: number; partnerCount: number;
  fundRequests: number; paymentsCleared: number; disbursedTotalUgx: number;
};

export type BeSsaPerformance = {
  schoolsWithSsa: number;
  overallAverage: number;
  byIntervention: { intervention: string; average: number }[];
};

export type BeActivityPipeline = {
  total: number;
  byStatus: { status: string; count: number }[];
  byDelivery: { deliveryType: string; count: number }[];
};

// ── Fetchers ────────────────────────────────────────────────────────

// Shared geography filter as emitted by the FE filter bar. district is a *name*
// ("Gulu"), region a *key* ("northern"), cluster a cuid — the backend resolves
// names via relation filters. The `__all__` sentinel and empty values are dropped
// so an unfiltered call stays unfiltered. Used by every role-scoped analytics
// surface so a selected geography narrows the WHOLE page, not just grouped tables.
export type GeoFilterParams = { region?: string; district?: string; cluster?: string };
const ALL_SENTINEL = "__all__";
function appendGeo(params: URLSearchParams, g?: GeoFilterParams): URLSearchParams {
  if (g?.region && g.region !== ALL_SENTINEL) params.set("region", g.region);
  if (g?.district && g.district !== ALL_SENTINEL) params.set("district", g.district);
  if (g?.cluster && g.cluster !== ALL_SENTINEL) params.set("cluster", g.cluster);
  return params;
}
function geoQuery(g?: GeoFilterParams): string {
  const q = appendGeo(new URLSearchParams(), g).toString();
  return q ? `?${q}` : "";
}

type SchoolQuery = {
  schoolType?: string;
  pageSize?: number;
  search?: string;
  districtId?: string;
  clusterStatus?: string;
  ssaStatus?: string;
  planningReadiness?: string;
} & GeoFilterParams;

export function fetchSchools(user: BackendUser, q: SchoolQuery = {}) {
  const params = new URLSearchParams();
  if (q.schoolType) params.set("schoolType", q.schoolType);
  params.set("pageSize", String(q.pageSize ?? 200));
  if (q.search) params.set("search", q.search);
  if (q.districtId) params.set("districtId", q.districtId);
  if (q.clusterStatus) params.set("clusterStatus", q.clusterStatus);
  if (q.ssaStatus) params.set("ssaStatus", q.ssaStatus);
  if (q.planningReadiness) params.set("planningReadiness", q.planningReadiness);
  // Name/key geography from the filter bar — server-narrows the full universe so
  // the directory list + strip aren't capped at the first `pageSize` rows.
  appendGeo(params, q);
  return live<BePaginated<BeSchoolRow>>(`/schools?${params.toString()}`, user);
}

export function fetchCoreHeader(user: BackendUser) {
  return live<BeCoreHeader>("/filters/core-header-summary", user);
}

export function fetchAnalyticsDashboard(user: BackendUser, geo?: GeoFilterParams) {
  return live<BeDashboard>(`/analytics/dashboard${geoQuery(geo)}`, user);
}
export function fetchLeadershipSummary(user: BackendUser, geo?: GeoFilterParams) {
  return live<BeLeadershipSummary>(`/analytics/leadership-summary${geoQuery(geo)}`, user);
}
export type BeDistrictRollup = {
  districtId: string; district: string; region: string;
  schools: number; coreSchools: number; clientSchools: number;
  clustered: number; unclustered: number;
  ssaDone: number; ssaPct: number; avgSsa: number;
};
export function fetchDistrictRollups(user: BackendUser, geo?: GeoFilterParams) {
  return live<{ districts: BeDistrictRollup[] }>(`/analytics/districts${geoQuery(geo)}`, user);
}

// The district NAMES the user actually has live data for — used to build the
// geography filter dropdowns from the real backend universe (so the bar offers
// exactly the districts that exist, with a working region→district cascade and
// an active label that resolves). Returns undefined when the backend is off, so
// the caller falls back to the mock-derived filter scope.
export async function liveDistrictNamesFor(user: BackendUser): Promise<string[] | undefined> {
  const res = await fetchDistrictRollups(user);
  if (!res.live) return undefined;
  return res.data.districts.map((d) => d.district).filter(Boolean);
}
export type BeSchoolDirectorySummary = {
  byType: { schoolType: string; count: number }[];
  byReadiness: { readiness: string; count: number }[];
  unmatchedOwners: number;
  potentialDuplicates: number;
};
export function fetchSchoolDirectorySummary(user: BackendUser, geo?: GeoFilterParams) {
  return live<BeSchoolDirectorySummary>(`/analytics/school-directory${geoQuery(geo)}`, user);
}
export type BeCoverageSummary = {
  totalClientSchools: number; assigned: number; unassigned: number;
  coveragePct: number; schoolsBelowSsaThreshold: number;
  priority: { schoolId: string; name: string; district: string; owner: string; avgSsa: number | null }[];
};
export function fetchCoverageSummary(user: BackendUser, geo?: GeoFilterParams) {
  return live<BeCoverageSummary>(`/analytics/coverage${geoQuery(geo)}`, user);
}

// ── Geo-analytics map ──────────────────────────────────────────────
export type BeGeoDistrict = {
  districtId: string; pcode: string | null; district: string; region: string; subRegion: string | null;
  centroidLat: number | null; centroidLng: number | null;
  schools: number; coreSchools: number; clientSchools: number;
  clustered: number; unclustered: number; ssaDone: number; ssaPending: number; ssaPct: number;
  avgSsa: number | null; criticalCount: number; activitiesCompleted: number;
  status: "healthy" | "needs_attention" | "high_risk" | "insufficient_data";
};
export type BeGeoSchoolPoint = { schoolId: string; name: string; lat: number; lng: number; type: string };
export type BeGeoSubRegion = {
  subRegion: string; region: string; districts: number; schools: number; coreSchools: number;
  clustered: number; avgSsa: number | null; criticalCount: number; activitiesCompleted: number;
};
export type BeGeoMap = {
  fy: string;
  summary: { districts: number; subRegions: number; schools: number; coreSchools: number; clustered: number; criticalSchools: number; highRiskDistricts: number; activitiesCompleted: number };
  districts: BeGeoDistrict[];
  subRegions: BeGeoSubRegion[];
  schoolPoints: BeGeoSchoolPoint[];
};
export function fetchGeoMap(user: BackendUser, geo?: GeoFilterParams) {
  return live<BeGeoMap>(`/analytics/geo-map${geoQuery(geo)}`, user);
}

export function fetchAnalyticsSsa(user: BackendUser, geo?: GeoFilterParams) {
  return live<BeSsaPerformance>(`/analytics/ssa-performance${geoQuery(geo)}`, user);
}

export function fetchActivityPipeline(user: BackendUser, geo?: GeoFilterParams) {
  return live<BeActivityPipeline>(`/analytics/activity-pipeline${geoQuery(geo)}`, user);
}

// ── Contribution ("how much am I contributing?") — scope-enforced ──

export type ContributionLens = "own" | "team" | "combined";
export type ContributionMetricKey =
  | "schoolsReached" | "teachersTrained" | "schoolLeadersTrained"
  | "learnersImpacted" | "districtsCovered" | "ssaImprovement";

export type ContributionMetrics = {
  schoolsReached: number;
  clientSchoolsReached: number;
  coreSchoolsSupported: number;
  projectSchoolsSupported: number;
  learnersImpacted: number;
  teachersTrained: number;
  schoolLeadersTrained: number;
  districtsCovered: number;
  subCountiesCovered: number;
  clustersCovered: number;
  regionsCovered: number;
  visitsCompleted: number;
  trainingsCompleted: number;
  clusterMeetingsCompleted: number;
  ssaCompleted: number;
  schoolsImproved: number;
  bestIntervention: string | null;
  worstIntervention: string | null;
  partnerActivities: number;
  staffActivities: number;
  evidencePending: number;
  salesforceIdsPending: number;
  iaVerifiedActivities: number;
};

export type ContributionSummary = {
  lens: ContributionLens;
  role: string;
  summaryOnly: boolean;
  canViewTeam: boolean;
  schoolsInScope: number;
  metrics: ContributionMetrics;
  dataQuality: string[];
};

type ContributionParams = { lens?: ContributionLens; fy?: string; quarter?: string; districtId?: string; clusterId?: string } & GeoFilterParams;

function contributionQuery(p: ContributionParams): string {
  const params = new URLSearchParams();
  params.set("lens", p.lens ?? "own");
  if (p.fy) params.set("fy", p.fy);
  if (p.quarter) params.set("quarter", p.quarter);
  if (p.districtId) params.set("districtId", p.districtId);
  if (p.clusterId) params.set("clusterId", p.clusterId);
  appendGeo(params, p);
  return params.toString();
}

export function fetchContributionSummary(user: BackendUser, p: ContributionParams = {}) {
  return live<ContributionSummary>(`/analytics/contribution-summary?${contributionQuery(p)}`, user);
}

export function fetchContributionDrilldown(
  user: BackendUser,
  p: ContributionParams & { metric: ContributionMetricKey },
) {
  const params = new URLSearchParams(contributionQuery(p));
  params.set("metric", p.metric);
  return live<Record<string, unknown>[]>(`/analytics/contribution-drilldown?${params.toString()}`, user);
}

// ── SSA Performance by group (8 intervention averages, drillable) ──

export type BeSsaGroupRow = {
  groupId: string; groupName: string;
  schoolCount: number; schoolsAssessed: number; schoolsMissingSSA: number;
  interventions: Record<string, number | null>;
  overallAverage: number | null;
};
export type BeSsaPerformanceGrouped = {
  fy: string; groupBy: string; schoolType: string;
  canGroupByCceo?: boolean;
  interventions: { code: string; label: string }[];
  rows: BeSsaGroupRow[];
};
export type BeSsaDrilldownRow = {
  schoolId: string; name: string; schoolType: string;
  district: string | null; cluster: string | null; cceo: string | null;
  ssaDate: string | null; overallAverage: number | null;
  interventions: Record<string, number | null>;
};

export function fetchSsaPerformanceGrouped(user: BackendUser, p: { groupBy?: string; schoolType?: string; fy?: string } & GeoFilterParams = {}) {
  const params = new URLSearchParams();
  if (p.groupBy) params.set("groupBy", p.groupBy);
  if (p.schoolType) params.set("schoolType", p.schoolType);
  if (p.fy) params.set("fy", p.fy);
  appendGeo(params, p);
  const q = params.toString();
  return live<BeSsaPerformanceGrouped>(`/analytics/ssa-performance-grouped${q ? `?${q}` : ""}`, user);
}

export type BeImprovementIntervention = { code: string; label: string; prevAvg: number | null; currAvg: number | null; change: number | null };
export type BeImprovementRow = {
  groupId: string; groupName: string;
  schoolsImproved: number; schoolsDeclined: number; schoolsNoChange: number; schoolsNoComparison: number;
  improvementRate: number | null;
  bestIntervention: { code: string; label: string; change: number } | null;
  decliningIntervention: { code: string; label: string; change: number } | null;
  weakestIntervention: { code: string; label: string; currAvg: number | null } | null;
  interventions: BeImprovementIntervention[];
};
export type BeInterventionImprovement = {
  currentFy: string; prevFy: string; groupBy: string; schoolType: string;
  canGroupByCceo?: boolean;
  interventions: { code: string; label: string }[];
  rows: BeImprovementRow[];
};

export function fetchInterventionImprovement(user: BackendUser, p: { groupBy?: string; schoolType?: string; currentFy?: string; prevFy?: string } & GeoFilterParams = {}) {
  const params = new URLSearchParams();
  if (p.groupBy) params.set("groupBy", p.groupBy);
  if (p.schoolType) params.set("schoolType", p.schoolType);
  if (p.currentFy) params.set("currentFy", p.currentFy);
  if (p.prevFy) params.set("prevFy", p.prevFy);
  appendGeo(params, p);
  const q = params.toString();
  return live<BeInterventionImprovement>(`/analytics/intervention-improvement${q ? `?${q}` : ""}`, user);
}

export function fetchSsaDrilldown(user: BackendUser, p: { groupBy: string; groupId: string; fy?: string; schoolType?: string }) {
  const params = new URLSearchParams({ groupBy: p.groupBy, groupId: p.groupId });
  if (p.fy) params.set("fy", p.fy);
  if (p.schoolType) params.set("schoolType", p.schoolType);
  return live<BeSsaDrilldownRow[]>(`/analytics/ssa-performance-grouped/drilldown?${params.toString()}`, user);
}

// ── My Plan (activities) — the write-path migration surface ─────────

export type BeActivity = {
  id: string;
  schoolId?: string | null;
  activityType: string;
  status: string;
  deliveryType: string;
  scheduledDate?: string | null;
  // Week/month-grained scheduling (visits carry these instead of an exact date).
  // The backend already returns them on the activity row.
  plannedMonth?: number | null;
  plannedWeek?: number | null;
  month?: number | null;
  week?: number | null;
  rescheduleCount?: number | null;
  lastReason?: string | null;
  assignedPartnerId?: string | null;
  school?: { schoolId: string; name: string; district?: { name: string } | null } | null;
  cluster?: { name: string } | null;
  assignedPartner?: { name: string } | null;
  // Workflow fields (returned by the backend; used by IA/accountant views).
  fy?: string;
  quarter?: string;
  salesforceActivityId?: string | null;
  evidenceStatus?: string;
  iaVerificationStatus?: string;
  paymentStatus?: string;
};

/** The caller's own activities (My Plan), from the backend. */
export function fetchMyPlanActivities(user: BackendUser, fy?: string) {
  const params = new URLSearchParams({ mine: "true", pageSize: "100" });
  if (fy) params.set("fy", fy);
  return live<BePaginated<BeActivity>>(`/activities?${params.toString()}`, user);
}

export type ActivityLifecycleAction = "reschedule" | "reassign" | "cancel" | "defer" | "complete";

/** Run a lifecycle action against a backend activity (My Plan row actions). */
export function backendActivityAction(user: BackendUser, id: string, action: ActivityLifecycleAction, body: Record<string, unknown>) {
  return live<BeActivity>(`/activities/${encodeURIComponent(id)}/${action}`, user, { method: "POST", body: JSON.stringify(body) });
}

/** Create an activity on the backend (capacity-enforced). Returns the live result
 *  so callers can distinguish an enforced 403 from a 404 (school not in backend). */
export function backendCreateActivity(user: BackendUser, body: Record<string, unknown>) {
  return live<BeActivity>(`/activities`, user, { method: "POST", body: JSON.stringify(body) });
}

// ── Cost preview from the CD Country Cost Register (scheduling drawer) ──
export type BeCostLine = { label: string; key: string; unit: number | null; qty: number; amount: number; missing: boolean };
export type BeCostPreview = { source: string; currency: string; amount: number; costMissing: boolean; lines: BeCostLine[] };
export function backendCostPreview(
  user: BackendUser,
  body: { activityType: string; deliveryType?: string; districtType?: string; teachersAttended?: number; leadersAttended?: number; otherParticipants?: number },
) {
  return live<BeCostPreview>(`/budget/costing/preview`, user, { method: "POST", body: JSON.stringify(body) });
}

// ── School detail + assignment (reads migration) ────────────────────

export type BeSchoolDetail = {
  id: string;
  schoolId: string;
  name: string;
  schoolType: string;
  enrollment?: number | null;
  clusterStatus: string;
  currentFySsaStatus: string;
  planningReadiness: string;
  accountOwnerNameRaw?: string | null;
  region?: { name: string } | null;
  district?: { name: string } | null;
  cluster?: { name: string } | null;
  accountOwner?: { user?: { name?: string } } | null;
  ssaRecords?: { id: string; fy: string; averageScore?: number | null; dateOfSsa: string }[];
};

/** A single school from the backend directory (by external schoolId). */
export function fetchSchoolDetail(user: BackendUser, schoolId: string) {
  return live<BeSchoolDetail>(`/schools/${encodeURIComponent(schoolId)}`, user);
}

// ── Targets by Time Period (staff vs partner, cumulative) ───────────
export type BeTargetCell = { target: number; achieved: number; pct: number | null };
export type BeTargetRow = { period: string; staff: BeTargetCell; partner: BeTargetCell; total: BeTargetCell; gap: number; status: string };
export type BeTargets = {
  fy: string; staffId: string; totalPortfolio: number;
  annual: { staffTarget: number; partnerTarget: number; total: number };
  rows: BeTargetRow[]; dataQuality: string[];
};

export function fetchTargetsByPeriod(user: BackendUser, fy?: string, staffId?: string) {
  const params = new URLSearchParams();
  if (fy) params.set("fy", fy);
  if (staffId) params.set("staffId", staffId);
  const q = params.toString();
  return live<BeTargets>(`/targets/time-period${q ? `?${q}` : ""}`, user);
}

export type BeWorkflowStep = { key: string; label: string; done: boolean; status: "done" | "current" | "pending" };
export type BeSchoolWorkflow = {
  school: { schoolId: string; name: string; schoolType: string; owner?: string | null };
  fy: string | null;
  stage: string;
  steps: BeWorkflowStep[];
  nextAction: { type: string; label: string; reason: string } | null;
  blockers: string[];
};

/** The full school improvement journey (the main workflow). */
export function fetchSchoolWorkflow(user: BackendUser, schoolId: string, fy?: string) {
  const q = fy ? `?fy=${encodeURIComponent(fy)}` : "";
  return live<BeSchoolWorkflow>(`/schools/${encodeURIComponent(schoolId)}/workflow${q}`, user);
}

export type BeAssignmentOption = { type: "self" | "staff" | "partner"; label: string; enabled: boolean; reason?: string; staffId?: string };
export type BeAssignmentOptions = {
  schoolId: string;
  fy: string;
  capacity: { staffId: string; fy: string; max: number; used: number; remaining: number; atLimit: boolean; nearLimit: boolean };
  options: BeAssignmentOption[];
};

export type BeStaffCapacity = { staffId: string; fy: string; max: number; used: number; remaining: number; atLimit: boolean; nearLimit: boolean };

/** The caller's (or a given staff's) direct-support capacity from the backend. */
export function fetchStaffCapacity(user: BackendUser, staffId?: string, fy?: string) {
  const params = new URLSearchParams();
  if (staffId) params.set("staffId", staffId);
  if (fy) params.set("fy", fy);
  const q = params.toString();
  return live<BeStaffCapacity>(`/assignment/capacity${q ? `?${q}` : ""}`, user);
}

/** Role + capacity-aware assignment options for a school (backend-enforced). */
export function fetchAssignmentOptions(user: BackendUser, schoolId: string, fy?: string) {
  const params = new URLSearchParams({ schoolId });
  if (fy) params.set("fy", fy);
  return live<BeAssignmentOptions>(`/assignment/options?${params.toString()}`, user);
}

// ── Partner-to-payment (accountant) ─────────────────────────────────
export type BePaymentQueueRow = {
  id: string;
  activityType: string;
  salesforceActivityId: string | null;
  evidenceStatus: string;
  iaVerificationStatus: string;
  paymentStatus: string;
  school: { schoolId: string; name: string } | null;
  assignedPartner: { name: string } | null;
  ready: boolean;
};

/** Partner-delivered activities sitting in the payment pipeline (accountant-scoped). */
export function fetchPaymentQueue(user: BackendUser) {
  return live<BePaymentQueueRow[]>(`/activities/payment-queue`, user);
}

/** Accountant clears a partner payment. Backend enforces IA-verified + SF id + evidence accepted. */
export function clearPayment(user: BackendUser, activityId: string) {
  return live<{ id: string; paymentStatus: string }>(
    `/activities/${encodeURIComponent(activityId)}/clear-payment`,
    user,
    { method: "POST" },
  );
}

// ── Leadership Decision Engine ──────────────────────────────────────
export type BeDecisionEvidence = {
  id: string;
  metricName: string;
  metricValue: string;
  comparisonValue?: string | null;
  sourceType: string;
  explanation?: string | null;
  weight: string;
  tone?: string | null;
};
export type BeDecisionInsight = {
  id: string;
  fy: string;
  decisionType: string;
  scopeType: string;
  scopeId?: string | null;
  scopeName?: string | null;
  recommendation: string;
  reason: string;
  riskLevel: string;
  confidenceLevel: string;
  confidenceScore: number;
  contextAdjustment?: string | null;
  financialImplication?: string | null;
  suggestedAction: string;
  alternatives: string[];
  metrics: Record<string, unknown>;
  riskFlags: string[];
  status: string;
  reviewedByUserId?: string | null;
  reviewedAt?: string | null;
  evidencePoints: BeDecisionEvidence[];
  _count?: { notes: number };
};
export type BeDecisionBoard = { decisionType: string; canReview: boolean; insights: BeDecisionInsight[] };
export type BeLeadershipBoards = { fy: string; visibleBoards: string[]; boards: BeDecisionBoard[] };
export type BeLeadershipSnapshot = {
  fy: string;
  strategicHeadline: string;
  regionsReadyToExpand: (string | null)[];
  regionsToPauseRecruitment: (string | null)[];
  staffOverloadRisks: number;
  partnerMouRisks: number;
  partnerCapacityGaps: number;
  dataConfidence: number;
  highRiskDecisions: number;
  totalInsights: number;
};

export function fetchLeadershipBoards(user: BackendUser, q: { fy?: string; decisionType?: string; riskLevel?: string; confidenceLevel?: string } = {}) {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v) sp.set(k, v);
  const qs = sp.toString();
  return live<BeLeadershipBoards>(`/leadership/decision-engine${qs ? `?${qs}` : ""}`, user);
}
export function fetchLeadershipSnapshot(user: BackendUser, fy?: string) {
  return live<BeLeadershipSnapshot>(`/leadership/decision-engine/snapshot${fy ? `?fy=${encodeURIComponent(fy)}` : ""}`, user);
}

// ── Layer 3: Support-to-Improvement correlation ─────────────────────
export type BeSupportFilter = "all" | "staff" | "partner" | "certified_partner" | "visit" | "training" | "project";

export type BeCorrelationSummary = {
  schoolsWithComparison: number;
  correlation: number | null;
  strength: string;
  avgSupport: number | null;
  avgImprovement: number | null;
  interpretation: string;
};
export type BeInterventionBin = {
  code: string; label: string;
  zero: number | null; zeroN: number; low: number | null; lowN: number; high: number | null; highN: number;
};
export type BeChartPoint = { schoolId: string; name: string; support: number; improvement: number; supportClass: string };
export type BeSupportCorrelation = {
  currentFy: string; prevFy: string; support: BeSupportFilter;
  summary: BeCorrelationSummary;
  chartPoints: BeChartPoint[];
  interventionBins: BeInterventionBin[];
  dataQuality: string[];
};
export type BeStaffVsPartnerGroup = {
  supportClass: string; schools: number;
  avgOverallImprovement: number | null; avgInterventionImprovement: number | null;
  schoolsImprovedPct: number | null; schoolsDeclinedPct: number | null; avgVerifiedSupport: number | null;
};
export type BeStaffVsPartner = { currentFy: string; prevFy: string; groups: BeStaffVsPartnerGroup[]; note: string; dataQuality: string[] };

export function fetchSupportSsaCorrelation(user: BackendUser, params: { support?: string; schoolType?: string; districtId?: string; regionId?: string } = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return live<BeSupportCorrelation>(`/analytics/support-ssa-correlation${s ? `?${s}` : ""}`, user);
}

export function fetchStaffVsPartner(user: BackendUser, params: { schoolType?: string; districtId?: string; regionId?: string } = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return live<BeStaffVsPartner>(`/analytics/staff-vs-partner-correlation${s ? `?${s}` : ""}`, user);
}

// ── Recruitment Intelligence ────────────────────────────────────────
export type BeRecruitmentDistrict = { districtId: string; district: string; schools: number; ssaCompletionPct: number; clusteredPct: number; reachedPct: number; score: number; signal: "expand" | "hold" | "pause" };
export type BeRecruitment = {
  fy: string; scope: string; readinessScore: number;
  recommendation: string; reason: string;
  capacity: { totalSchools: number; core: number; client: number; reachedPct: number; partnerPaymentBacklog: number; partnerEvidencePending: number; partnerStrainPct: number };
  ssaReadiness: { currentSsaPct: number; previousSsaPct: number; impactReadyPct: number; missingCurrentSsa: number };
  dataQuality: { missingCluster: number; unmatchedOwner: number; duplicates: number; missingEnrollment: number; penaltyPct: number };
  impact: { schoolsImproved: number; schoolsDeclined: number };
  suggestedRecruitDistricts: { districtId: string; district: string; ssaCompletionPct: number; score: number }[];
  pauseDistricts: { districtId: string; district: string; ssaCompletionPct: number; score: number }[];
  districts: BeRecruitmentDistrict[];
  nextAction: string; disclaimer: string;
};

// ── Daily Debrief ───────────────────────────────────────────────────
export type BeDebrief = {
  id: string; fy: string; date: string; debriefType: string; status: string;
  whatHappened?: string | null; whatWentWell?: string | null; whatDidNotGoWell?: string | null;
  blockers: string[]; supportNeeded?: string | null; recommendations?: string | null; nextAction?: string | null;
  submittedByRole: string; submittedAt: string; routedTo?: number;
};
export type BeDebriefToday = { submittedToday: boolean; mine: BeDebrief[]; partnerInputs: BeDebrief[] };

export type SubmitDebriefBody = {
  debriefType?: "staff" | "partner"; partnerId?: string; responsibleStaffId?: string;
  whatHappened?: string; whatWentWell?: string; whatDidNotGoWell?: string;
  blockers?: string[]; blockerOther?: string;
  supportNeeded?: string; recommendations?: string; nextAction?: string;
  linkedSchoolIds?: string[]; linkedActivityIds?: string[];
};

export function submitDebrief(user: BackendUser, body: SubmitDebriefBody) {
  return live<BeDebrief>(`/debriefs`, user, { method: "POST", body: JSON.stringify(body) });
}
export function fetchDebriefsToday(user: BackendUser) {
  return live<BeDebriefToday>(`/debriefs/today`, user);
}

// ── SSA verification QA (10% client-portfolio rule) ─────────────────
export type BeSsaVerifyRequirement = {
  staffId: string; fy: string; clientPortfolioCount: number; requiredSampleCount: number;
  verifiedSampleCount: number; gap: number; percentage: number; meetsRequirement: boolean;
  partnerPending: number; schoolsMissingSsa: number;
};
export type BeSsaVerifySummary = {
  fy: string; staffCount: number; staffMeetingRequirement: number; staffBelowRequirement: number;
  compliancePct: number; totalRequiredSample: number; totalVerifiedSample: number; partnerPendingTotal: number;
  belowStaff: BeSsaVerifyRequirement[];
};
export function fetchSsaVerificationRequirements(user: BackendUser, staffId?: string) {
  return live<BeSsaVerifyRequirement>(`/ssa/verification-requirements${staffId ? `?staffId=${encodeURIComponent(staffId)}` : ""}`, user);
}
export function fetchSsaVerificationSummary(user: BackendUser) {
  return live<BeSsaVerifySummary>(`/ssa/verification-summary`, user);
}

// ── Budget = the schedule, costed (automatic costing spine) ─────────
export type BeCostSetting = { id: string; key: string; label: string; unitCost: number; fy?: string | null; version?: number; updatedAt?: string };
export type BeCostSettings = { settings: BeCostSetting[]; count: number };
export type BeBudgetMonth = { month: number; label: string; amount: number; count: number; trainings: number; insight?: string };
export type BeBudgetFromSchedule = {
  live: true; fy: string; role: string; scope: "own" | "team" | "country";
  total: number; activityCount: number; costMissingCount: number;
  scheduledTotal: number; unscheduledCount: number; unscheduledAmount: number;
  byMonth: BeBudgetMonth[];
  byQuarter: { quarter: string; amount: number; count: number }[];
  byType: { type: string; amount: number; count: number }[];
  byDelivery: { staff: { amount: number; count: number }; partner: { amount: number; count: number } };
  busyMonths: BeBudgetMonth[]; slowMonths: BeBudgetMonth[]; avgMonthlyCost: number;
};
export type BeBudgetCostLine = { label: string; key: string; unit: number | null; qty: number; amount: number; missing: boolean };
export type BeBudgetWeeklyLine = {
  id: string; activityType: string; deliveryType: string; status: string;
  month: number | null; week: number | null; scheduledDate: string | null;
  place: string; district: string | null; staff: string | null; partner: string | null;
  amount: number; costMissing: boolean; lines: BeBudgetCostLine[];
  paymentStatus: string; iaVerificationStatus: string;
};
export type BeBudgetWeekly = {
  live: true; fy: string; role: string; total: number; count: number; costMissingCount: number;
  weeks: { key: string; month: number | null; week: number | null; amount: number; count: number }[];
  lines: BeBudgetWeeklyLine[];
};
export function fetchBudgetFromSchedule(user: BackendUser, fy?: string) {
  return live<Omit<BeBudgetFromSchedule, "live">>(`/budget/from-schedule${fy ? `?fy=${encodeURIComponent(fy)}` : ""}`, user);
}
export function fetchBudgetWeekly(user: BackendUser, opts: { fy?: string; month?: number } = {}) {
  const q = new URLSearchParams();
  if (opts.fy) q.set("fy", opts.fy);
  if (opts.month) q.set("month", String(opts.month));
  const qs = q.toString();
  return live<Omit<BeBudgetWeekly, "live">>(`/budget/weekly${qs ? `?${qs}` : ""}`, user);
}
export function fetchCostSettings(user: BackendUser) {
  return live<BeCostSettings>(`/budget/cost-settings`, user);
}
export function setCostSetting(user: BackendUser, body: { key: string; label?: string; unitCost: number; fy?: string; reason?: string }) {
  return live<{ ok: boolean; setting: BeCostSetting }>(`/budget/cost-settings`, user, { method: "POST", body: JSON.stringify(body) });
}
export type BeCostHistoryRow = {
  id: string; key: string; label: string; oldUnitCost?: number | null; newUnitCost: number;
  version: number; fy?: string | null; changedByUserId: string; reason?: string | null; changedAt: string;
};
export function fetchCostHistory(user: BackendUser, key?: string) {
  return live<{ history: BeCostHistoryRow[]; count: number }>(`/budget/cost-settings/history${key ? `?key=${encodeURIComponent(key)}` : ""}`, user);
}

// ── Special Projects (backend-backed; no mock) ──────────────────────
export type BeProject = {
  id: string; code?: string | null; name: string; category: string; intervention?: string | null;
  managerStaffId?: string | null; schoolCount: number; partnerCount: number; activityCount: number;
  latestImpact?: unknown; latestImpactFy?: string | null;
};
export type BeProjectDetail = {
  id: string; name: string; category: string; intervention?: string | null; managerStaffId?: string | null;
  schools: { schoolId: string; name: string; schoolType: string; district: string | null; ssaStatus: string }[];
  partners: { id: string; name: string; isCertified: boolean; certificationStatus?: string | null }[];
  impactSnapshots: { fy: string; metrics: unknown }[];
};
export function fetchSpecialProjects(user: BackendUser) {
  return live<BeProject[]>(`/special-projects`, user);
}
export function fetchProjectDetail(user: BackendUser, id: string) {
  return live<BeProjectDetail>(`/special-projects/${encodeURIComponent(id)}`, user);
}
// ── Project impact (intervention improvement) + partner monitoring ──
export type BeProjectImpact = {
  projectId: string; name: string; intervention?: string | null;
  schoolCount: number; measuredCount: number; improvedCount: number; avgDelta: number | null;
  schools: { schoolId: string; name: string; baseline: number | null; latest: number | null; delta: number | null; ssaCount: number }[];
};
export type BeProjectPartner = { id: string; name: string; isCertified: boolean; certificationStatus?: string | null; activityTotal: number; activityCompleted: number };
export function fetchProjectImpact(user: BackendUser, id: string) {
  return live<BeProjectImpact>(`/special-projects/${encodeURIComponent(id)}/impact`, user);
}
export function fetchProjectPartners(user: BackendUser, id: string) {
  return live<BeProjectPartner[]>(`/special-projects/${encodeURIComponent(id)}/partners`, user);
}
export function assignProjectPartner(user: BackendUser, projectId: string, partnerId: string) {
  return live<{ ok: boolean }>(`/special-projects/${encodeURIComponent(projectId)}/partners`, user, { method: "POST", body: JSON.stringify({ partnerId }) });
}
export function removeProjectPartner(user: BackendUser, projectId: string, partnerId: string) {
  return live<{ ok: boolean }>(`/special-projects/${encodeURIComponent(projectId)}/partners/${encodeURIComponent(partnerId)}`, user, { method: "DELETE" });
}
// Assignment write paths — `projectId` may be the backend cuid OR the business
// code (e.g. "SP-EDTECH"); the backend resolves either. `schoolId` is the
// business School-Directory id; the backend rejects anything not in the Directory.
export function assignProjectSchool(user: BackendUser, projectId: string, schoolId: string) {
  return live<{ ok: boolean; schoolId: string; projectId: string }>(
    `/special-projects/${encodeURIComponent(projectId)}/schools`,
    user,
    { method: "POST", body: JSON.stringify({ schoolId }) },
  );
}
export function removeProjectSchool(user: BackendUser, projectId: string, schoolId: string) {
  return live<{ ok: boolean; schoolId: string; projectId: string }>(
    `/special-projects/${encodeURIComponent(projectId)}/schools/${encodeURIComponent(schoolId)}`,
    user,
    { method: "DELETE" },
  );
}

// ── Command Center (recommendation-led "what must I do next") ───────
export type BeActionItem = {
  id: string; priority: "critical" | "high" | "medium"; kind: string;
  title: string; reason: string;
  subject?: { kind: string; id: string; name: string };
  action: { label: string; href: string };
  count?: number;
};
export type BeTodayFeed = {
  live: true; role: string; scope: "own" | "team" | "country";
  summary: { total: number; critical: number; action: number; attention: number };
  groups: { key: string; label: string; items: BeActionItem[] }[];
};
export function fetchCommandCenterToday(user: BackendUser) {
  return live<Omit<BeTodayFeed, "live">>(`/command-center/today`, user);
}

// ── Fund requests (approval queue + dynamic detail) ─────────────────
export type BeFundCostLine = { label: string; qty: number; unit: number | null; amount: number; missing: boolean };
export type BeFundActivityCost = {
  id: string; activityType: string; deliveryType: string; target: string;
  month: number | null; amount: number; costMissing: boolean; lines: BeFundCostLine[];
};
export type BeFundRequest = {
  id: string; fy: string; period: string; periodKey: string; scope: string;
  submittedBy: string; submittedByRole: string; totalAmount: number; activityCount: number;
  status: "submitted" | "approved" | "returned" | "rejected" | "disbursed";
  reviewedAt?: string | null; reviewNote?: string | null; createdAt: string;
  // Disbursement + accountability (the back half of the money pipeline).
  disbursedAmount?: number | null; disbursedAt?: string | null; disburseMethod?: string | null; disburseReference?: string | null;
  accountedAmount?: number | null; returnedAmount?: number | null;
  accountabilityStatus?: "none" | "submitted" | "approved" | "returned" | null;
  accountabilityNetsuiteId?: string | null; accountabilitySubmittedAt?: string | null; accountabilityReviewedAt?: string | null;
  // Present on the list (whether YOU may act) and detail (the costed breakdown).
  canReview?: boolean;
  // The list also flags the accountability close-out leg: isOwn = you submitted
  // this (so you account for it); canAccountReview = you supervise the submitter
  // and they've filed accountability awaiting your approve/return.
  isOwn?: boolean;
  canAccountReview?: boolean;
  breakdown?: { total: number; count: number; activities: BeFundActivityCost[] } | null;
};
export function fetchFundRequests(user: BackendUser) {
  return live<BeFundRequest[]>(`/fund-requests`, user);
}
export function fetchFundRequest(user: BackendUser, id: string) {
  return live<BeFundRequest>(`/fund-requests/${encodeURIComponent(id)}`, user);
}
export function reviewFundRequest(user: BackendUser, id: string, action: "approve" | "return" | "reject", note?: string) {
  return live<BeFundRequest>(`/fund-requests/${encodeURIComponent(id)}/${action}`, user, { method: "POST", body: JSON.stringify({ note }) });
}
/** Generic fund-request action — review (approve/return/reject), disburse,
 *  account, account-approve, account-return. Body passed straight through. */
export function backendFundAction(user: BackendUser, id: string, action: string, body?: Record<string, unknown>) {
  return live<BeFundRequest>(`/fund-requests/${encodeURIComponent(id)}/${action}`, user, { method: "POST", body: JSON.stringify(body ?? {}) });
}
/** Submit (generate) a fund request from the caller's scheduled work for a
 *  period — derived from the plan + CD cost register; blocked on missing cost. */
export function submitFundRequest(user: BackendUser, body: { period?: string; month?: number; quarter?: string }) {
  return live<BeFundRequest>(`/fund-requests`, user, { method: "POST", body: JSON.stringify(body) });
}

// ── Activities — generic scoped list (IA queue, etc.; My Plan uses
//    fetchMyPlanActivities; actions use backendActivityAction above) ──
export function fetchActivities(user: BackendUser, qs = "") {
  return live<BePaginated<BeActivity>>(`/activities${qs}`, user);
}
// Generic action caller — covers the full row state machine incl. ia-confirm /
// clear-payment (backendActivityAction above is typed to the 5 plan-row actions).
export function activityAction(user: BackendUser, id: string, action: string, body: Record<string, unknown> = {}) {
  return live<unknown>(`/activities/${encodeURIComponent(id)}/${action}`, user, { method: "POST", body: JSON.stringify(body) });
}

// ── Planning (setup buckets + core) ─────────────────────────────────
export type BePlanningBucket = { key: string; label: string; count: number; items: BePlanningSchool[] };
export type BePlanningSchool = {
  schoolId: string; name: string; schoolType: string; districtId?: string | null;
  subCounty?: string | null; owner?: string | null; ssaStatus: string; planningReadiness: string; stage?: string;
};
export function fetchPlanningSetup(user: BackendUser, qs = "") {
  return live<BePlanningBucket[]>(`/planning/setup${qs}`, user);
}
export function fetchPlanningCore(user: BackendUser, qs = "") {
  return live<unknown>(`/planning/core${qs}`, user);
}

// ── SSA for a specific school (the View SSA drawer) ─────────────────
export type BeSsaScore = { intervention: string; score: number };
export type BeSchoolSsaRecord = {
  id: string; fy: string; dateOfSsa?: string | null; averageScore?: number | null;
  verificationStatus: string; collectorType?: string | null; scores: BeSsaScore[];
};
export function fetchSsaForSchool(user: BackendUser, schoolId: string) {
  return live<BeSchoolSsaRecord[]>(`/ssa/school/${encodeURIComponent(schoolId)}`, user);
}
// SSA-driven recommendation (two weakest interventions + severity) — the
// backend source that replaces the empty in-memory mock rec-engine.
export type BeSsaRecommendation = {
  schoolId: string; hasSsa: boolean; fy?: string; averageScore?: number | null;
  severity: string; weakest: { intervention: string; score: number; label: string }[]; recommendation: string;
};
export function fetchSsaRecommendation(user: BackendUser, schoolId: string) {
  return live<BeSsaRecommendation>(`/ssa/school/${encodeURIComponent(schoolId)}/recommendation`, user);
}

// ── Clusters (backend-backed; no mock) ──────────────────────────────
export type BeCluster = {
  id: string; name: string; clusterType: string; status: string;
  district?: { name: string } | null; subCounty?: { name: string } | null;
  subCountyName?: string | null; responsibleStaffId?: string | null;
  clusterLeaderName?: string | null; clusterLeaderPhone?: string | null;
  subCounties?: string[]; subCountyIds?: string[];
  schoolCount?: number; schoolsWithSsa?: number;
  _count?: { schools: number };
};
// A cluster as returned by the eligibility endpoint (covered set + leader).
export type BeEligibleCluster = {
  id: string; name: string; district?: string | null; status: string; clusterType: string;
  subCounty?: string | null; subCounties: string[];
  clusterLeaderName?: string | null; clusterLeaderPhone?: string | null;
  schoolCount: number;
};
export type BeClusterEligibility = {
  schoolId: string; subCounty?: string | null;
  eligible: BeEligibleCluster[]; districtAlternatives: BeEligibleCluster[];
  canCreate: boolean; hint?: string;
};
/** Eligible clusters for a school's geography (only ones covering its sub-county). */
export function fetchEligibleClusters(user: BackendUser, schoolId: string) {
  return live<BeClusterEligibility>(`/clusters/eligible-for-school/${encodeURIComponent(schoolId)}`, user);
}
/** Create a cluster (standard form: district + sub-counties + name + leader). */
export function backendCreateCluster(
  user: BackendUser,
  body: { name: string; regionId: string; districtId: string; subCountyIds: string[]; clusterLeaderName?: string; clusterLeaderPhone?: string; overrideReason?: string },
) {
  return live<BeCluster>(`/clusters`, user, { method: "POST", body: JSON.stringify(body) });
}
/** Assign a school to a cluster (backend enforces sub-county eligibility). */
export function backendAssignCluster(user: BackendUser, schoolId: string, clusterId: string, reason?: string) {
  return live<{ ok: boolean; schoolId: string; clusterId: string; planningReadiness: string; stage: string }>(
    `/clusters/assign`, user, { method: "POST", body: JSON.stringify({ schoolId, clusterId, reason }) },
  );
}
/** Create a cluster from a school (derives geography + auto-assigns the school). */
export function backendCreateClusterFromSchool(user: BackendUser, body: { schoolId: string; name: string; overrideReason?: string }) {
  return live<{ cluster: BeCluster; assignment: unknown }>(`/clusters/from-school`, user, { method: "POST", body: JSON.stringify(body) });
}

// ── Geography (regions → districts → sub-counties), for the cluster form ──
export type BeRegion = { id: string; name: string; code?: string | null };
export type BeDistrict = { id: string; name: string; regionId: string };
export type BeSubCounty = { id: string; name: string; districtId: string };
export function fetchRegions(user: BackendUser) {
  return live<BeRegion[]>(`/geography/regions`, user);
}
export function fetchDistricts(user: BackendUser, regionId?: string) {
  return live<BeDistrict[]>(`/geography/districts${regionId ? `?regionId=${encodeURIComponent(regionId)}` : ""}`, user);
}
export function fetchSubCounties(user: BackendUser, districtId: string) {
  return live<BeSubCounty[]>(`/geography/sub-counties?districtId=${encodeURIComponent(districtId)}`, user);
}
export type BeClusterSchool = {
  schoolId: string; name: string; schoolType: string; subCounty?: string | null;
  phone?: string | null; primaryContact?: string | null;
  accountOwner?: string | null; ssaStatus: string; planningReadiness: string;
  latestSsa: number | null; stage: string;
  weakestIntervention?: { area: string; score: number } | null;
};
export type BeClusterPlanning = {
  id: string; clusterName: string; district: string; subCounty: string;
  schoolsCount: number; schoolsWithSsa: number;
  sit: string; firstMeeting: string; secondMeeting: string; thirdMeeting: string;
  gapCategory: "no_sit" | "no_first_meeting" | "no_second_meeting" | "no_third_meeting";
};
export function fetchClusterPlanning(user: BackendUser) {
  return live<BeClusterPlanning[]>(`/clusters/planning`, user);
}
export function fetchClusters(user: BackendUser) {
  return live<BeCluster[]>(`/clusters`, user);
}
export function fetchClusterSchools(user: BackendUser, clusterId: string) {
  return live<{
    cluster: { id: string; name: string; status: string; type: string };
    count: number;
    commonWeakIntervention?: { area: string; avgScore: number } | null;
    schools: BeClusterSchool[];
  }>(
    `/clusters/${encodeURIComponent(clusterId)}/schools`, user,
  );
}

// ── Monthly plan lifecycle (backend writes + reads) ─────────────────
export type BePlanActivity = {
  kind: string; title: string; weekOfMonth?: number; scheduledDate?: string | null;
  schoolId?: string | null; estCostCents?: number; interventionArea?: string | null;
  deliveryType?: string | null; partnerName?: string | null;
};
export type BeMonthlyPlan = {
  id: string; monthIso: string; ownerStaffId: string; ownerName?: string | null;
  status: string; totalCostCents: number; activityCount?: number;
  submittedAt?: string | null; approvedAt?: string | null; returnedReason?: string | null;
  activities?: (BePlanActivity & { id: string })[];
};
export function fetchPlans(user: BackendUser) {
  return live<BeMonthlyPlan[]>(`/planning/plans`, user);
}
export function fetchPlan(user: BackendUser, id: string) {
  return live<BeMonthlyPlan>(`/planning/plans/${encodeURIComponent(id)}`, user);
}
export function backendCreatePlan(user: BackendUser, body: { monthIso: string; activities?: BePlanActivity[] }) {
  return live<BeMonthlyPlan>(`/planning/plans`, user, { method: "POST", body: JSON.stringify(body) });
}
export function backendAddPlanActivity(user: BackendUser, planId: string, body: BePlanActivity) {
  return live<{ id: string }>(`/planning/plans/${encodeURIComponent(planId)}/activities`, user, { method: "POST", body: JSON.stringify(body) });
}
export function backendPlanAction(user: BackendUser, planId: string, action: "submit" | "approve" | "return", body?: Record<string, unknown>) {
  return live<BeMonthlyPlan>(`/planning/plans/${encodeURIComponent(planId)}/${action}`, user, { method: "POST", body: JSON.stringify(body ?? {}) });
}

// ── Data intake (Add School + Upload SSA) — backend writes ──────────
export function backendCreateSchool(user: BackendUser, body: {
  schoolId: string; name: string; regionId: string; districtId: string;
  subCountyId?: string; parishId?: string; shippingAddress?: string;
  schoolPhone?: string; primaryContactName?: string; primaryContactPhone?: string;
  enrollment?: number; accountOwnerName?: string; schoolType?: string;
}) {
  return live<{ id: string; schoolId: string }>(`/schools`, user, { method: "POST", body: JSON.stringify(body) });
}
/** Change a school's type (Client → Core → Champion). Moves it on/off the core dashboard. */
export function backendSetSchoolType(user: BackendUser, schoolId: string, schoolType: string) {
  return live<{ schoolId: string; name: string; schoolType: string }>(`/schools/${encodeURIComponent(schoolId)}/type`, user, { method: "POST", body: JSON.stringify({ schoolType }) });
}
export type BeSchoolProposal = { schoolId: string; name: string; district: string | null; schoolType: string; latestSsa: number | null };
/** Best-SSA client schools → potential Core; best-SSA core schools → potential Champion. */
export function fetchSchoolProposals(user: BackendUser) {
  return live<{ potentialCore: BeSchoolProposal[]; potentialChampion: BeSchoolProposal[] }>(`/schools/proposals`, user);
}
export function backendUploadSsa(user: BackendUser, body: {
  schoolId: string; dateOfSsa: string; newEnrollment?: number;
  scores: { intervention: string; score: number }[];
}) {
  return live<{ id: string; averageScore?: number }>(`/ssa`, user, { method: "POST", body: JSON.stringify(body) });
}

// ── Partners (for assignment pickers — real backend partner IDs) ────
export type BePartner = {
  id: string; name: string; isCertified: boolean;
  certificationStatus?: string | null; activeStatus?: boolean | null;
  regionName?: string | null; expertiseAreas?: string[] | null;
};
/** Active partners the caller may assign work to (real assignedPartnerId values). */
export function fetchPartners(user: BackendUser, activeOnly = true) {
  return live<BePartner[]>(`/partners${activeOnly ? "?activeOnly=true" : ""}`, user);
}

// ── Notifications (backend-backed; no mock) ─────────────────────────
export type BeNotification = {
  id: string; title: string; body?: string | null; contextType?: string | null; contextId?: string | null;
  targetRoute?: string | null; actionRequired: boolean; priority: "low" | "normal" | "high" | "urgent";
  status: "unread" | "read" | "archived"; createdAt: string;
};
export function fetchNotificationsRecent(user: BackendUser) {
  return live<BeNotification[]>(`/notifications/recent`, user);
}
export function fetchNotificationCounts(user: BackendUser) {
  return live<{ unread: number; actionRequired: number }>(`/notifications/counts`, user);
}
export function markNotificationReadBE(user: BackendUser, id: string) {
  return live<{ status: string }>(`/notifications/${encodeURIComponent(id)}/read`, user, { method: "PATCH" });
}
export function resolveNotificationBE(user: BackendUser, id: string) {
  return live<{ status: string }>(`/notifications/${encodeURIComponent(id)}/resolve`, user, { method: "PATCH" });
}
export function markAllNotificationsReadBE(user: BackendUser) {
  return live<{ updated: number }>(`/notifications/mark-all-read`, user, { method: "PATCH" });
}

export type BeMergeResult = { merged: BeDebrief; partnerDebriefId: string; routedTo: number };
/** CCEO reviews + merges a partner debrief into their daily debrief; routes up. */
export function mergePartnerDebrief(user: BackendUser, body: { partnerDebriefId: string; cceoDebriefId?: string; note?: string }) {
  return live<BeMergeResult>(`/debriefs/merge-partner-debrief`, user, { method: "POST", body: JSON.stringify(body) });
}

export function fetchRecruitmentRecommendation(user: BackendUser, params: { fy?: string; districtId?: string } = {}) {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) q.set(k, v);
  const s = q.toString();
  return live<BeRecruitment>(`/analytics/recruitment-recommendation${s ? `?${s}` : ""}`, user);
}

// ── Reports (generated, persisted program summaries) ────────────────
export type BeReportRow = { id: string; title: string; type: string; fy: string; scope: string; createdAt: string };
export type BeReport = BeReportRow & { summaryJson: Record<string, unknown>; createdByUserId?: string | null };
/** List previously generated reports (newest first). */
export function fetchReports(user: BackendUser) {
  return live<BeReportRow[]>(`/reports`, user);
}
export function fetchReport(user: BackendUser, id: string) {
  return live<BeReport>(`/reports/${encodeURIComponent(id)}`, user);
}
/** Generate + persist a report from live program data. */
export function generateReport(user: BackendUser, type: string, fy = "2026") {
  return live<BeReport>(`/reports/generate`, user, { method: "POST", body: JSON.stringify({ type, fy }) });
}

// ── HR (staff roster + leave workflow) ──────────────────────────────
export type BeRosterRow = {
  staffProfileId: string; name: string; email: string; role: string;
  onboardingState: string; active: boolean; primaryDistrict: string | null;
  schools: number; supervisees: number;
};
export type BeRoster = { counts: { total: number; active: number; pending: number }; staff: BeRosterRow[] };
export function fetchHrRoster(user: BackendUser) {
  return live<BeRoster>(`/hr/roster`, user);
}
export type BeLeaveRow = {
  id: string; staffName: string; type: string; startDate: string; endDate: string;
  days: number; status: string; reason: string | null; createdAt: string;
};
/** HR/CD see all leave; a staffer sees their own. */
export function fetchLeave(user: BackendUser) {
  return live<BeLeaveRow[]>(`/hr/leave`, user);
}
export function requestLeave(user: BackendUser, body: { type?: string; startDate: string; endDate: string; days?: number; reason?: string }) {
  return live<{ id: string; status: string }>(`/hr/leave`, user, { method: "POST", body: JSON.stringify(body) });
}
export function reviewLeave(user: BackendUser, id: string, action: "approve" | "reject") {
  return live<{ id: string; status: string }>(`/hr/leave/${encodeURIComponent(id)}/${action}`, user, { method: "POST" });
}
export type BeLeaveCalendarRow = {
  id: string; staffName: string; staffProfileId: string; type: string;
  startDate: string; endDate: string; dates: string[];
};
/** Approved leave shaped for the calendar + planning-availability engine
 *  (HR/CD see the team; a staffer sees their own). */
export function fetchApprovedLeave(user: BackendUser, range?: { from?: string; to?: string }) {
  const q = new URLSearchParams();
  if (range?.from) q.set("from", range.from);
  if (range?.to) q.set("to", range.to);
  const s = q.toString();
  return live<BeLeaveCalendarRow[]>(`/hr/leave/calendar${s ? `?${s}` : ""}`, user);
}

// ── Partner round-trip (a field officer's own scoped session) ───────
export type BeMyPartnerActivity = {
  id: string; activityType: string; schoolName: string | null; district: string | null;
  status: string; evidenceStatus: string; scheduledDate: string | null; fy: string; deliveryType: string;
};
export type BeMyPartner = {
  partner: BePartner;
  counts: { total: number; open: number; awaitingEvidence: number; scheduled: number };
  activities: BeMyPartnerActivity[];
};
/** The partner org the caller logs in as. */
export function fetchMyPartner(user: BackendUser) {
  return live<BePartner>(`/partners/me`, user);
}
/** Activities assigned to the caller's partner — the round-tripped work queue. */
export function fetchMyPartnerActivities(user: BackendUser) {
  return live<BeMyPartner>(`/partners/me/activities`, user);
}

// ── Budget Intelligence & Financial Decision Engine ─────────────────
export type BeBudgetInsight = {
  id: string;
  fy: string;
  insightType: string;
  scopeType: string;
  scopeId?: string | null;
  scopeName?: string | null;
  recommendation: string;
  reason: string;
  riskLevel: string;
  impactYield: string;
  confidenceLevel: string;
  confidenceScore: number;
  amountAffected?: number | null;
  financialImplication?: string | null;
  suggestedAction: string;
  alternatives: string[];
  metrics: Record<string, unknown>;
  riskFlags: string[];
  evidenceSummary?: { metricName: string; metricValue: string; tone?: string }[] | null;
  status: string;
};
export type BeBudgetBoards = { fy: string; insights: BeBudgetInsight[] };
export type BeBudgetSnapshot = {
  fy: string;
  totalInsights: number;
  lowYieldCount: number;
  highYieldCount: number;
  amountAtRisk: number;
  headline: string;
};

export function fetchBudgetIntelligenceBoards(
  user: BackendUser,
  q: { fy?: string; insightType?: string; impactYield?: string } = {},
) {
  const sp = new URLSearchParams();
  if (q.fy) sp.set("fy", q.fy);
  if (q.insightType) sp.set("insightType", q.insightType);
  if (q.impactYield) sp.set("impactYield", q.impactYield);
  const qs = sp.toString();
  return live<BeBudgetBoards>(`/budget-intelligence${qs ? `?${qs}` : ""}`, user);
}
export function fetchBudgetIntelligenceSnapshot(user: BackendUser, fy?: string) {
  return live<BeBudgetSnapshot>(`/budget-intelligence/snapshot${fy ? `?fy=${encodeURIComponent(fy)}` : ""}`, user);
}

// ── CD → PL flags ───────────────────────────────────────────────────
export type BeCdFlag = {
  id: string; raisedByUserId: string; raisedByName?: string | null; assignedToUserId: string;
  category: string; scopeType?: string | null; scopeId?: string | null; scopeName?: string | null;
  note: string; recommendedAction?: string | null; priority: string; dueDate?: string | null;
  status: string; resolutionNote?: string | null; resolvedAt?: string | null; createdAt: string;
};
export function fetchFlags(user: BackendUser, status?: string) {
  return live<{ flags: BeCdFlag[]; count: number; openCount: number }>(`/flags${status ? `?status=${encodeURIComponent(status)}` : ""}`, user);
}
export function fetchProgramLeads(user: BackendUser) {
  return live<{ programLeads: { id: string; name: string }[] }>(`/flags/program-leads`, user);
}
export function backendRaiseFlag(user: BackendUser, body: Record<string, unknown>) {
  return live<BeCdFlag>(`/flags`, user, { method: "POST", body: JSON.stringify(body) });
}
export function backendUpdateFlag(user: BackendUser, id: string, body: { action: string; note?: string }) {
  return live<BeCdFlag>(`/flags/${encodeURIComponent(id)}`, user, { method: "PATCH", body: JSON.stringify(body) });
}

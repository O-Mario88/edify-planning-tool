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
  currentFySsaStatus: string;
  planningReadiness: string;
  accountOwnerStatus: string;
  accountOwnerNameRaw?: string | null;
  district?: { name: string } | null;
  cluster?: { name: string } | null;
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

type SchoolQuery = {
  schoolType?: string;
  pageSize?: number;
  search?: string;
  districtId?: string;
  clusterStatus?: string;
  ssaStatus?: string;
  planningReadiness?: string;
};

export function fetchSchools(user: BackendUser, q: SchoolQuery = {}) {
  const params = new URLSearchParams();
  if (q.schoolType) params.set("schoolType", q.schoolType);
  params.set("pageSize", String(q.pageSize ?? 200));
  if (q.search) params.set("search", q.search);
  if (q.districtId) params.set("districtId", q.districtId);
  if (q.clusterStatus) params.set("clusterStatus", q.clusterStatus);
  if (q.ssaStatus) params.set("ssaStatus", q.ssaStatus);
  if (q.planningReadiness) params.set("planningReadiness", q.planningReadiness);
  return live<BePaginated<BeSchoolRow>>(`/schools?${params.toString()}`, user);
}

export function fetchCoreHeader(user: BackendUser) {
  return live<BeCoreHeader>("/filters/core-header-summary", user);
}

export function fetchAnalyticsDashboard(user: BackendUser) {
  return live<BeDashboard>("/analytics/dashboard", user);
}

export function fetchAnalyticsSsa(user: BackendUser) {
  return live<BeSsaPerformance>("/analytics/ssa-performance", user);
}

export function fetchActivityPipeline(user: BackendUser) {
  return live<BeActivityPipeline>("/analytics/activity-pipeline", user);
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

type ContributionParams = { lens?: ContributionLens; fy?: string; quarter?: string; districtId?: string; clusterId?: string };

function contributionQuery(p: ContributionParams): string {
  const params = new URLSearchParams();
  params.set("lens", p.lens ?? "own");
  if (p.fy) params.set("fy", p.fy);
  if (p.quarter) params.set("quarter", p.quarter);
  if (p.districtId) params.set("districtId", p.districtId);
  if (p.clusterId) params.set("clusterId", p.clusterId);
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

// ── My Plan (activities) — the write-path migration surface ─────────

export type BeActivity = {
  id: string;
  schoolId?: string | null;
  activityType: string;
  status: string;
  deliveryType: string;
  scheduledDate?: string | null;
  rescheduleCount?: number | null;
  lastReason?: string | null;
  assignedPartnerId?: string | null;
  school?: { schoolId: string; name: string } | null;
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

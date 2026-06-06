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

async function live<T>(path: string, user: BackendUser): Promise<LiveResult<T>> {
  if (!isBackendEnabled()) return { live: false, error: null };
  const r = await backendFetch<T>(path, user);
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

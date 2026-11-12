/**
 * The School Directory's answer (SchoolDirectoryScreenService, read by Go:
 * docs/migration/12-school-directory.md) laid out as the page's generic
 * blocks. Only words that live in the Django templates are written here
 * (templates/pages/schools/index.html, partials/schools/*); every count,
 * label, tone, permission and row comes from the gateway.
 */
import { create } from '@bufbuild/protobuf';

import type { GetSchoolDirectoryResponse } from '@/gen/edify/screens/v1/school_directory_pb';
import {
  PageFiltersSchema,
  PageHeaderSchema,
  PageLinkTabsSchema,
  PagePagerSchema,
} from '@/gen/edify/screens/v1/page_pb';
import type { PageFilters, PageHeader, PageLinkTabs, PagePager } from '@/gen/edify/screens/v1/page_pb';

import { elidedPageNumbers, hrefWith, showingSummary } from './pager';

export const DIRECTORY_PATH = '/schools';

/** The page's own query parameters (GetSchoolDirectoryRequest). */
export const DIRECTORY_KEYS = [
  'q', 'fy', 'district', 'sub_county', 'school_type', 'cluster_status', 'project_status', 'gap', 'tab', 'page',
] as const;
type DirectoryKey = (typeof DIRECTORY_KEYS)[number];
export type DirectoryQuery = Partial<Record<DirectoryKey, string>>;

const MAX_QUERY_VALUE = 200;

/** The request's query, keeping only the page's own keys. */
export function directoryQuery(searchParams: Readonly<Record<string, string | string[] | undefined>>): DirectoryQuery {
  const query: DirectoryQuery = {};
  for (const key of DIRECTORY_KEYS) {
    const raw = searchParams[key];
    const value = (Array.isArray(raw) ? raw[0] : raw)?.trim().slice(0, MAX_QUERY_VALUE);
    if (value) query[key] = value;
  }
  return query;
}

export function directoryRequest(query: DirectoryQuery) {
  const page = Number.parseInt(query.page ?? '', 10);
  return {
    q: query.q ?? '',
    fy: query.fy ?? '',
    district: query.district ?? '',
    subCounty: query.sub_county ?? '',
    schoolType: query.school_type ?? '',
    clusterStatus: query.cluster_status ?? '',
    projectStatus: query.project_status ?? '',
    gap: query.gap ?? '',
    tab: query.tab ?? '',
    page: Number.isFinite(page) && page > 0 ? page : 0,
  };
}

export function directoryHeader(answer: GetSchoolDirectoryResponse): PageHeader {
  const actions = [];
  if (answer.canAddSchool) {
    actions.push({ key: 'add_school', label: 'Add School', primary: true, enabled: true, drawer: true });
  }
  actions.push({ key: 'export', label: 'Export', enabled: true });
  return create(PageHeaderSchema, {
    eyebrow: 'Schools & Field',
    title: 'School Directory',
    description: answer.readOnly
      ? "Your region's schools by Programme Lead: ownership, clustering, SSA readiness and planning status. Read-only."
      : 'Manage uploaded schools, ownership, clustering, SSA readiness, and planning status.',
    actions,
  });
}

const ALL = { value: '', label: 'All' };

export function directoryFilters(answer: GetSchoolDirectoryResponse, query: DirectoryQuery): PageFilters {
  const f = answer.filters;
  const options = (list: { value: string; label: string }[] | undefined) => (list ?? []).map(({ value, label }) => ({ value, label }));
  const district = f?.district ?? '';
  return create(PageFiltersSchema, {
    filters: [
      { name: 'fy', label: 'Fiscal year', value: f?.fy ?? '', options: options(f?.fyOptions) },
      { name: 'district', label: 'District', value: district, options: [ALL, ...options(f?.districts)] },
      {
        name: 'sub_county',
        label: 'Sub-county',
        value: f?.subCounty ?? '',
        options: [{ value: '', label: district ? 'All in district' : 'Choose district first' }, ...options(f?.subCounties)],
      },
      { name: 'school_type', label: 'Partner type', value: f?.schoolType ?? '', options: [ALL, ...options(f?.schoolTypes)] },
      { name: 'cluster_status', label: 'Cluster status', value: f?.clusterStatus ?? '', options: [ALL, ...options(f?.clusterStatuses)] },
      { name: 'gap', label: 'Missing detail', value: f?.gap ?? '', options: [{ value: '', label: 'All schools' }, ...options(f?.gaps)] },
      { name: 'project_status', label: 'Project status', value: f?.projectStatus ?? '', options: [ALL, ...options(f?.projectStatuses)] },
    ],
    hidden: { tab: answer.activeTab || 'all', ...(query.q ? { q: query.q } : {}) },
  });
}

/** Filters whose select is unusable until another is chosen. */
export function disabledFilters(filters: PageFilters): string[] {
  const district = filters.filters.find((filter) => filter.name === 'district');
  return district?.value ? [] : ['sub_county'];
}

export function directoryTabs(answer: GetSchoolDirectoryResponse, query: DirectoryQuery): PageLinkTabs & { counts: number[] } {
  const base = { ...query } as Record<string, string>;
  delete base.page;
  const tabs = create(PageLinkTabsSchema, {
    label: 'School directory views',
    scrolls: true,
    tabs: answer.tabs.map((tab) => ({
      label: tab.label,
      href: hrefWith(DIRECTORY_PATH, base, { tab: tab.key === 'all' ? '' : tab.key }),
      active: tab.key === (answer.activeTab || 'all'),
    })),
  });
  return Object.assign(tabs, { counts: answer.tabs.map((tab) => tab.count) });
}

export function directoryTotal(answer: GetSchoolDirectoryResponse): number {
  return Number(answer.page?.total ?? 0n);
}

/** The pager under the list; absent when everything fits on one page. */
export function directoryPager(answer: GetSchoolDirectoryResponse, query: DirectoryQuery): PagePager | undefined {
  const info = answer.page;
  if (!info || info.totalPages <= 1) return undefined;
  const total = directoryTotal(answer);
  return create(PagePagerSchema, {
    summary: showingSummary(info.page, info.pageSize, total, 'schools'),
    pages: elidedPageNumbers(info.page, info.totalPages).map((number) =>
      number === null
        ? { label: '…' }
        : { label: String(number), href: hrefWith(DIRECTORY_PATH, query as Record<string, string>, { page: String(number) }), current: number === info.page },
    ),
  });
}

/** Why the list is empty (partials/schools/table.html). */
export function emptyMessage(answer: GetSchoolDirectoryResponse, query: DirectoryQuery): string {
  const filtered = Object.keys(query).length > 0;
  if (answer.emptyState === 'no_matches' || (!answer.emptyState && filtered)) return 'No schools match these filters.';
  if (answer.emptyState === 'scope_empty') return 'No schools are assigned to you yet.';
  return 'No schools uploaded yet.';
}

export function schoolsListed(total: number): string {
  return `${total} school${total === 1 ? '' : 's'} listed`;
}

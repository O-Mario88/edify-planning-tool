import { create } from '@bufbuild/protobuf';
import type { MessageInitShape } from '@bufbuild/protobuf';
import { describe, expect, it } from 'vitest';

import { GetSchoolDirectoryResponseSchema } from '@/gen/edify/screens/v1/school_directory_pb';

import {
  directoryFilters,
  directoryHeader,
  directoryPager,
  directoryQuery,
  directoryRequest,
  directoryTabs,
  disabledFilters,
  emptyMessage,
  schoolsListed,
} from './schoolDirectory';

const answer = (overrides: Omit<MessageInitShape<typeof GetSchoolDirectoryResponseSchema>, '$typeName'> = {}) =>
  create(GetSchoolDirectoryResponseSchema, {
    tabs: [
      { key: 'all', label: 'All Schools', count: 699 },
      { key: 'unclustered', label: 'Unclustered', count: 606 },
    ],
    activeTab: 'all',
    filters: { fy: '2027', fyOptions: [{ value: '2027', label: 'FY 2027' }], gaps: [{ value: 'any', label: 'Any Missing Detail (3)' }] },
    page: { page: 1, pageSize: 50, total: 699n, totalPages: 14 },
    canAddSchool: true,
    ...overrides,
  });

describe('directoryQuery and directoryRequest', () => {
  it('keeps only the page’s own keys, trimmed and bounded', () => {
    const query = directoryQuery({ q: '  kasawo ', tab: ['clustered', 'x'], evil: '1', page: '3', gap: '' });
    expect(query).toEqual({ q: 'kasawo', tab: 'clustered', page: '3' });
    expect(directoryRequest(query)).toMatchObject({ q: 'kasawo', tab: 'clustered', page: 3, subCounty: '' });
  });

  it('asks for the default page when the page is not a number', () => {
    expect(directoryRequest({ page: 'abc' }).page).toBe(0);
    expect(directoryRequest({ page: '-2' }).page).toBe(0);
  });
});

describe('directoryHeader', () => {
  it('offers Add School only when the gateway says so, as the primary', () => {
    expect(directoryHeader(answer()).actions.map((a) => [a.label, a.primary])).toEqual([
      ['Add School', true],
      ['Export', false],
    ]);
    expect(directoryHeader(answer({ canAddSchool: false })).actions.map((a) => a.label)).toEqual(['Export']);
  });

  it('says read only for a regional reader', () => {
    expect(directoryHeader(answer({ readOnly: true })).description).toMatch(/Read-only\.$/);
  });
});

describe('directoryFilters', () => {
  it('lays the filters out in the page’s order with its words', () => {
    const filters = directoryFilters(answer(), { q: 'x' });
    expect(filters.filters.map((f) => f.label)).toEqual([
      'Fiscal year', 'District', 'Sub-county', 'Partner type', 'Cluster status', 'Missing detail', 'Project status',
    ]);
    expect(filters.filters[5]?.options.map((o) => o.label)).toEqual(['All schools', 'Any Missing Detail (3)']);
    expect(filters.hidden).toEqual({ tab: 'all', q: 'x' });
    expect(disabledFilters(filters)).toEqual(['sub_county']);
  });
});

describe('directoryTabs and directoryPager', () => {
  it('links each tab back to page one with the filters kept', () => {
    const tabs = directoryTabs(answer(), { fy: '2027', page: '3' });
    expect(tabs.tabs.map((t) => [t.href, t.active])).toEqual([
      ['/schools?fy=2027', true],
      ['/schools?fy=2027&tab=unclustered', false],
    ]);
    expect(tabs.counts).toEqual([699, 606]);
  });

  it('draws the pager only when there is more than one page', () => {
    const pager = directoryPager(answer(), { tab: 'unclustered' });
    expect(pager?.summary).toBe('Showing 1 to 50 of 699 schools');
    expect(pager?.pages.map((p) => p.label)).toEqual(['1', '2', '…', '14']);
    expect(pager?.pages[1]?.href).toBe('/schools?tab=unclustered&page=2');
    expect(directoryPager(answer({ page: { page: 1, pageSize: 50, total: 3n, totalPages: 1 } }), {})).toBeUndefined();
  });
});

describe('empty states and counts', () => {
  it('words why the list is empty', () => {
    expect(emptyMessage(answer({ emptyState: 'scope_empty' }), {})).toBe('No schools are assigned to you yet.');
    expect(emptyMessage(answer({ emptyState: 'registry_empty' }), {})).toBe('No schools uploaded yet.');
    expect(emptyMessage(answer({ emptyState: '' }), { q: 'zzz' })).toBe('No schools match these filters.');
  });

  it('counts schools listed as the page does', () => {
    expect(schoolsListed(1)).toBe('1 school listed');
    expect(schoolsListed(699)).toBe('699 schools listed');
  });
});

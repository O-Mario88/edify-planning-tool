/**
 * Desktop sidebar active-item resolution: strictly at most one visible item
 * receives the active class and aria-current="page" on every route.
 */
import { create } from '@bufbuild/protobuf';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

import { NavItemSchema, NavSectionSchema } from '@/gen/edify/screens/v1/navigation_pb';
import type { NavSection } from '@/gen/edify/screens/v1/navigation_pb';

import { SidebarNav, resolveActiveNavKey } from './Sidebar';

const pathnameMock = vi.fn<() => string | null>(() => null);

vi.mock('next/navigation', () => ({
  usePathname: () => pathnameMock(),
}));

function makeSection(label: string, items: Array<{ label: string; url: string; pageKey?: string }>): NavSection {
  return create(NavSectionSchema, {
    label,
    items: items.map((item) => create(NavItemSchema, { label: item.label, url: item.url, pageKey: item.pageKey ?? '', iconSvg: '' })),
  });
}

const CCEO_SECTIONS: NavSection[] = [
  makeSection('DAILY', [
    { label: 'Dashboard', url: '/dashboard', pageKey: 'dashboard' },
    { label: 'Planning', url: '/planning', pageKey: 'planning' },
    { label: 'My Plan', url: '/my-plan', pageKey: 'my_plan' },
    { label: 'Smart Route Planner', url: '/my-plan/smart-route', pageKey: 'smart_route_planner' },
    { label: 'School Directory', url: '/schools', pageKey: 'school_directory' },
    { label: 'Clusters', url: '/clusters', pageKey: 'clusters' },
    { label: 'My Actions', url: '/actions/mine', pageKey: 'my_actions' },
  ]),
  makeSection('OVERSIGHT', [
    { label: 'Cluster Oversight', url: '/cluster-oversight/', pageKey: 'cluster_oversight' },
  ]),
  makeSection('REFERENCE', [
    { label: 'Closed Schools', url: '/schools/closed', pageKey: 'closed_schools' },
  ]),
];

const PC_SECTIONS: NavSection[] = [
  makeSection('DAILY', [
    { label: 'Dashboard', url: '/dashboard', pageKey: 'dashboard' },
    { label: 'Projects', url: '/projects', pageKey: 'projects' },
    { label: 'My Plan', url: '/projects/my-plan', pageKey: 'my_plan' },
    { label: 'Planning', url: '/projects/planning', pageKey: 'planning' },
    { label: 'School Directory', url: '/schools', pageKey: 'school_directory' },
  ]),
];

function activeHrefs(sections: NavSection[], path: string): { ariaCurrent: string[]; activeClass: string[] } {
  pathnameMock.mockReturnValue(path);
  const html = renderToStaticMarkup(<SidebarNav sections={sections} path={path} />);
  const links = [...html.matchAll(/<a\b[^>]*>/g)].map((m) => m[0]);
  const ariaCurrent = links
    .filter((tag) => tag.includes('aria-current="page"'))
    .map((tag) => /href="([^"]+)"/.exec(tag)?.[1] ?? '');
  const activeClass = links
    .filter((tag) => tag.includes('app-sidebar__item--active'))
    .map((tag) => /href="([^"]+)"/.exec(tag)?.[1] ?? '');
  return { ariaCurrent, activeClass };
}

describe('desktop sidebar single-winner active state', () => {
  it('highlights ONLY Smart Route Planner on /my-plan/smart-route (and variants), never My Plan', () => {
    for (const path of ['/my-plan/smart-route', '/my-plan/smart-route/', '/my-plan/smart-route?date=2026-11-22']) {
      const got = activeHrefs(CCEO_SECTIONS, path);
      expect(got.ariaCurrent).toEqual(['/my-plan/smart-route']);
      expect(got.activeClass).toEqual(['/my-plan/smart-route']);
    }
  });

  it('highlights ONLY My Plan on /my-plan and its non-sibling children', () => {
    for (const path of ['/my-plan', '/my-plan/', '/my-plan/other']) {
      const got = activeHrefs(CCEO_SECTIONS, path);
      expect(got.ariaCurrent).toEqual(['/my-plan']);
      expect(got.activeClass).toEqual(['/my-plan']);
    }
  });

  it('prefers Closed Schools over School Directory on /schools/closed, while school profiles keep School Directory active', () => {
    expect(activeHrefs(CCEO_SECTIONS, '/schools/closed').ariaCurrent).toEqual(['/schools/closed']);
    expect(activeHrefs(CCEO_SECTIONS, '/schools/SCH-001').ariaCurrent).toEqual(['/schools']);
    expect(activeHrefs(CCEO_SECTIONS, '/schools').ariaCurrent).toEqual(['/schools']);
  });

  it('handles trailing slashes and child sections under Cluster Oversight', () => {
    expect(activeHrefs(CCEO_SECTIONS, '/cluster-oversight').ariaCurrent).toEqual(['/cluster-oversight']);
    expect(activeHrefs(CCEO_SECTIONS, '/cluster-oversight/meetings?fy=2027').ariaCurrent).toEqual(['/cluster-oversight']);
  });

  it('matches My Actions directly for CCEO and falls back to folded Dashboard for ProjectCoordinator', () => {
    expect(activeHrefs(CCEO_SECTIONS, '/actions/mine').ariaCurrent).toEqual(['/actions/mine']);
    expect(activeHrefs(PC_SECTIONS, '/actions/mine').ariaCurrent).toEqual(['/dashboard']);
    expect(activeHrefs(PC_SECTIONS, '/projects/planning').ariaCurrent).toEqual(['/projects/planning']);
  });

  it('never matches partial path segments like /my-planner against /my-plan', () => {
    expect(
      resolveActiveNavKey(
        [
          { key: 'plan', url: '/my-plan' },
          { key: 'route', url: '/my-plan/smart-route' },
        ],
        '/my-planner',
      ),
    ).toBeNull();
  });
});

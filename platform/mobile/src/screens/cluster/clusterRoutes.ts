/**
 * The Cluster Leader Portal's own routes and tabs (brief A3). A Cluster
 * Leader has no web menu: their reach is the clusters assigned to them,
 * decided by the gateway, so the app draws a portal of its own — Home,
 * member Schools and Activities — under the usual Edify frame.
 */
import { create } from '@bufbuild/protobuf';

import type { NavItem, NavSection } from '../../gen/edify/screens/v1/navigation_pb';
import { NavItemSchema, NavSectionSchema } from '../../gen/edify/screens/v1/navigation_pb';

/** The portal's pages: three tabs, and the work pages behind Home and More. */
export type ClusterTab = 'home' | 'schools' | 'activities' | 'share' | 'plans' | 'actions' | 'requests' | 'report';

export const CLUSTER_TABS: Readonly<Record<ClusterTab, string>> = {
  home: 'cluster:home',
  schools: 'cluster:schools',
  activities: 'cluster:activities',
  share: 'cluster:share',
  plans: 'cluster:plans',
  actions: 'cluster:actions',
  requests: 'cluster:requests',
  report: 'cluster:report',
};

/** The leader's work pages, under their More menu. */
export function clusterWorkSection(): NavSection {
  const item = (label: string, tab: ClusterTab) => create(NavItemSchema, { label, url: CLUSTER_TABS[tab], native: true });
  return create(NavSectionSchema, {
    label: 'Cluster work',
    items: [
      item('Meeting plans', 'plans'),
      item('Action items', 'actions'),
      item('Requests to staff', 'requests'),
      item('Cluster report', 'report'),
    ],
  });
}

// The icons are Lucide's, drawn like the web's own (stroke, currentColor).
const svg = (body: string) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;

const HOME_ICON = svg(
  '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
);
const SCHOOLS_ICON = svg(
  '<path d="M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z"/><path d="M6 12H4a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2h2"/><path d="M18 9h2a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2"/><path d="M10 6h4"/><path d="M10 10h4"/><path d="M10 14h4"/><path d="M10 18h4"/>',
);
// Lucide "share-2".
const SHARE_ICON = svg(
  '<circle cx="18" cy="5" r="3"/><circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><line x1="8.59" x2="15.42" y1="13.51" y2="17.49"/><line x1="15.41" x2="8.59" y1="6.51" y2="10.49"/>',
);
const ACTIVITIES_ICON = svg(
  '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
);

/** The portal's bottom bar: Home, Schools, Activities, the loan link (More is the shell's). */
export function clusterBottomBar(): NavItem[] {
  return [
    create(NavItemSchema, { label: 'Home', url: CLUSTER_TABS.home, iconSvg: HOME_ICON, native: true }),
    create(NavItemSchema, { label: 'Schools', url: CLUSTER_TABS.schools, iconSvg: SCHOOLS_ICON, native: true }),
    create(NavItemSchema, { label: 'Activities', url: CLUSTER_TABS.activities, iconSvg: ACTIVITIES_ICON, native: true }),
    create(NavItemSchema, { label: 'Loan link', url: CLUSTER_TABS.share, iconSvg: SHARE_ICON, native: true }),
  ];
}

/** The tab a Home count or quick action opens ("schools", "activities?when=upcoming"). */
export function tabOf(href: string): ClusterTab | null {
  const path = href.split(/[?#]/)[0].replace(/^\/+|\/+$/g, '');
  if (path === '') {
    return 'home';
  }
  return path in CLUSTER_TABS ? (path as ClusterTab) : null;
}

/** "activities?when=past" → "past"; upcoming otherwise. */
export function whenOf(href: string): 'upcoming' | 'past' {
  return /[?&]when=past\b/.test(href) ? 'past' : 'upcoming';
}

/** The tab a shell URL is, or null for the shell's own (the menu). */
export function tabOfUrl(url: string): ClusterTab | null {
  const entry = (Object.entries(CLUSTER_TABS) as [ClusterTab, string][]).find(([, value]) => value === url);
  return entry ? entry[0] : null;
}

/** Where staff manage cluster leaders: one section under their own menu. */
export const LEADERS_URL = 'cluster:leaders';

/** The roles that may manage leaders (the gateway decides per cluster). */
const LEADER_ADMINISTRATORS = new Set(['Admin', 'Program Lead', 'CCEO']);

export function canManageLeaders(activeRole: string): boolean {
  return LEADER_ADMINISTRATORS.has(activeRole);
}

export function leadersSection(): NavSection {
  return create(NavSectionSchema, {
    label: 'Cluster leadership',
    items: [create(NavItemSchema, { label: 'Cluster Leaders', url: LEADERS_URL, native: true })],
  });
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "2026-11-15" as a date box's month and day ("NOV", "15"); empty parts for no date. */
export function dateBox(iso: string): { readonly month: string; readonly day: string } {
  const found = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!found) {
    return { month: '', day: '' };
  }
  return { month: MONTHS[Number(found[2]) - 1]?.toUpperCase() ?? '', day: String(Number(found[3])) };
}

/** "2026-11-15" as "15 Nov 2026"; "Date to be set" while unscheduled. */
export function longDate(iso: string): string {
  const found = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!found) {
    return 'Date to be set';
  }
  return `${Number(found[3])} ${MONTHS[Number(found[2]) - 1]} ${found[1]}`;
}

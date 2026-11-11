/**
 * The Cluster Leader Portal's own routes and tabs (brief A3). A Cluster
 * Leader has no web menu: their reach is the clusters assigned to them,
 * decided by the gateway, so the app draws a portal of its own — Home,
 * member Schools and Activities — under the usual Edify frame.
 */
import { create } from '@bufbuild/protobuf';

import type { NavItem, NavSection } from '../../gen/edify/screens/v1/navigation_pb';
import { NavItemSchema, NavSectionSchema } from '../../gen/edify/screens/v1/navigation_pb';

/** The portal's pages: the bottom tabs, and the work pages behind Home and More. */
export type ClusterTab =
  | 'home'
  | 'meetings'
  | 'schools'
  | 'manage'
  | 'progress'
  | 'planMeeting'
  | 'mobilize'
  | 'share'
  | 'actions'
  | 'requests';

export const CLUSTER_TABS: Readonly<Record<ClusterTab, string>> = {
  home: 'cluster:home',
  meetings: 'cluster:meetings',
  schools: 'cluster:schools',
  manage: 'cluster:manage',
  progress: 'cluster:progress',
  planMeeting: 'cluster:plan-meeting',
  mobilize: 'cluster:mobilize',
  share: 'cluster:share',
  actions: 'cluster:actions',
  requests: 'cluster:requests',
};

/** Older names a Home link may still carry, and the page each now is. */
const ALIASES: Readonly<Record<string, ClusterTab>> = { activities: 'meetings', plans: 'meetings', report: 'progress' };

/** The leader's work pages, under their More menu. */
export function clusterWorkSection(): NavSection {
  const item = (label: string, tab: ClusterTab) => create(NavItemSchema, { label, url: CLUSTER_TABS[tab], native: true });
  return create(NavSectionSchema, {
    label: 'Cluster work',
    items: [
      item('Action & follow-up', 'actions'),
      item('Requests to staff', 'requests'),
      item('Progress & Reports', 'progress'),
      item('Manage cluster', 'manage'),
      item('Share loan application', 'share'),
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
const ACTIVITIES_ICON = svg(
  '<path d="M8 2v4"/><path d="M16 2v4"/><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M3 10h18"/>',
);

/** The portal's bottom bar: Home, Meetings, Schools (More is the shell's). */
export function clusterBottomBar(): NavItem[] {
  return [
    create(NavItemSchema, { label: 'Home', url: CLUSTER_TABS.home, iconSvg: HOME_ICON, native: true }),
    create(NavItemSchema, { label: 'Meetings', url: CLUSTER_TABS.meetings, iconSvg: ACTIVITIES_ICON, native: true }),
    create(NavItemSchema, { label: 'Schools', url: CLUSTER_TABS.schools, iconSvg: SCHOOLS_ICON, native: true }),
  ];
}

/** The tab a Home count or quick action opens ("schools", "activities?when=upcoming"). */
export function tabOf(href: string): ClusterTab | null {
  const path = href.split(/[?#]/)[0].replace(/^\/+|\/+$/g, '');
  if (path === '') {
    return 'home';
  }
  if (path in ALIASES) {
    return ALIASES[path];
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

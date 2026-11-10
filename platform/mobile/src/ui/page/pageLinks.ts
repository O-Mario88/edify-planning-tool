/**
 * Where a page's links lead and which of its link tabs a phone shows. Pure,
 * so it is tested without a device.
 */
import type { PageLinkTab } from '../../gen/edify/screens/v1/page_pb';

const MY_PLAN = '/my-plan';

/** The tabs a phone's rail shows: the first, and the open one (or the second). */
export function railTabs(tabs: readonly PageLinkTab[]): { shown: PageLinkTab[]; rest: PageLinkTab[] } {
  const open = tabs.findIndex((tab) => tab.active);
  const keep = new Set([0, open > 0 ? open : 1]);
  return {
    shown: tabs.filter((_, index) => keep.has(index)),
    rest: tabs.filter((_, index) => !keep.has(index)),
  };
}

/** The web page an activity's drawer belongs to: its activity page. */
export function webPageFor(href: string): string {
  const url = new URL(href, 'http://edify.local');
  const activity = /^\/(?:my-plan|activities)\/([^/]+)\/.+$/.exec(url.pathname);
  if (activity && activity[1] !== 'export-drawer') {
    return `${MY_PLAN}/${activity[1]}`;
  }
  if (url.pathname === `${MY_PLAN}/export-drawer` || url.pathname.endsWith('-modal')) {
    url.searchParams.delete('action');
    const query = url.searchParams.toString();
    return query ? `${MY_PLAN}?${query}` : MY_PLAN;
  }
  return url.pathname + url.search;
}


/** Whether a row shows for the page's chips: a chip left on its "all"
 * value, or one naming the row's own key, shows it (the web's x-show
 * `cat === 'all' || cat === '<the row's>'`). */
export function isShownFor(keys: Readonly<Record<string, string>>, chosen: Readonly<Record<string, string>>): boolean {
  return Object.entries(chosen).every(([name, value]) => value === 'all' || value === '' || keys[name] === undefined || keys[name] === value);
}

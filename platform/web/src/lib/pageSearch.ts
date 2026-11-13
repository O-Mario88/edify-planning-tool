/**
 * The top bar's search for the page being drawn: the page's own search where
 * it has one (the Django view's `topbar_search`), otherwise the platform
 * search. Searching keeps the page's filters and starts again at page one.
 */
import type { PageSearch } from '@/components/shell/TopBar';

interface PageSearchSpec {
  readonly placeholder: string;
  readonly label: string;
}

const PAGE_SEARCHES: Readonly<Record<string, PageSearchSpec>> = {
  '/schools': {
    placeholder: 'Search schools, School IDs, districts, sub-counties…',
    label: 'Search schools by name, School ID, district, sub-county, cluster or assigned owner',
  },
  // notifications_page_view's topbar_search.
  '/notifications': { placeholder: 'Search notifications…', label: 'Search notifications' },
};

const PLATFORM_SEARCH: PageSearchSpec = { placeholder: 'Search schools, staff, districts…', label: 'Search' };

export function pageSearch(path: string): PageSearch & { label: string } {
  const url = new URL(path, 'http://web.invalid');
  const spec = PAGE_SEARCHES[url.pathname];
  if (!spec) return { action: '/search', value: '', keep: {}, ...PLATFORM_SEARCH };
  const keep: Record<string, string> = {};
  for (const [key, value] of url.searchParams) {
    if (key !== 'q' && key !== 'page' && value) keep[key] = value;
  }
  return { action: url.pathname, value: url.searchParams.get('q') ?? '', keep, ...spec };
}

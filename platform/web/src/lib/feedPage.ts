/**
 * Pages drawn from PageScreenService.GetPage: the request a page asks with,
 * and where the answer's links lead. Presentation only: every label, figure,
 * tone, row, page and permission is the gateway's answer.
 */
import type { PageAction, PageCell, PageColumn, PageRow } from '@/gen/edify/screens/v1/page_pb';

/** A query value longer than this is not one the pages write. */
const MAX_VALUE_LENGTH = 512;
const MAX_KEYS = 40;

type SearchParams = Readonly<Record<string, string | string[] | undefined>>;

/**
 * The page's query as the gateway takes it: one value a key (the first, as
 * Django's `request.GET.get`), empty values dropped (the gateway drops them
 * too: docs/migration/25 §25.3), bounded.
 */
export function pageQuery(params: SearchParams): Record<string, string> {
  const query: Record<string, string> = {};
  for (const [key, raw] of Object.entries(params)) {
    if (Object.keys(query).length >= MAX_KEYS) break;
    const value = Array.isArray(raw) ? raw[0] : raw;
    if (typeof value !== 'string' || value === '' || key === 'path' || key.length > 64) continue;
    query[key] = value.slice(0, MAX_VALUE_LENGTH);
  }
  return query;
}

export function queryString(query: Readonly<Record<string, string>>): string {
  const text = new URLSearchParams(query).toString();
  return text ? `?${text}` : '';
}

/**
 * An answer's link as a path on this site: the gateway writes the page's own
 * links as a bare query ("?tab=core"), a fragment, or a web path. Anything
 * that is not a path on the same site is refused (empty).
 */
export function resolveHref(pagePath: string, href: string): string {
  const value = href.trim();
  if (!value) return '';
  if (value.startsWith('?')) return `${pagePath}${value}`;
  if (value.startsWith('#')) return value;
  if (!value.startsWith('/') || value.startsWith('//') || value.startsWith('/\\')) return '';
  return value;
}

/**
 * Where a button that opens a drawer leads while drawers are the existing
 * web's: the same page there, with the same query, where the drawer opens.
 */
export function drawerPageHref(existingWebUrl: string, webPath: string, query: Readonly<Record<string, string>>): string {
  return `${existingWebUrl}${webPath}${queryString(query)}`;
}

/** An action's link: its own page here, or the existing web's page for a drawer. */
export function actionHref(action: PageAction, pagePath: string, drawerHref: string): string {
  if (action.drawer) return withDrawer(drawerHref, resolveHref(pagePath, action.href));
  return resolveHref(pagePath, action.href) || drawerHref;
}

/**
 * A drawer action's link: the page it falls back to, carrying the drawer's
 * own path for the drawer host (components/drawer/DrawerHost).
 */
export function withDrawer(pageHref: string, drawerPath: string): string {
  if (!drawerPath.startsWith('/')) return pageHref;
  return `${pageHref.split('#')[0]}#drawer=${encodeURIComponent(drawerPath)}`;
}

/** The drawer a link names, and the existing web's page to fall back to, if that is where the link leads. */
export function drawerFromHash(href: string): { path: string; fallback: string } | null {
  const at = href.indexOf('#drawer=');
  if (at < 0) return null;
  let path = '';
  try {
    path = decodeURIComponent(href.slice(at + '#drawer='.length));
  } catch {
    return null;
  }
  if (!path.startsWith('/') || path.startsWith('//')) return null;
  const page = href.slice(0, at);
  return { path, fallback: /^https?:\/\//.test(page) ? page : '' };
}

/**
 * A row that is a heading between groups (Planning's "By PL & CCEO": one
 * cell, "Program Lead 1 · Paul N. 75 schools") in a table of several columns.
 */
export function isHeadingRow(row: PageRow, columns: readonly PageColumn[]): boolean {
  return columns.length > 1 && row.cells.length === 1 && !row.pickId && row.cells[0]?.actions.length === 0;
}

/** A cell that is the row's buttons and Actions menu. */
export function isActionsCell(cell: PageCell): boolean {
  return cell.actions.length > 0;
}

/** The row's own buttons ("button") and its menu items ("menu", "danger"), apart. */
export function splitActions(actions: readonly PageAction[]): { buttons: PageAction[]; menu: PageAction[] } {
  return {
    buttons: actions.filter((action) => action.key === 'button'),
    menu: actions.filter((action) => action.key !== 'button'),
  };
}

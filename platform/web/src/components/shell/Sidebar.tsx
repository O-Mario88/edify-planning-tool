'use client';

/*
 * The sidebar, in the existing web's own markup and class names
 * (templates/components/sidebar.html), so the existing stylesheet
 * (static/css/components/sidebar.css, linked by the root layout) draws it
 * exactly as there: the gateway's sections in their order, every link drawn,
 * the current page marked, and the settings panel at the foot. The current
 * page is read in the browser: the shell's layout is not redrawn when a link
 * moves within it, so the path it was drawn for goes stale.
 */
import Link from 'next/link';
import { usePathname } from 'next/navigation';

import type { NavSection } from '@/gen/edify/screens/v1/navigation_pb';
import { safeIcon } from '@/lib/icon';

import { SidebarSettings } from './SidebarSettings';

export function normalizeNavPath(raw: string): string {
  const noHash = raw.split('#')[0] ?? raw;
  const bare = noHash.split('?')[0] ?? noHash;
  const trimmed = bare.replace(/\/+$/, '');
  return trimmed || '/';
}

/**
 * Routes that own sibling sub-routes as separate sidebar items and must only
 * match themselves (never swallow child paths like /projects/planning).
 */
const EXACT_ONLY_URLS = new Set(['/', '/dashboard', '/projects', '/ssa']);

/**
 * Alias and folded paths (apps/core/navigation.py) that keep a visible host
 * item active when the target itself does not have its own visible sidebar item.
 */
function aliasPathsFor(itemUrl: string, pageKey?: string): readonly string[] {
  const norm = normalizeNavPath(itemUrl);
  const out: string[] = [];
  if (norm === '/dashboard') {
    out.push('/', '/home', '/todos', '/actions/mine');
  } else if (norm === '/partners') {
    out.push('/partner-oversight');
  } else if (norm === '/actions/sent') {
    out.push('/extra-work');
  } else if (norm === '/projects/monitoring') {
    out.push('/projects/analytics');
  } else if (norm === '/projects/my-plan') {
    out.push('/calendar');
  }
  if (pageKey === 'monthly_budget') {
    out.push('/fund-requests/weekly', '/work-plan');
  } else if (pageKey === 'priorities_master') {
    out.push('/my-performance', '/my-targets', '/my-professional-development');
  }
  return out;
}

function segmentMatch(prefix: string, here: string, allowPrefix: boolean): { exact: boolean; length: number } | null {
  const norm = normalizeNavPath(prefix);
  if (here === norm) return { exact: true, length: norm.length };
  if (allowPrefix && !EXACT_ONLY_URLS.has(norm) && here.startsWith(`${norm}/`)) {
    return { exact: false, length: norm.length };
  }
  return null;
}

export interface NavMatchCandidate {
  readonly key: string;
  readonly url: string;
  readonly pageKey?: string;
}

/**
 * Pick at most ONE winning navigation item across a visible menu:
 *   1. Exact match on an item's own URL.
 *   2. Most specific eligible parent match on a path-segment boundary.
 *   3. Most specific alias / folded path match (exact before prefix).
 * Ties break deterministically by menu order.
 */
export function resolveActiveNavKey(candidates: readonly NavMatchCandidate[], path: string): string | null {
  const here = normalizeNavPath(path);
  let bestKey: string | null = null;
  let bestPriority = 0;
  let bestLength = -1;

  for (const candidate of candidates) {
    if (!candidate.url) continue;
    const own = segmentMatch(candidate.url, here, true);
    if (own) {
      const priority = own.exact ? 4 : 3;
      if (priority > bestPriority || (priority === bestPriority && own.length > bestLength)) {
        bestKey = candidate.key;
        bestPriority = priority;
        bestLength = own.length;
      }
      continue;
    }
    for (const alias of aliasPathsFor(candidate.url, candidate.pageKey)) {
      const allowPrefix = alias !== '/' && alias !== '/home';
      const hit = segmentMatch(alias, here, allowPrefix);
      if (!hit) continue;
      const priority = hit.exact ? 2 : 1;
      if (priority > bestPriority || (priority === bestPriority && hit.length > bestLength)) {
        bestKey = candidate.key;
        bestPriority = priority;
        bestLength = hit.length;
      }
    }
  }
  return bestKey;
}

export function isCurrent(itemUrl: string, path: string): boolean {
  const url = normalizeNavPath(itemUrl);
  const here = normalizeNavPath(path);
  return here === url || (!EXACT_ONLY_URLS.has(url) && here.startsWith(`${url}/`));
}

function Brand() {
  return (
    <div className="app-sidebar__brand">
      <div className="app-sidebar__wordmark">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/static/images/logo.png" alt="Edify" width={110} height={45} className="app-sidebar__brand-logo" />
        <span className="app-sidebar__brand-divider" aria-hidden="true" />
        <span className="app-sidebar__brand-product">
          Planning &amp;
          <br />
          Monitoring
        </span>
      </div>
    </div>
  );
}

export function SidebarNav({ sections, path }: { sections: NavSection[]; path: string }) {
  const here = usePathname() ?? path;
  const candidates: NavMatchCandidate[] = [];
  sections.forEach((section, sectionIndex) => {
    section.items.forEach((item, itemIndex) => {
      candidates.push({
        key: `${sectionIndex}:${itemIndex}:${item.url}`,
        url: item.url,
        pageKey: item.pageKey,
      });
    });
  });
  const activeKey = resolveActiveNavKey(candidates, here);
  return (
    <nav className="app-sidebar__nav" aria-label="Main Navigation">
      {sections.map((section, sectionIndex) =>
        section.items.length ? (
          <div key={section.label} className="app-sidebar__section">
            {section.label ? (
              <div className="app-sidebar__section-header">
                <span className="app-sidebar__section-title">{section.label.toUpperCase()}</span>
              </div>
            ) : null}
            <div className="app-sidebar__section-items">
              {section.items.map((item, itemIndex) => {
                const key = `${sectionIndex}:${itemIndex}:${item.url}`;
                const active = key === activeKey;
                return (
                  <Link
                    key={item.url}
                    href={item.url}
                    title={item.label}
                    aria-current={active ? 'page' : undefined}
                    className={`app-sidebar__item ${active ? 'app-sidebar__item--active' : ''}`}
                  >
                    <div className="app-sidebar__item-icon" aria-hidden="true" dangerouslySetInnerHTML={{ __html: safeIcon(item.iconSvg) }} />
                    <span className="app-sidebar__item-label">{item.label}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        ) : null,
      )}
    </nav>
  );
}

export function Sidebar({ sections, path }: { sections: NavSection[]; path: string }) {
  return (
    <aside className="app-sidebar hidden lg:flex">
      <Brand />
      <div className="app-sidebar__nav-container">
        <SidebarNav sections={sections} path={path} />
      </div>
      <div className="app-sidebar__footer">
        <SidebarSettings path={path} />
      </div>
    </aside>
  );
}

export { Brand as SidebarBrand };

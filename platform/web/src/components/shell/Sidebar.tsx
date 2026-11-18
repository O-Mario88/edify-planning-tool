/*
 * The sidebar, in the existing web's own markup and class names
 * (templates/components/sidebar.html), so the existing stylesheet
 * (static/css/components/sidebar.css, linked by the root layout) draws it
 * exactly as there: the gateway's sections in their order, every link drawn,
 * the current page marked, and the settings panel at the foot.
 */
import Link from 'next/link';

import type { NavSection } from '@/gen/edify/screens/v1/navigation_pb';
import { safeIcon } from '@/lib/icon';

import { SidebarSettings } from './SidebarSettings';

export function isCurrent(itemUrl: string, path: string): boolean {
  const bare = path.split('?')[0] ?? path;
  const url = itemUrl.replace(/\/$/, '') || '/';
  const here = bare.replace(/\/$/, '') || '/';
  return here === url || here.startsWith(`${url}/`);
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
  return (
    <nav className="app-sidebar__nav" aria-label="Main Navigation">
      {sections.map((section) =>
        section.items.length ? (
          <div key={section.label} className="app-sidebar__section">
            {section.label ? (
              <div className="app-sidebar__section-header">
                <span className="app-sidebar__section-title">{section.label.toUpperCase()}</span>
              </div>
            ) : null}
            <div className="app-sidebar__section-items">
              {section.items.map((item) => {
                const active = isCurrent(item.url, path);
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

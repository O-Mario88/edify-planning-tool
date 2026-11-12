/*
 * The sidebar as the owner restored it (2026-10-02): the gateway's sections in
 * their order, every link drawn, no search and no folded groups. Sizes and
 * colours are the existing web's (static/css/components/sidebar.css).
 */
import Link from 'next/link';

import type { NavSection } from '@/gen/edify/screens/v1/navigation_pb';
import { safeIcon } from '@/lib/icon';

export function isCurrent(itemUrl: string, path: string): boolean {
  const bare = path.split('?')[0] ?? path;
  return bare === itemUrl || bare.startsWith(`${itemUrl}/`);
}

function Brand() {
  return (
    <div className="mb-2 px-2 py-1">
      <div className="flex min-h-[54px] items-center justify-center gap-[11px]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/images/logo.png" alt="Edify" width={110} height={45} className="block h-auto max-h-[46px] w-[110px] min-w-[110px] object-contain object-left" />
        <span className="h-[42px] w-px shrink-0 bg-[rgba(189,216,233,0.72)]" aria-hidden="true" />
        <span className="whitespace-nowrap text-[length:var(--edify-text-label-size)] font-medium leading-[1.35] tracking-[-0.01em] text-[rgba(215,230,239,0.88)]">
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
    <nav aria-label="Main Navigation" className="flex flex-col gap-0.5">
      {sections.map((section) =>
        section.items.length ? (
          <div key={section.label} className="mt-2.5">
            {section.label ? (
              <div className="flex items-center px-3 pb-1 pt-1.5">
                <span className="text-[length:var(--edify-text-micro-size)] font-semibold uppercase tracking-[0.08em] text-[rgba(189,216,233,0.5)]">
                  {section.label}
                </span>
              </div>
            ) : null}
            <div className="flex flex-col gap-0.5 pt-[3px]">
              {section.items.map((item) => {
                const active = isCurrent(item.url, path);
                return (
                  <Link
                    key={item.url}
                    href={item.url}
                    title={item.label}
                    aria-current={active ? 'page' : undefined}
                    className={
                      'relative flex h-[38px] items-center gap-3 rounded-[var(--radius-control)] px-2.5 py-1 text-[length:var(--edify-text-label-size)] no-underline transition-colors ' +
                      (active
                        ? 'border border-[var(--brand-primary-border)] bg-[var(--brand-primary)] font-semibold text-white before:absolute before:bottom-2 before:left-0 before:top-2 before:w-[3px] before:rounded-r-[2px] before:bg-[var(--brand-primary-soft)] dark:bg-[var(--edify-sidebar-active)]'
                        : 'border border-transparent font-medium text-[rgba(221,237,247,0.76)] hover:bg-white/5 hover:text-white')
                    }
                  >
                    <span
                      className={'edify-nav-icon flex h-5 w-5 shrink-0 items-center justify-center ' + (active ? 'text-[var(--brand-primary-soft)]' : '')}
                      aria-hidden="true"
                      dangerouslySetInnerHTML={{ __html: safeIcon(item.iconSvg) }}
                    />
                    <span className="truncate">{item.label}</span>
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

const COG =
  'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z';

export function Sidebar({ sections, path }: { sections: NavSection[]; path: string }) {
  return (
    <aside className="sticky top-0 hidden h-dvh w-[260px] shrink-0 flex-col border-r border-[var(--edify-border)] bg-[image:var(--edify-sidebar-bg)] px-3.5 py-[18px] lg:flex">
      <Brand />
      <div className="mt-5 flex-1 overflow-y-auto pb-4 pr-1 [scrollbar-width:thin] [scrollbar-color:rgba(255,255,255,0.08)_transparent]">
        <SidebarNav sections={sections} path={path} />
      </div>
      <div className="border-t border-white/10 pt-3">
        <Link
          href="/settings"
          aria-label="Settings"
          className="grid h-9 w-9 place-items-center rounded-full bg-white/10 text-[rgba(221,237,247,0.86)] hover:bg-white/15"
        >
          <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor" strokeWidth={1.8} aria-hidden="true">
            <path strokeLinecap="round" strokeLinejoin="round" d={COG} />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </Link>
      </div>
    </aside>
  );
}

export { Brand as SidebarBrand };

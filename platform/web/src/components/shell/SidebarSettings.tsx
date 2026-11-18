'use client';

/*
 * The sidebar's settings panel (templates/components/sidebar.html): the cog
 * at the foot opens Appearance, All settings, My profile, the notification
 * centre and Help for this page, upward, as on the existing web. Edify Blue
 * is not offered by this web app yet.
 */
import Link from 'next/link';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

import { THEME_OPTIONS, chooseTheme, readThemePreference, subscribeThemePreference } from '@/lib/themePreference';
import type { ThemePreference } from '@/lib/themePreference';

const COG =
  'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z';

export function SidebarSettings({ path }: { path: string }) {
  const [open, setOpen] = useState(false);
  const here = useRef<HTMLDivElement>(null);
  const preference = useSyncExternalStore<ThemePreference>(subscribeThemePreference, readThemePreference, () => 'light');
  useEffect(() => {
    if (!open) return undefined;
    const away = (event: MouseEvent) => {
      if (!here.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', away);
    document.addEventListener('keydown', escape);
    return () => {
      document.removeEventListener('mousedown', away);
      document.removeEventListener('keydown', escape);
    };
  }, [open]);
  const route = encodeURIComponent(path.split('?')[0] || '/');
  return (
    <div className="app-sidebar__settings" ref={here}>
      <button
        type="button"
        className="app-sidebar__user app-sidebar__settings-trigger"
        aria-label="Settings"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="app-sidebar__user-avatar" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}>
            <path strokeLinecap="round" strokeLinejoin="round" d={COG} />
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </span>
      </button>
      {open ? (
        <div className="app-sidebar__settings-menu" aria-label="Settings panel">
          <p className="app-sidebar__settings-heading">Appearance</p>
          <div className="app-sidebar__theme-row" role="group" aria-label="Workspace theme">
            {THEME_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={`app-sidebar__theme ${preference === option.value ? 'is-active' : ''}`}
                aria-pressed={preference === option.value}
                onClick={() => chooseTheme(option.value)}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="app-sidebar__settings-divider" role="separator" />
          <Link href="/settings" className="app-sidebar__settings-item">
            All settings
          </Link>
          <Link href="/profile" className="app-sidebar__settings-item">
            My profile
          </Link>
          <Link href="/notifications" className="app-sidebar__settings-item">
            Notification centre
          </Link>
          <Link href={`/help/context?for=${route}`} className="app-sidebar__settings-item">
            <svg fill="none" viewBox="0 0 24 24" stroke="currentColor" aria-hidden="true">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
            <span>Help for this page</span>
          </Link>
        </div>
      ) : null}
    </div>
  );
}

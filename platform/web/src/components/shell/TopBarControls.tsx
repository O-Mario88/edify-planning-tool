'use client';

/* The top bar's interactive parts, in the existing web's markup and class
   names (templates/layouts/shell.html), so its stylesheets draw them as
   there: page history, the theme switch, the account menu (role switch,
   help, report, profile, sign out) and the phone menu. */
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

import { applyThemeClass, chooseTheme, subscribeThemePreference } from '@/lib/themePreference';

import { Icon } from './icons';

const CONTROL = 'edify-topbar__icon-control flex items-center justify-center focus:outline-none';

export function HistoryControls() {
  return (
    <nav className="edify-topbar__history flex items-center shrink-0" aria-label="Page history">
      <button type="button" className={`${CONTROL} edify-topbar__history-control`} title="Back" aria-label="Go back" onClick={() => history.back()}>
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 5l-7 7 7 7" />
        </svg>
      </button>
      <button
        type="button"
        className={`${CONTROL} edify-topbar__history-control edify-topbar__history-control--forward`}
        title="Forward"
        aria-label="Go forward"
        onClick={() => history.forward()}
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
        </svg>
      </button>
      <button
        type="button"
        className={`${CONTROL} edify-topbar__history-control edify-topbar__history-control--refresh`}
        title="Refresh"
        aria-label="Refresh this page"
        onClick={() => location.reload()}
      >
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h5M20 20v-5h-5" />
          <path strokeLinecap="round" strokeLinejoin="round" d="M5.6 15A7 7 0 0 0 18 16.5M18.4 9A7 7 0 0 0 6 7.5" />
        </svg>
      </button>
    </nav>
  );
}

/** Kept for callers that set the theme class directly. */
export const applyTheme = applyThemeClass;

/** The root's theme class, which the page's head script set before paint. */
export function subscribeTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
  const unsubscribe = subscribeThemePreference(onChange);
  return () => {
    observer.disconnect();
    unsubscribe();
  };
}

export function ThemeToggle() {
  const dark = useSyncExternalStore(
    subscribeTheme,
    () => document.documentElement.classList.contains('theme-dark'),
    () => false,
  );
  return (
    <button
      type="button"
      className={`${CONTROL} edify-topbar__utility edify-topbar__utility--theme`}
      onClick={() => chooseTheme(dark ? 'light' : 'dark')}
      aria-label={dark ? 'Turn off night black mode' : 'Turn on night black mode'}
      aria-pressed={dark}
    >
      {dark ? (
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M12 3V1m0 22v-2m9-9h2M1 12h2m15.364-6.364 1.414-1.414M4.222 19.778l1.414-1.414m12.728 0 1.414 1.414M4.222 4.222l1.414 1.414M16 12a4 4 0 11-8 0 4 4 0 018 0z"
          />
        </svg>
      ) : (
        <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path strokeLinecap="round" strokeLinejoin="round" d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
        </svg>
      )}
    </button>
  );
}

/** Closes on a click outside or Escape; opens below its button. */
function useDisclosure() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onClick = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false);
    document.addEventListener('mousedown', onClick);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onClick);
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);
  return { open, setOpen, ref };
}

export interface AccountMenuProps {
  readonly name: string;
  readonly initials: string;
  readonly email?: string;
  readonly activeRole: string;
  readonly roles: readonly { value: string; label: string }[];
  readonly path: string;
}

const MENU_ITEM = 'w-full text-left px-4 py-1.5 hover:bg-[var(--edify-surface-muted)] font-semibold';

export function AccountMenu({ name, initials, email = '', activeRole, roles, path }: AccountMenuProps) {
  const { open, setOpen, ref } = useDisclosure();
  const route = encodeURIComponent(path.split('?')[0] || '/');
  return (
    <div className="edify-topbar__account relative" ref={ref}>
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className={`${CONTROL} edify-topbar__icon-control--avatar text-white text-[12px] font-semibold`}
      >
        {/* The initials are a picture of the person; the button is named in
            words (WCAG 2.5.3 asks a label to hold what is shown). */}
        <span aria-hidden="true">{initials}</span>
        <span className="sr-only">Account menu</span>
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full mt-2 w-56 rounded-surface shadow-lg py-1.5 text-[12px] z-50 overflow-hidden edify-surface border edify-border"
        >
          <div className="px-4 py-2 border-b edify-border-bottom">
            <p className="font-semibold edify-text">{name}</p>
            <p className="edify-text-caption font-semibold edify-text-muted">{activeRole}</p>
            {email ? <p className="edify-text-caption truncate edify-text-subtle mt-0.5">{email}</p> : null}
          </div>
          {roles.length > 1 ? (
            <>
              <div className="px-3 py-1 edify-text-caption font-bold uppercase tracking-wider edify-surface-muted edify-text-subtle">Switch Active Role</div>
              {roles.map((role) => (
                <form key={role.value} method="post" action="/auth/switch-role" className="m-0">
                  <input type="hidden" name="role" value={role.value} />
                  <input type="hidden" name="next" value={path} />
                  <button
                    type="submit"
                    role="menuitem"
                    className={MENU_ITEM}
                    style={{ color: role.value === activeRole ? 'var(--edify-accent)' : 'var(--edify-text-muted)' }}
                  >
                    {role.label}
                  </button>
                </form>
              ))}
              <div className="my-1.5 border-t edify-border-top" />
            </>
          ) : null}
          <a href={`/help/context?for=${route}`} className="edify-mobile-account-link block px-4 py-2 edify-text">
            Help for this page
          </a>
          <a href={`/support?route=${route}`} className="edify-mobile-account-link block px-4 py-2 edify-text">
            Report a problem
          </a>
          <Link href="/profile" className="block px-4 py-1.5 hover:bg-[var(--edify-surface-muted)] font-semibold edify-text">
            My Profile
          </Link>
          <form method="post" action="/auth/sign-out" className="m-0 mt-1 border-t edify-border-top">
            <button type="submit" role="menuitem" className="account-menu__signout w-full text-left px-4 py-2 font-semibold">
              Log out
            </button>
          </form>
        </div>
      ) : null}
    </div>
  );
}

/** The page the phone's More opens: the reader's whole menu in the native app's design. */
export const MORE_PATH = '/more';

/**
 * Below 1024px the menu is the native app's More page (owner, 2026-11-19: the
 * same mobile navigation as the app, not the old blue sidebar): the bottom
 * bar's More tab, and the top bar's menu button at tablet width, open it.
 */
export function PhoneMenu({ asTab = false }: { asTab?: boolean }) {
  const current = usePathname() === MORE_PATH;
  if (asTab) {
    return (
      <Link
        href={MORE_PATH}
        aria-current={current ? 'page' : undefined}
        className={`relative flex h-16 flex-col items-center justify-center gap-1 text-[12px] font-semibold ${current ? 'text-[var(--brand-primary)] before:absolute before:left-1/4 before:right-1/4 before:top-0 before:h-[3px] before:rounded-b before:bg-[var(--brand-primary)]' : 'text-[var(--edify-text)]'}`}
      >
        <Icon name="menu" className="h-6 w-6" />
        <span>More</span>
      </Link>
    );
  }
  return (
    <Link href={MORE_PATH} className={`${CONTROL} hidden md:flex lg:hidden`} aria-label="Open the menu">
      <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" d="M4 6h16M4 12h16M4 18h16" />
      </svg>
    </Link>
  );
}

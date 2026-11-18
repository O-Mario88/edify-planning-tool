'use client';

/* The top bar's interactive parts: page history, the theme switch, the
   account menu (role switch, sign out) and the phone menu. */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type { ReactNode } from 'react';

import { Icon } from './icons';

const ICON_BUTTON =
  'grid h-9 w-9 place-items-center rounded-full text-[var(--edify-text-muted)] hover:bg-[var(--edify-surface-muted)] hover:text-[var(--edify-text)] focus-visible:outline-2 focus-visible:outline-[var(--brand-primary)]';

export function HistoryControls() {
  return (
    <nav aria-label="Page history" className="hidden shrink-0 items-center gap-1 [@media(display-mode:standalone)]:flex">
      <button type="button" className={ICON_BUTTON} title="Back" aria-label="Go back" onClick={() => history.back()}>
        <Icon name="back" className="h-5 w-5" />
      </button>
      <button type="button" className={ICON_BUTTON} title="Forward" aria-label="Go forward" onClick={() => history.forward()}>
        <Icon name="forward" className="h-5 w-5" />
      </button>
      <button type="button" className={ICON_BUTTON} title="Refresh" aria-label="Refresh this page" onClick={() => location.reload()}>
        <Icon name="refresh" className="h-5 w-5" />
      </button>
    </nav>
  );
}

export function applyTheme(dark: boolean) {
  const root = document.documentElement;
  root.classList.remove('light', 'theme-dark', 'dark');
  root.classList.add(dark ? 'theme-dark' : 'light');
  if (dark) root.classList.add('dark');
  root.dataset.theme = dark ? 'dark' : 'light';
}

/** The root's theme class, which the page's head script set before paint. */
export function subscribeTheme(onChange: () => void) {
  const observer = new MutationObserver(onChange);
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
  return () => observer.disconnect();
}

export function ThemeToggle() {
  const dark = useSyncExternalStore(
    subscribeTheme,
    () => document.documentElement.classList.contains('theme-dark'),
    () => false,
  );
  const toggle = () => {
    const next = !dark;
    applyTheme(next);
    try {
      localStorage.setItem('edify_theme', next ? 'dark' : 'light');
    } catch {
      // Private windows: the choice lasts for this page only.
    }
  };
  return (
    <button
      type="button"
      className={ICON_BUTTON}
      onClick={toggle}
      aria-label={dark ? 'Turn off night black mode' : 'Turn on night black mode'}
      aria-pressed={dark}
    >
      <Icon name={dark ? 'sun' : 'moon'} className="h-5 w-5" />
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
  readonly activeRole: string;
  readonly roles: readonly { value: string; label: string }[];
  readonly path: string;
}

export function AccountMenu({ name, initials, activeRole, roles, path }: AccountMenuProps) {
  const { open, setOpen, ref } = useDisclosure();
  const others = roles.filter((role) => role.value !== activeRole);
  const activeLabel = roles.find((role) => role.value === activeRole)?.label ?? activeRole;
  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        aria-label="Account menu"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="grid h-9 w-9 place-items-center rounded-full bg-[var(--brand-primary)] text-[12px] font-semibold text-white"
      >
        {initials}
      </button>
      {open ? (
        <div role="menu" className="absolute right-0 top-full z-50 mt-2 w-64 rounded-[var(--radius-surface)] border border-[var(--edify-border)] bg-[var(--edify-surface)] py-1 text-[13px] shadow-lg">
          <div className="border-b border-[var(--edify-border)] px-4 py-2.5">
            <p className="font-semibold text-[var(--edify-text)]">{name}</p>
            <p className="text-[length:var(--edify-text-micro-size)] font-semibold text-[var(--edify-text-muted)]">{activeLabel}</p>
          </div>
          {others.length ? (
            <div className="border-b border-[var(--edify-border)] py-1">
              <p className="bg-[var(--edify-surface-muted)] px-3 py-1 text-[length:var(--edify-text-micro-size)] font-bold uppercase tracking-wider text-[var(--edify-text-subtle)]">
                Switch Active Role
              </p>
              {others.map((role) => (
                <form key={role.value} method="post" action="/auth/switch-role">
                  <input type="hidden" name="role" value={role.value} />
                  <input type="hidden" name="next" value={path} />
                  <button type="submit" role="menuitem" className="w-full px-4 py-1.5 text-left font-semibold hover:bg-[var(--edify-surface-muted)]">
                    {role.label}
                  </button>
                </form>
              ))}
            </div>
          ) : null}
          <form method="post" action="/auth/sign-out" className="mt-1">
            <button type="submit" role="menuitem" className="w-full px-4 py-2 text-left font-semibold text-[#be123c] hover:bg-[var(--edify-surface-muted)]">
              Log out
            </button>
          </form>
        </div>
      ) : null}
    </div>
  );
}

/** Below 1024px the sidebar opens from the top bar's menu button. */
export function PhoneMenu({ children, asTab = false }: { children: ReactNode; asTab?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      {asTab ? (
        <button type="button" aria-label="More" aria-expanded={open} onClick={() => setOpen(true)} className="flex h-16 flex-col items-center justify-center gap-1 text-[12px] font-semibold text-[var(--edify-text)]">
          <Icon name="menu" className="h-6 w-6" />
          <span>More</span>
        </button>
      ) : (
        <button type="button" className={`${ICON_BUTTON} hidden md:grid lg:hidden`} aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}>
          <Icon name="menu" className="h-5 w-5" />
        </button>
      )}
      {open ? (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button type="button" aria-label="Close menu" className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-[280px] flex-col overflow-y-auto bg-[image:var(--edify-sidebar-bg)] px-3.5 py-[18px]" onClick={(event) => {
            if ((event.target as HTMLElement).closest('a')) setOpen(false);
          }}>
            {children}
          </div>
        </div>
      ) : null}
    </>
  );
}

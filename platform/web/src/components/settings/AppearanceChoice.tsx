'use client';

/*
 * The Appearance card's choice: the workspace theme for this browser, kept
 * under the same key the existing web and the top bar's switch use
 * ("edify_theme": system, light or dark). A viewer's preference, not data.
 * The existing web's Edify Blue theme is not drawn by this web app yet, so
 * it is not offered here.
 */
import { useSyncExternalStore } from 'react';

import { applyTheme } from '../shell/TopBarControls';

type Preference = 'system' | 'light' | 'dark';

const KEY = 'edify_theme';
/** Told when this page changes the choice; another tab's change comes as a storage event. */
const CHANGED = 'edify-theme-changed';

function subscribe(onChange: () => void) {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener('storage', onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener('storage', onChange);
  };
}

const OPTIONS: readonly { value: Preference; label: string; note: string }[] = [
  { value: 'system', label: 'System', note: 'Matches your device appearance' },
  { value: 'light', label: 'Light', note: 'Clean and focused' },
  { value: 'dark', label: 'Night black', note: 'Deep navy-black, low-glare and easy on the eyes at night' },
];

function readPreference(): Preference {
  try {
    const saved = localStorage.getItem(KEY);
    return saved === 'system' || saved === 'dark' ? saved : 'light';
  } catch {
    return 'light';
  }
}

function isDark(preference: Preference): boolean {
  return preference === 'dark' || (preference === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
}

export function AppearanceChoice() {
  const preference = useSyncExternalStore<Preference>(subscribe, readPreference, () => 'light');
  const choose = (next: Preference) => {
    applyTheme(isDark(next));
    try {
      localStorage.setItem(KEY, next);
    } catch {
      // Private windows: the choice lasts for this page only.
    }
    window.dispatchEvent(new Event(CHANGED));
  };
  return (
    <div role="group" aria-label="Workspace color theme" className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      {OPTIONS.map((option) => {
        const active = preference === option.value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => choose(option.value)}
            className={`rounded-[8px] border px-3 py-2 text-left ${
              active
                ? 'border-[var(--brand-primary)] bg-[var(--brand-primary-soft)]'
                : 'border-[var(--edify-border)] hover:bg-[var(--edify-surface-muted)]'
            }`}
          >
            <span className="block text-[length:var(--edify-text-label-size)] font-semibold text-[var(--edify-text)]">{option.label}</span>
            <span className="mt-0.5 block text-[length:var(--edify-text-micro-size)] text-[var(--edify-text-muted)]">{option.note}</span>
          </button>
        );
      })}
    </div>
  );
}

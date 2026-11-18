'use client';

/*
 * The Appearance card's choice of workspace theme for this browser
 * (lib/themePreference). The existing web's Edify Blue theme is not offered
 * by this web app yet.
 */
import { useSyncExternalStore } from 'react';

import { THEME_OPTIONS, chooseTheme, readThemePreference, subscribeThemePreference } from '@/lib/themePreference';
import type { ThemePreference } from '@/lib/themePreference';

export function AppearanceChoice() {
  const preference = useSyncExternalStore<ThemePreference>(subscribeThemePreference, readThemePreference, () => 'light');
  return (
    <div role="group" aria-label="Workspace color theme" className="grid grid-cols-1 gap-2 sm:grid-cols-3">
      {THEME_OPTIONS.map((option) => {
        const active = preference === option.value;
        return (
          <button
            key={option.value}
            type="button"
            aria-pressed={active}
            onClick={() => chooseTheme(option.value)}
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

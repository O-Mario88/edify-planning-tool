/**
 * The workspace theme this browser chose, kept under the existing web's key
 * ("edify_theme": system, light or dark) and applied to the root as the
 * existing web applies it. A viewer's preference, not data. Shared by the
 * Settings page's Appearance card and the sidebar's settings panel.
 */
export type ThemePreference = 'system' | 'light' | 'dark';

export const THEME_KEY = 'edify_theme';
const CHANGED = 'edify-theme-changed';

export const THEME_OPTIONS: readonly { value: ThemePreference; label: string; note: string }[] = [
  { value: 'system', label: 'System', note: 'Matches your device appearance' },
  { value: 'light', label: 'Light', note: 'Clean and focused' },
  { value: 'dark', label: 'Night black', note: 'Deep navy-black, low-glare and easy on the eyes at night' },
];

export function readThemePreference(): ThemePreference {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    return saved === 'system' || saved === 'dark' ? saved : 'light';
  } catch {
    return 'light';
  }
}

/** For useSyncExternalStore: this page's choices and another tab's. */
export function subscribeThemePreference(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener('storage', onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener('storage', onChange);
  };
}

export function applyThemeClass(dark: boolean): void {
  const root = document.documentElement;
  root.classList.remove('light', 'theme-dark', 'dark');
  root.classList.add(dark ? 'theme-dark' : 'light');
  if (dark) root.classList.add('dark');
  root.dataset.theme = dark ? 'dark' : 'light';
}

export function chooseTheme(next: ThemePreference): void {
  applyThemeClass(next === 'dark' || (next === 'system' && matchMedia('(prefers-color-scheme: dark)').matches));
  try {
    localStorage.setItem(THEME_KEY, next);
  } catch {
    // Private windows: the choice lasts for this page only.
  }
  window.dispatchEvent(new Event(CHANGED));
}

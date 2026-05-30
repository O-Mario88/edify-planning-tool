"use client";

// ThemeProvider — the source of truth for the app's colour mode.
//
// Four modes:
//   • "light"  — fixed light surfaces, ignores OS preference
//   • "dark"   — fixed dark surfaces, ignores OS preference
//   • "glass"  — futuristic holographic command-center theme
//   • "system" — follows prefers-color-scheme live, resolves to
//                light or dark (glass is always explicit)
//
// What lands on <html>:
//   • light  → no class
//   • dark   → `.dark` class
//   • glass  → `.glass` class (also implies dark colour-scheme so
//              native chrome adapts)
// These classes are mutually exclusive — the apply step removes the
// others before adding the current one.
//
// FOUC avoidance: a tiny pre-paint script is inlined into <head> at
// the layout level (see ThemeScript below). It reads the stored
// preference and stamps the right class on <html> BEFORE React
// mounts. Without it, the page would render light, then flip on
// hydrate — a jarring half-second flash on every reload.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

export type ThemeMode = "light" | "dark" | "glass" | "system";
export type ResolvedTheme = "light" | "dark" | "glass";

type ThemeContextValue = {
  /** The user's stated preference. "system" tracks the OS. */
  mode: ThemeMode;
  /** The class actually applied to <html> right now. */
  resolved: ResolvedTheme;
  /** Persist a new preference and apply it. */
  setMode: (next: ThemeMode) => void;
};

const STORAGE_KEY = "edify-theme";

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStoredMode(): ThemeMode {
  if (typeof window === "undefined") return "system";
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (raw === "light" || raw === "dark" || raw === "glass" || raw === "system") return raw;
  return "system";
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function resolveFor(mode: ThemeMode): ResolvedTheme {
  // Glass is always explicit — OS-level "prefers-color-scheme: glass"
  // doesn't exist. System resolves only between light and dark.
  if (mode === "system") return systemPrefersDark() ? "dark" : "light";
  return mode;
}

function applyClass(resolved: ResolvedTheme) {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  // Mutually exclusive class set — strip the others before applying
  // the active one so no two theme stylesheets stack.
  root.classList.remove("dark", "glass");
  if (resolved === "dark") root.classList.add("dark");
  else if (resolved === "glass") root.classList.add("glass");
  // Native chrome — both dark + glass want OS dark scrollbars / form
  // controls. Light = OS light.
  root.style.colorScheme = resolved === "light" ? "light" : "dark";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  // Initial state defaults to "system" so SSR + first paint match the
  // pre-hydration script. The mounted effect upgrades to the stored
  // value (which the pre-paint script has already applied to the DOM
  // anyway, so this is just bookkeeping for React).
  const [mode, setModeState] = useState<ThemeMode>("system");
  const [resolved, setResolved] = useState<ResolvedTheme>("light");

  // On mount: sync React state with what the pre-paint script already
  // applied. No DOM mutation here — the class is already correct.
  useEffect(() => {
    const stored = readStoredMode();
    setModeState(stored);
    setResolved(resolveFor(stored));
  }, []);

  // Live-watch the OS preference. Only meaningful while mode==="system".
  useEffect(() => {
    if (mode !== "system") return;
    const mql = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => {
      const next = systemPrefersDark() ? "dark" : "light";
      setResolved(next);
      applyClass(next);
    };
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, [mode]);

  const setMode = useCallback((next: ThemeMode) => {
    window.localStorage.setItem(STORAGE_KEY, next);
    setModeState(next);
    const r = resolveFor(next);
    setResolved(r);
    // Briefly enable the cross-fade class on <html>, then peel it off
    // after the transition so it doesn't slow other interactions.
    document.documentElement.classList.add("theme-fade");
    applyClass(r);
    window.setTimeout(() => {
      document.documentElement.classList.remove("theme-fade");
    }, 220);
  }, []);

  return (
    <ThemeContext.Provider value={{ mode, resolved, setMode }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    // Render-safe fallback: pages outside the provider get "system"
    // and a no-op setter rather than throwing.
    return {
      mode: "system",
      resolved: "light",
      setMode: () => {},
    };
  }
  return ctx;
}

// Inline script — must run before React hydrates. Stamps the right
// theme class onto <html> from the persisted preference (or the OS,
// when "system"). Anything heavier (effects, context, hooks) flashes
// the wrong theme for one paint frame; this is the only way to
// avoid that.
//
// Safe-string contents: no untrusted interpolation, no template
// literals that could be hijacked, no eval. The CSP-strict deploys
// can hash this script.
export const themePreloadScript = `
(function() {
  try {
    var stored = localStorage.getItem('${STORAGE_KEY}');
    var modes = ['light', 'dark', 'glass', 'system'];
    var mode = modes.indexOf(stored) >= 0 ? stored : 'system';
    var prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
    var resolved = mode === 'system' ? (prefersDark ? 'dark' : 'light') : mode;
    var root = document.documentElement;
    if (resolved === 'dark')  root.classList.add('dark');
    if (resolved === 'glass') root.classList.add('glass');
    root.style.colorScheme = resolved === 'light' ? 'light' : 'dark';
  } catch (_) { /* localStorage / matchMedia may be unavailable; fail open to light. */ }
})();
`;

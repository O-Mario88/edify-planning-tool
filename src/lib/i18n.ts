// Lightweight i18n — locale-aware string lookup with English fallback.
//
// This is a scaffold, not a full library. Production target is
// `next-intl`, which adds App Router locale routing, ICU plural
// rules, and a Provider-based React API. The shape below intentionally
// matches the next-intl call pattern (`t("cpl.hero.tagline", { name })`)
// so the migration is a one-line import change per call site.
//
// What this gives the app today:
//   • Single source-of-truth for user-facing strings (messages/*.json)
//   • Stable resolution rule — current locale → English → key (so a
//     missing translation never renders blank)
//   • ICU-lite parameter interpolation (`{name}`)
//   • Server + Edge safe — no Node deps, just imports JSON
//
// What to ship before going multi-locale in production:
//   • Locale-prefixed routes via `[locale]` segment + middleware redirect
//   • Locale persistence in cookie + Accept-Language header detection
//   • RTL-aware layout (Arabic, Hebrew) if/when added
//   • Swap this file for next-intl's `getTranslations()` / `useTranslations()`

import en from "../../messages/en.json";
import sw from "../../messages/sw.json";
import fr from "../../messages/fr.json";

export const SUPPORTED_LOCALES = ["en", "sw", "fr"] as const;
export type Locale = (typeof SUPPORTED_LOCALES)[number];
export const DEFAULT_LOCALE: Locale = "en";

type Messages = Record<string, unknown>;

const BUNDLES: Record<Locale, Messages> = {
  en: en as Messages,
  sw: sw as Messages,
  fr: fr as Messages,
};

// Walk a dotted key path through the bundle. At each step, try the
// remaining key as a *literal* property first (so JSON can mix-and-
// match nesting and dotted keys — "cpl": { "hero.greeting": "…" }
// works the same as "cpl": { "hero": { "greeting": "…" } }), then
// fall back to splitting on the next dot.
function lookup(bundle: Messages, key: string): string | undefined {
  const tryAt = (node: unknown, remaining: string): string | undefined => {
    if (!node || typeof node !== "object") return undefined;
    const obj = node as Record<string, unknown>;
    // Literal match on the whole remaining key (leaf).
    const direct = obj[remaining];
    if (typeof direct === "string") return direct;
    // Walk one dot at a time, descending into nested objects.
    const dot = remaining.indexOf(".");
    if (dot < 0) return undefined;
    const head = remaining.slice(0, dot);
    const tail = remaining.slice(dot + 1);
    const next = obj[head];
    return tryAt(next, tail);
  };
  return tryAt(bundle, key);
}

// {name} → params.name. Missing params render as the literal "{name}"
// so it's obvious in dev which substitutions were forgotten.
function interpolate(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (_, k: string) => {
    const v = params[k];
    return v == null ? `{${k}}` : String(v);
  });
}

/**
 * Get a translated string. Falls back to English, then to the key
 * itself, so a missing translation is visible but doesn't break the
 * UI.
 *
 *   t("cpl.hero.greeting", { name: "Daniel" }, "en")
 */
export function t(
  key: string,
  params?: Record<string, string | number>,
  locale: Locale = DEFAULT_LOCALE,
): string {
  const localized = lookup(BUNDLES[locale], key) ?? lookup(BUNDLES[DEFAULT_LOCALE], key) ?? key;
  return interpolate(localized, params);
}

// Locale resolution — read from cookie, fall back to default. Both
// server and client call this; the cookie name matches the eventual
// next-intl convention.
export const LOCALE_COOKIE = "edify-locale";

export function resolveLocale(cookieValue: string | undefined): Locale {
  if (cookieValue && (SUPPORTED_LOCALES as readonly string[]).includes(cookieValue)) {
    return cookieValue as Locale;
  }
  return DEFAULT_LOCALE;
}

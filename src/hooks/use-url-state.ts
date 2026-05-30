"use client";

// URL-backed state hooks for filter / sort / search / pagination.
//
// Why URL state, not useState:
//   • Survives reload, deep-link, share-via-link.
//   • Server can read the same values via `searchParams` so the first
//     paint matches the filter (no flicker, no client-only "applying…").
//   • Multiple panes on the same page (table + chart) read the same
//     URL key and stay in lockstep without prop-drilling.
//
// Conventions enforced here:
//   • `router.replace` is used (not `push`) — filter changes don't pollute
//     browser history. The user's Back button still goes to the previous
//     page, which is what they expect.
//   • Default values are NEVER written to the URL (`?filter=all` is noise).
//   • Updates are batched per microtask so two `setX()` calls in the same
//     handler produce one navigation, not two.
//   • SSR-safe: reading is a no-op until hydration; writing is guarded by
//     `typeof window`.

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

// ────────── writer ───────────────────────────────────────────────────
//
// Synchronous wrapper around `router.replace`. Each setter call lands
// one navigation. The Next router already coalesces rapid replace
// calls on the same path, so batching here was premature.

type PendingUpdate = Record<string, string | null>;

function useSearchParamWriter() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();

  return useCallback(
    (updates: PendingUpdate) => {
      const next = new URLSearchParams(searchParams?.toString() ?? "");
      for (const [key, value] of Object.entries(updates)) {
        if (value == null || value === "") next.delete(key);
        else next.set(key, value);
      }
      const qs = next.toString();
      router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );
}

// ────────── primitive: single key ────────────────────────────────────

export type UseUrlStateOptions<T extends string> = {
  /** URL query key, e.g. "tab" or "status". */
  key: string;
  /** Default — never written to the URL. */
  defaultValue: T;
  /** Optional allow-list. Anything not in here falls back to default. */
  allowed?: readonly T[];
};

export function useUrlState<T extends string = string>(
  opts: UseUrlStateOptions<T>,
): [T, (next: T) => void] {
  const searchParams = useSearchParams();
  const enqueue = useSearchParamWriter();

  const raw = searchParams?.get(opts.key) ?? null;
  const value = useMemo<T>(() => {
    if (raw == null) return opts.defaultValue;
    if (opts.allowed && !opts.allowed.includes(raw as T)) return opts.defaultValue;
    return raw as T;
  }, [raw, opts.defaultValue, opts.allowed]);

  const setValue = useCallback(
    (next: T) => {
      enqueue({ [opts.key]: next === opts.defaultValue ? null : next });
    },
    [enqueue, opts.key, opts.defaultValue],
  );

  return [value, setValue];
}

// ────────── primitive: debounced text (search) ───────────────────────
//
// Keeps the input responsive at 60fps while throttling the URL write
// (and the resulting server round-trip) to a sensible cadence.

export type UseUrlSearchOptions = {
  key: string;
  defaultValue?: string;
  /** Debounce in ms. Default 300 — feels instant, doesn't thrash. */
  debounceMs?: number;
};

export function useUrlSearch(
  opts: UseUrlSearchOptions,
): [string, (next: string) => void] {
  const { key, defaultValue = "", debounceMs = 300 } = opts;
  const searchParams = useSearchParams();
  const enqueue = useSearchParamWriter();

  const urlValue = searchParams?.get(key) ?? defaultValue;

  // Local state for the input so typing stays at native speed; URL
  // gets the trailing value after debounce.
  const [local, setLocal] = useState(urlValue);
  const lastUrlRef = useRef(urlValue);

  // Adopt external URL changes (Back button, programmatic nav).
  useEffect(() => {
    if (urlValue !== lastUrlRef.current) {
      lastUrlRef.current = urlValue;
      setLocal(urlValue);
    }
  }, [urlValue]);

  // Debounced write-back.
  useEffect(() => {
    if (local === urlValue) return;
    const t = setTimeout(() => {
      lastUrlRef.current = local;
      enqueue({ [key]: local.trim() === "" ? null : local });
    }, debounceMs);
    return () => clearTimeout(t);
  }, [local, urlValue, enqueue, key, debounceMs]);

  return [local, setLocal];
}

// ────────── primitive: multi-key filter object ──────────────────────
//
// For surfaces with several filter dimensions (FY, month, region,
// district, …). Returns the merged object + a single `setFilters`
// that takes a partial — all keys reach the URL in one navigation.

export type UseUrlFiltersSpec<T extends Record<string, string>> = {
  [K in keyof T]: { defaultValue: T[K]; allowed?: readonly T[K][] };
};

export function useUrlFilters<T extends Record<string, string>>(
  spec: UseUrlFiltersSpec<T>,
): [T, (patch: Partial<T>) => void, () => void] {
  const searchParams = useSearchParams();
  const enqueue = useSearchParamWriter();

  const filters = useMemo<T>(() => {
    const out = {} as T;
    for (const key in spec) {
      const raw = searchParams?.get(key) ?? null;
      const def = spec[key].defaultValue;
      if (raw == null) {
        out[key] = def;
      } else if (spec[key].allowed && !spec[key].allowed!.includes(raw as T[typeof key])) {
        out[key] = def;
      } else {
        out[key] = raw as T[typeof key];
      }
    }
    return out;
  }, [searchParams, spec]);

  const setFilters = useCallback(
    (patch: Partial<T>) => {
      const updates: PendingUpdate = {};
      for (const key in patch) {
        const value = patch[key];
        const def = spec[key].defaultValue;
        updates[key] = value === def || value == null ? null : (value as string);
      }
      enqueue(updates);
    },
    [enqueue, spec],
  );

  const reset = useCallback(() => {
    const updates: PendingUpdate = {};
    for (const key in spec) updates[key] = null;
    enqueue(updates);
  }, [enqueue, spec]);

  return [filters, setFilters, reset];
}

"use client";

// Local draft autosave (spec layer #9). Wraps any form value in debounced
// localStorage persistence so a dropped connection or a closed tab never loses a
// field report. Restores on mount; clear() on successful submit.
//
//   const { value, setValue, savedAt, restored, clear } = useDraft("debrief:STF-1", "");
//
// The production swap can additionally push the draft to IndexedDB + a "sync
// when online" queue; the call sites don't change.

import { useCallback, useEffect, useRef, useState } from "react";

export type DraftState<T> = {
  value: T;
  setValue: (v: T) => void;
  /** ISO timestamp of the last local save, or null. */
  savedAt: string | null;
  /** True when a previous draft was restored on mount. */
  restored: boolean;
  clear: () => void;
};

export function useDraft<T>(key: string, initial: T, opts: { debounceMs?: number } = {}): DraftState<T> {
  const { debounceMs = 600 } = opts;
  const storageKey = `edify-draft:${key}`;
  const [value, setValue] = useState<T>(initial);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hydrated = useRef(false);

  // Restore any saved draft once, on mount.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (raw) {
        const parsed = JSON.parse(raw) as { value: T; savedAt: string };
        setValue(parsed.value);
        setSavedAt(parsed.savedAt);
        setRestored(true);
      }
    } catch {
      /* corrupt draft — ignore */
    } finally {
      hydrated.current = true;
    }
  }, [storageKey]);

  // Debounced autosave. Skip the very first run so restore doesn't immediately
  // re-write what it just read.
  useEffect(() => {
    if (!hydrated.current) return;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      try {
        const at = new Date().toISOString();
        localStorage.setItem(storageKey, JSON.stringify({ value, savedAt: at }));
        setSavedAt(at);
      } catch {
        /* storage full / unavailable — fail silently, work continues */
      }
    }, debounceMs);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [value, storageKey, debounceMs]);

  const clear = useCallback(() => {
    try {
      localStorage.removeItem(storageKey);
    } catch {
      /* ignore */
    }
    setSavedAt(null);
    setRestored(false);
  }, [storageKey]);

  return { value, setValue, savedAt, restored, clear };
}

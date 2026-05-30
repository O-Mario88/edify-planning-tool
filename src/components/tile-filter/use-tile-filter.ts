"use client";

// Hook for the system-wide interactive tile filter pattern.
//
// Reads the active tile filter id from the URL (`?tileFilter=<id>`),
// returns the matching spec, and offers `setTileFilter(id | null)` to
// activate or clear. URL state is owned by the existing useUrlState
// primitive so deep-links, browser back, and reload all behave.
//
// The hook is intentionally generic — a page passes the registry of
// tiles it knows about, and the hook resolves the active spec. This
// means every dashboard wires the same hook to a different registry.

import { useCallback, useMemo } from "react";
import { useUrlState } from "@/hooks/use-url-state";
import type { TileFilterSpec } from "./types";

const NONE = "";

export type UseTileFilterReturn = {
  activeFilterId: string | null;
  activeFilter: TileFilterSpec | null;
  setTileFilter: (id: string | null) => void;
  resetTileFilter: () => void;
  isActive: (id: string) => boolean;
};

export function useTileFilter(
  registry: ReadonlyArray<TileFilterSpec>,
): UseTileFilterReturn {
  const [raw, setRaw] = useUrlState({ key: "tileFilter", defaultValue: NONE });

  const activeFilterId = raw === NONE ? null : raw;
  const activeFilter = useMemo(
    () => (activeFilterId ? registry.find((r) => r.id === activeFilterId) ?? null : null),
    [activeFilterId, registry],
  );

  const setTileFilter = useCallback(
    (id: string | null) => setRaw(id ?? NONE),
    [setRaw],
  );

  const resetTileFilter = useCallback(() => setRaw(NONE), [setRaw]);

  const isActive = useCallback(
    (id: string) => activeFilterId === id,
    [activeFilterId],
  );

  return {
    activeFilterId,
    activeFilter,
    setTileFilter,
    resetTileFilter,
    isActive,
  };
}

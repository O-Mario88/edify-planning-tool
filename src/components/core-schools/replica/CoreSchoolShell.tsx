"use client";

// Client shell for the Core School dashboard.
//
// Owns the active tile filter state (URL-backed via useTileFilter) and
// decides what the page renders:
//
//   • No active filter → full dashboard (KPI row, package progress,
//     analytics, tables, champion pipeline, bottom row).
//   • Active filter → focused detail view: KPI row stays visible so the
//     user can switch filters inline, the active package progress card
//     stays (so the funnel context is preserved), and below that the
//     ActiveTileFilterHeader + filtered school list replace every
//     unrelated section.
//
// The KPI row + package progress receive `activeFilterId` and an
// `onTileClick` so the same tile that triggers a filter can also flip
// it off — clicking an already-active tile clears the filter.

import { useCallback } from "react";
import {
  ActiveTileFilterHeader,
  TileFilterEmptyState,
  useTileFilter,
} from "@/components/tile-filter";
import { ReplicaKpiRow } from "./ReplicaKpiRow";
import { ReplicaPackageProgress } from "./ReplicaPackageProgress";
import { ReplicaAnalyticsRow } from "./ReplicaAnalyticsRow";
import { ReplicaTablesRow } from "./ReplicaTablesRow";
import { ReplicaBottomRow } from "./ReplicaBottomRow";
import { ChampionSchoolPipelineCard } from "@/components/cceo/ChampionSchoolPipelineCard";
import { CoreSchoolFilteredResultList } from "./CoreSchoolFilteredResultList";
import {
  CORE_TILE_FILTERS,
  getTileFilterCount,
  getTileFilterResults,
} from "./tile-filters";

export function CoreSchoolShell() {
  const { activeFilter, activeFilterId, setTileFilter, resetTileFilter } =
    useTileFilter(CORE_TILE_FILTERS);

  // Clicking an active tile clears the filter; clicking a different
  // tile flips to that filter. This keeps the tile row dual-purpose
  // and matches how users expect a "toggle pill" to behave.
  const onTileClick = useCallback(
    (id: string) => {
      if (activeFilterId === id) {
        resetTileFilter();
      } else {
        setTileFilter(id);
      }
    },
    [activeFilterId, setTileFilter, resetTileFilter],
  );

  const onExport = useCallback(() => {
    if (typeof window === "undefined" || !activeFilter) return;
    const rows = getTileFilterResults(activeFilter.id);
    const csv = toCsv(rows);
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8;" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `core-schools-${activeFilter.id}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [activeFilter]);

  if (activeFilter) {
    const rows = getTileFilterResults(activeFilter.id);
    const count = rows.length > 0 ? rows.length : getTileFilterCount(activeFilter.id);
    return (
      <div className="space-y-3 lg:space-y-4">
        {/* KPI row stays so the user can switch filters in-context. */}
        <ReplicaKpiRow activeFilterId={activeFilterId} onTileClick={onTileClick} />

        {/* Package progress stays for visit/training/package filters so
            the funnel context is preserved. For unrelated filters we
            hide it to keep the focus on the result list. */}
        {shouldShowPackageProgress(activeFilter.id) && (
          <ReplicaPackageProgress
            activeFilterId={activeFilterId}
            onTileClick={onTileClick}
          />
        )}

        <ActiveTileFilterHeader
          filter={activeFilter}
          count={count}
          onReset={resetTileFilter}
          onExport={onExport}
          breadcrumb="Core Schools"
        />

        {rows.length === 0 ? (
          <TileFilterEmptyState onReset={resetTileFilter} />
        ) : (
          <CoreSchoolFilteredResultList rows={rows} />
        )}
      </div>
    );
  }

  // Normal full dashboard
  return (
    <div className="space-y-3 lg:space-y-4">
      <ReplicaKpiRow activeFilterId={null} onTileClick={onTileClick} />
      <ReplicaPackageProgress activeFilterId={null} onTileClick={onTileClick} />
      <ReplicaAnalyticsRow />
      <ReplicaTablesRow />
      <ChampionSchoolPipelineCard />
      <ReplicaBottomRow activeFilterId={null} onTileClick={onTileClick} />
    </div>
  );
}

// Funnel context (package progress card) stays visible when the active
// filter came from the funnel itself (any pkg-* tile), or covers a
// visit / training / package / champion subset. For pure SSA / risk /
// summary tiles the focus is the school list, not the funnel.
function shouldShowPackageProgress(filterId: string): boolean {
  if (filterId.startsWith("pkg-")) return true;
  const spec = CORE_TILE_FILTERS.find((s) => s.id === filterId);
  if (!spec) return false;
  return (
    spec.category === "visit" ||
    spec.category === "training" ||
    spec.category === "package" ||
    spec.category === "champion"
  );
}

function toCsv(rows: ReturnType<typeof getTileFilterResults>): string {
  const headers = [
    "School", "District", "CCEO", "SSA Score", "Visits", "Trainings",
    "Package Status", "Status", "Next Action", "Evidence",
  ];
  const escape = (s: string | number) => {
    const str = String(s ?? "");
    return /[",\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
  };
  const body = rows
    .map((r) => [
      r.schoolName, r.district, r.cceo, r.ssaScore, r.visits, r.trainings,
      r.packageStatus, r.status, r.nextAction, r.evidenceStatus,
    ].map(escape).join(","))
    .join("\n");
  return `${headers.join(",")}\n${body}`;
}

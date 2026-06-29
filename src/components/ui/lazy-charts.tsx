"use client";

import dynamic from "next/dynamic";
import { ChartSkeleton } from "./ChartSkeleton";

// Centralised lazy wrappers for every Recharts-backed card. Recharts is
// the single biggest client-bundle dependency in the app; lazy-loading
// each card means routes don't pay for charts they don't render and
// charts no longer ship in the first JS payload of any dashboard.
//
// Usage:
//   import { CountryPerformanceChart } from "@/components/ui/lazy-charts";
//   <CountryPerformanceChart />

export const CountryPerformanceChart = dynamic(
  () => import("@/components/director/CountryPerformanceChart").then((m) => m.CountryPerformanceChart),
  { ssr: false, loading: () => <ChartSkeletonCard variant="bar" /> },
);

export const RegionalPerformanceCard = dynamic(
  () => import("@/components/director/CountryPerformanceChart").then((m) => m.RegionalPerformanceCard),
  { ssr: false, loading: () => <ChartSkeletonCard variant="bar" /> },
);

export const TeamPerformanceOverviewChart = dynamic(
  () => import("@/components/cpl/TeamPerformanceChart").then((m) => m.TeamPerformanceOverviewChart),
  { ssr: false, loading: () => <ChartSkeletonCard variant="bar" /> },
);

export const CoreSsaTrendCard = dynamic(
  () => import("@/components/cceo/CoreSsaTrendCard").then((m) => m.CoreSsaTrendCard),
  { ssr: false, loading: () => <ChartSkeletonCard variant="line" /> },
);

export const SsaTrendCard = dynamic(
  () => import("@/components/ssa/SsaTrendCard").then((m) => m.SsaTrendCard),
  { ssr: false, loading: () => <ChartSkeletonCard variant="line" /> },
);

export const DataQualityTrendChart = dynamic(
  () => import("@/components/impact/DataQualityTrendChart").then((m) => m.DataQualityTrendChart),
  { ssr: false, loading: () => <ChartSkeletonCard variant="line" /> },
);

export const QualityCheckStatusCard = dynamic(
  () => import("@/components/impact/QualityCheckStatusCard").then((m) => m.QualityCheckStatusCard),
  { ssr: false, loading: () => <ChartSkeletonCard variant="donut" /> },
);

export const BudgetByQuarterBars = dynamic(
  () => import("@/components/budget/BudgetCharts").then((m) => m.BudgetByQuarterBars),
  { ssr: false, loading: () => <ChartSkeletonCard variant="bar" /> },
);

export const MonthlyBurnReleases = dynamic(
  () => import("@/components/budget/BudgetCharts").then((m) => m.MonthlyBurnReleases),
  { ssr: false, loading: () => <ChartSkeletonCard variant="line" /> },
);

export const BudgetByDimensionBars = dynamic(
  () => import("@/components/budget/BudgetCharts").then((m) => m.BudgetByDimensionBars),
  { ssr: false, loading: () => <ChartSkeletonCard variant="bar" /> },
);

export const ProgramAdminDonut = dynamic(
  () => import("@/components/budget/BudgetCharts").then((m) => m.ProgramAdminDonut),
  { ssr: false, loading: () => <ChartSkeletonCard variant="donut" /> },
);

export const BudgetMixDonut = dynamic(
  () => import("@/components/budget/BudgetCharts").then((m) => m.BudgetMixDonut),
  { ssr: false, loading: () => <ChartSkeletonCard variant="donut" /> },
);

export const AnnualOverviewLines = dynamic(
  () => import("@/components/budget/BudgetCharts").then((m) => m.AnnualOverviewLines),
  { ssr: false, loading: () => <ChartSkeletonCard variant="line" /> },
);

function ChartSkeletonCard({ variant }: { variant: "bar" | "line" | "donut" }) {
  return (
    <section className="card p-3.5">
      <div className="mb-3 flex items-center gap-2">
        <div className="h-3 w-32 rounded bg-[var(--color-edify-soft)]/80 chart-skel-shimmer-mask" />
        <div className="ml-auto h-3 w-16 rounded bg-[var(--color-edify-soft)]/80" />
      </div>
      <ChartSkeleton variant={variant} height={260} />
    </section>
  );
}

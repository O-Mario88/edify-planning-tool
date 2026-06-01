// Analytics truth-layer — shared metric contract.
//
// Every analytics number is an AnalyticsMetric: it carries its definition, its
// source, the planned/completed/verified/donor-ready breakdown, the exact
// records behind the number (drilldown), and a data-quality verdict. The shape
// is a deliberate superset of donor-metrics' DonorMetric so the two converge in
// a later phase. Pure & client-safe.

import type { TileFilterEntityType } from "@/components/tile-filter/types";

export type AnalyticsMetricGroup =
  | "reach"
  | "pipeline"
  | "ssa"
  | "geography"
  | "impact"
  | "finance"
  | "verification"
  | "evidence";

export type MetricSource = "derived" | "estimated" | "pending_schema";

export type DataQualityLevel = "ok" | "caveat" | "blocked";

/** One record behind a metric — what the drilldown lists. */
export type DrilldownRecord = {
  id: string;
  entityType: TileFilterEntityType;
  title: string;
  subtitle?: string;
  schoolId?: string;
  district?: string;
  date?: string;
  status?: string;
  value?: number;
  /** Counted toward the headline vs excluded (shown muted in the drilldown). */
  contributesToCount: boolean;
};

/** The four workflow views every reach/activity metric separates. */
export type AnalyticsBreakdown = {
  planned: number;
  completed: number;
  verified: number;
  donorReady: number;
};

export type DataQuality = {
  level: DataQualityLevel;
  notes: string[];
};

export type AnalyticsMetric = {
  key: string;
  label: string;
  group: AnalyticsMetricGroup;
  value: number;
  /** What this number means (the spec §7 definition). */
  definition: string;
  source: MetricSource;
  breakdown: AnalyticsBreakdown;
  /** The exact rows behind the number — drilldown + export read these. */
  records: DrilldownRecord[];
  dataQuality: DataQuality;
  /** Optional headline-only target context (from computePeriodTarget). */
  target?: {
    expectedCumulative: number;
    paceStatus: string;
    gapToExpected: number;
  };
};

/** A pipeline funnel stage (planned → completed → verified → paid). */
export type FunnelStage = {
  key: string;
  label: string;
  count: number;
  records: DrilldownRecord[];
};

/** One row of the SSA intervention heatmap. */
export type HeatmapRow = {
  key: string;
  label: string;
  /** Average score per intervention area (0–10), undefined when no data. */
  scores: Record<string, number | undefined>;
};

/** A point on a trend line. */
export type TrendPoint = {
  period: string;
  value: number;
};

export type AnalyticsSnapshot = {
  scopeLabel: string;
  fyId: string;
  cycleTag: string;
  metrics: AnalyticsMetric[];
  pipeline: FunnelStage[];
  ssaHeatmap: { interventions: string[]; rows: HeatmapRow[] };
  trend: TrendPoint[];
  dataQuality: DataQuality;
};

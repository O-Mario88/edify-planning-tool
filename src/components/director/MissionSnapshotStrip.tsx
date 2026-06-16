import { Globe2 } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import type { DonorMetricSnapshot } from "@/lib/donor-metrics-types";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Country Mission Snapshot — the CD's "are we achieving the mission?"
// band. One dense MetricStrip of mission-level reach figures, sourced
// from the donor-metrics builder so the dashboard and the donor report
// can never disagree. Every cell is drillable.

const MISSION_KEYS: { key: string; href: string }[] = [
  { key: "schoolsReached",       href: "/donor-reporting/print" },
  { key: "studentsImpacted",     href: "/donor-reporting/print" },
  { key: "teachersTrained",      href: "/donor-reporting/print" },
  { key: "schoolLeadersTrained", href: "/donor-reporting/print" },
  { key: "districtsCovered",     href: "/analytics" },
  { key: "clustersReached",      href: "/analytics" },
  { key: "ssaCompleted",         href: "/ssa" },
  { key: "schoolsImproved",      href: "/ssa" },
  { key: "visitsCompleted",      href: "/analytics" },
  { key: "trainingsDelivered",   href: "/analytics" },
];

export function MissionSnapshotStrip({ snapshot }: { snapshot: DonorMetricSnapshot }) {
  // Mission reach figures are mock-derived (donor-metrics builder); withhold in prod.
  if (!isMockAllowed()) return <InsufficientData surface="the mission snapshot" />;
  const byKey = new Map(snapshot.metrics.map((m) => [m.key, m]));
  const metrics: MetricCell[] = MISSION_KEYS.flatMap(({ key, href }) => {
    const m = byKey.get(key);
    if (!m || m.value == null) return [];
    return [
      {
        key,
        label: m.label,
        value: m.value.toLocaleString(),
        href,
      } satisfies MetricCell,
    ];
  });

  return (
    <SectionCard icon={<Globe2 size={13} />} title="Country Mission Snapshot">
      <MetricStrip
        metrics={metrics}
        columns="grid-cols-2 sm:grid-cols-3 md:grid-cols-5 xl:grid-cols-10"
      />
      <p className="mt-2 text-[11px] muted leading-snug">
        Same builder as the donor report — deduplicated, scoped to {snapshot.scopeLabel || "the country"}, verified or confirmed only. Click any figure to drill in.
      </p>
    </SectionCard>
  );
}

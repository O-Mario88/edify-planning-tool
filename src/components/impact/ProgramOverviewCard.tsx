import { programTiles } from "@/lib/impact-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

export function ProgramOverviewCard() {
  const metrics: MetricCell[] = programTiles.map((t) => ({
    key: t.key,
    label: t.label,
    value: t.count,
    delta: { dir: "up", text: t.trend },
    href: t.href,
  }));

  return (
    <article className="card p-3.5 h-full flex flex-col">
      <h2 className="text-body-lg font-extrabold tracking-tight mb-3">Program Overview</h2>
      <MetricStrip bare className="flex-1" columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-5" metrics={metrics} />
    </article>
  );
}

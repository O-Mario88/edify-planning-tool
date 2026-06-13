import Link from "next/link";
import { ChevronRight } from "lucide-react";
import {
  leadershipImpactKpis,
  type LeadershipScope,
} from "@/lib/impact-mock";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";

const SCOPE_COPY: Record<LeadershipScope, { title: string; subtitle: string }> = {
  cpl: {
    title:    "Data Quality — My Team",
    subtitle: "Verification posture for the records uploaded by CCEOs you supervise.",
  },
  director: {
    title:    "Data Quality — Country",
    subtitle: "Verification posture across every region and program in your country.",
  },
  rvp: {
    title:    "Data Quality — Region",
    subtitle: "Verification posture across every country in your region.",
  },
};

// Surfaces the five Impact Assessment KPIs (Total / Verified / Pending /
// Failed QC / Partners Active) scoped to a leader's view, so leadership
// dashboards reuse the same numbers the M&E console reports against.
export function LeadershipImpactSnapshot({ variant }: { variant: LeadershipScope }) {
  const rows  = leadershipImpactKpis[variant];
  const copy  = SCOPE_COPY[variant];

  const metrics: MetricCell[] = rows.map((k) => ({
    key: k.key,
    label: k.label,
    value: k.value,
    caption: k.share ? `(${k.share})` : undefined,
    delta: { dir: k.trend.tone === "up" ? "up" : "down", text: k.trend.label },
    href: k.href,
  }));

  return (
    <article className="card p-3.5" id="impact-snapshot">
      <header className="flex items-baseline justify-between gap-2 mb-3">
        <div className="min-w-0">
          <h2 className="text-body-lg lg:text-[15px] font-extrabold tracking-tight">{copy.title}</h2>
          <p className="text-[11.5px] muted leading-snug">{copy.subtitle}</p>
        </div>
        <Link
          href="/dashboards/impact"
          className="hidden md:inline-flex h-9 px-3 rounded-xl border border-[var(--color-edify-border)] text-[11.5px] font-semibold items-center gap-1 hover:bg-[var(--color-edify-soft)]/60 shrink-0"
        >
          Open M&amp;E console
          <ChevronRight size={12} />
        </Link>
      </header>

      <MetricStrip bare columns="grid-cols-2 md:grid-cols-3 lg:grid-cols-5" metrics={metrics} />
    </article>
  );
}

import Link from "next/link";
import {
  Database,
  ShieldCheck,
  Clock,
  AlertOctagon,
  Users,
  ArrowUpRight,
  ArrowDownRight,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import {
  leadershipImpactKpis,
  type ImpactKpi,
  type LeadershipScope,
} from "@/lib/impact-mock";
import { cn } from "@/lib/utils";

const ICON: Record<ImpactKpi["icon"], LucideIcon> = {
  database:     Database,
  shieldCheck:  ShieldCheck,
  clock:        Clock,
  alertOctagon: AlertOctagon,
  users:        Users,
};

const TONE: Record<ImpactKpi["iconTone"], string> = {
  violet: "bg-violet-100  text-violet-700",
  green:  "bg-emerald-100 text-emerald-700",
  amber:  "bg-amber-100   text-amber-700",
  rose:   "bg-rose-100    text-rose-600",
  blue:   "bg-sky-100     text-sky-700",
};

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

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2.5">
        {rows.map((k) => (
          <KpiTile key={k.key} kpi={k} />
        ))}
      </div>
    </article>
  );
}

function KpiTile({ kpi }: { kpi: ImpactKpi }) {
  const Icon  = ICON[kpi.icon];
  const tone  = TONE[kpi.iconTone];
  const Arrow = kpi.trend.tone === "up" ? ArrowUpRight : ArrowDownRight;
  const trend = kpi.trend.tone === "up" ? "text-emerald-600" : "text-rose-600";

  return (
    <Link
      href={kpi.href}
      className="rounded-xl border border-[var(--color-edify-border)] p-3 flex flex-col gap-1.5 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <span className={cn("w-8 h-8 rounded-full grid place-items-center shrink-0", tone)}>
          <Icon size={13} />
        </span>
        <span className="text-caption muted font-semibold text-right leading-tight line-clamp-2">
          {kpi.label}
        </span>
      </div>
      <div className="flex items-baseline gap-1.5 mt-0.5">
        <span className="text-[20px] font-extrabold tabular leading-none">{kpi.value}</span>
        {kpi.share && <span className="text-[11px] muted font-semibold">({kpi.share})</span>}
      </div>
      <div className={cn("text-caption font-semibold inline-flex items-center gap-0.5", trend)}>
        <Arrow size={10} />
        {kpi.trend.label}
      </div>
    </Link>
  );
}

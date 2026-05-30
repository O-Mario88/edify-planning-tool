// Pure presentational leaf components extracted from CceoMyTargetsView.
// No closure dependencies on parent state — safe to import anywhere.

import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PlannedActivity } from "@/lib/cceo-my-targets-engine";

export function formatM(value: number): string {
  if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(0)}K`;
  return `${value}`;
}

export function isToday(a: PlannedActivity): boolean {
  const todayDay = new Date().toLocaleDateString("en-US", { weekday: "short" }).slice(0, 3);
  return a.scheduledDay === todayDay;
}

export function Strong({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn("font-extrabold text-[var(--color-edify-text)] tabular", className)}>{children}</span>;
}

export function Fact({ label, value }: { label: string; value: string }) {
  return (
    <li className="rounded-lg bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] px-2.5 py-1.5">
      <div className="muted font-bold uppercase tracking-wide text-[9.5px]">{label}</div>
      <div className="text-[13px] font-extrabold tabular leading-tight">{value}</div>
    </li>
  );
}

export function ProgressRing({
  pct,
  size = 56,
  stroke = 6,
  color = "var(--color-edify-primary)",
}: {
  pct: number;
  size?: number;
  stroke?: number;
  color?: string;
}) {
  const r = (size - stroke) / 2;
  const circ = 2 * Math.PI * r;
  const offset = circ * (1 - Math.max(0, Math.min(100, pct)) / 100);
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
      <circle cx={size / 2} cy={size / 2} r={r} stroke="#eef2f4" strokeWidth={stroke} fill="none" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        stroke={color}
        strokeWidth={stroke}
        fill="none"
        strokeDasharray={circ}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text
        x="50%"
        y="52%"
        textAnchor="middle"
        dominantBaseline="middle"
        fontSize="11"
        fontWeight="800"
        fill="var(--color-edify-text)"
      >
        {Math.round(pct)}%
      </text>
    </svg>
  );
}

export function MiniBar({ pct, color = "var(--color-edify-primary)" }: { pct: number; color?: string }) {
  return (
    <div className="w-[72px] h-2 rounded-full bg-[#eef2f4] overflow-hidden">
      <div
        className="h-full rounded-full"
        style={{ width: `${Math.max(0, Math.min(100, pct))}%`, backgroundColor: color }}
      />
    </div>
  );
}

const SECONDARY_STAT_TONE = {
  edify: "bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-primary)]",
  green: "bg-emerald-100  text-emerald-700",
  amber: "bg-amber-100    text-amber-700",
  rose: "bg-rose-100     text-rose-700",
  sky: "bg-sky-100      text-sky-700",
  violet: "bg-violet-100   text-violet-700",
} as const;

export function SecondaryStat({
  Icon,
  label,
  value,
  sub,
  tone,
}: {
  Icon: LucideIcon;
  label: string;
  value: string | number;
  sub?: string;
  tone: "edify" | "green" | "amber" | "rose" | "sky" | "violet";
}) {
  return (
    <div className="card p-3.5 h-full flex items-center gap-3">
      <span className={cn("h-10 w-10 rounded-xl grid place-items-center shrink-0", SECONDARY_STAT_TONE[tone])}>
        <Icon size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-caption muted font-semibold uppercase tracking-wide truncate">{label}</div>
        <div className="text-[22px] font-extrabold tabular leading-tight tracking-tight truncate">{value}</div>
        {sub && <div className="text-caption muted truncate">{sub}</div>}
      </div>
    </div>
  );
}

const HERO_KPI_TONE = {
  edify: "from-[var(--color-edify-soft)]/50  to-white",
  violet: "from-violet-50/80  to-white",
  amber: "from-amber-50/80   to-white",
  green: "from-emerald-50/80 to-white",
  rose: "from-rose-50/80    to-white",
  sky: "from-sky-50/80     to-white",
} as const;

const HERO_KPI_ICON_BG = {
  edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  violet: "bg-violet-100  text-violet-700",
  amber: "bg-amber-100   text-amber-700",
  green: "bg-emerald-100 text-emerald-700",
  rose: "bg-rose-100    text-rose-700",
  sky: "bg-sky-100     text-sky-700",
} as const;

export function HeroKpiCard({
  Icon,
  label,
  value,
  sub,
  tone,
  accent,
}: {
  Icon: LucideIcon;
  label: string;
  value: string;
  sub?: string;
  tone: "edify" | "violet" | "amber" | "green" | "rose" | "sky";
  accent: React.ReactNode;
}) {
  return (
    <div
      className={cn(
        "card p-3.5 bg-gradient-to-br border-[var(--color-edify-border)] h-full flex flex-col justify-between gap-3",
        HERO_KPI_TONE[tone],
      )}
    >
      <div className="flex items-center gap-2.5">
        <span className={cn("h-9 w-9 rounded-xl grid place-items-center shrink-0", HERO_KPI_ICON_BG[tone])}>
          <Icon size={15} />
        </span>
        <span className="text-[11px] muted font-semibold uppercase tracking-wide truncate">{label}</span>
      </div>
      <div className="flex items-end justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-[34px] sm:text-[36px] font-extrabold tabular leading-none tracking-tight truncate">
            {value}
          </div>
          {sub && <div className="text-[11.5px] muted mt-1 truncate">{sub}</div>}
        </div>
        <div className="shrink-0">{accent}</div>
      </div>
    </div>
  );
}

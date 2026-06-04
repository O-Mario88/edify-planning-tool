// Budget KPI strip — two-tier hierarchy. KPIs flagged `hero` render large
// (the decision-driving numbers a leader lands on first); the rest render as a
// compact secondary strip. With no hero flags it falls back to a uniform grid.

import { ArrowUp, ArrowDown, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type BudgetKpi = {
  key: string;
  label: string;
  value: string;
  caption?: string;
  delta?: string;
  deltaTone?: "up" | "down";
  Icon: LucideIcon;
  tone?: string; // tailwind classes for the icon chip
  hero?: boolean; // promote to the prominent top tier
};

const ICON_FALLBACK = "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]";

// Static column maps (Tailwind can't see interpolated class names).
const HERO_COLS: Record<number, string> = { 2: "lg:grid-cols-2", 3: "lg:grid-cols-3", 4: "lg:grid-cols-4" };
const MINI_COLS: Record<number, string> = { 3: "sm:grid-cols-3", 4: "sm:grid-cols-4", 5: "sm:grid-cols-3 lg:grid-cols-5", 6: "sm:grid-cols-3 lg:grid-cols-6" };

function Delta({ delta, tone }: { delta: string; tone?: "up" | "down" }) {
  return (
    <span className={cn(
      "text-[10px] font-bold inline-flex items-center gap-0.5 shrink-0 tabular",
      tone === "down" ? "text-rose-600" : "text-emerald-600",
    )}>
      {tone === "down" ? <ArrowDown size={9} /> : <ArrowUp size={9} />}{delta}
    </span>
  );
}

function HeroKpi({ k }: { k: BudgetKpi }) {
  return (
    <div className="card px-4 py-3.5 flex items-start gap-3">
      <span className={cn("h-9 w-9 rounded-lg grid place-items-center shrink-0", k.tone ?? ICON_FALLBACK)}>
        <k.Icon size={17} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[11px] font-semibold muted leading-tight truncate">{k.label}</div>
        <div className="text-[21px] font-extrabold tabular leading-tight mt-0.5 truncate" title={k.value}>{k.value}</div>
        <div className="flex items-center justify-between gap-2 mt-1 min-h-[15px]">
          {k.caption ? <span className="text-[10.5px] muted leading-tight truncate">{k.caption}</span> : <span />}
          {k.delta && <Delta delta={k.delta} tone={k.deltaTone} />}
        </div>
      </div>
    </div>
  );
}

function MiniKpi({ k }: { k: BudgetKpi }) {
  return (
    <div className="card px-3 py-2" title={k.caption}>
      <div className="flex items-center gap-1.5">
        <span className={cn("h-4 w-4 rounded grid place-items-center shrink-0", k.tone ?? ICON_FALLBACK)}>
          <k.Icon size={10} />
        </span>
        <span className="text-[10px] font-semibold muted leading-tight truncate">{k.label}</span>
      </div>
      <div className="flex items-center justify-between gap-1 mt-1">
        <span className="text-[13.5px] font-extrabold tabular leading-none truncate" title={k.value}>{k.value}</span>
        {k.delta && <Delta delta={k.delta} tone={k.deltaTone} />}
      </div>
    </div>
  );
}

export function BudgetKpiRow({ items }: { items: BudgetKpi[] }) {
  const heroes = items.filter((i) => i.hero);

  // No hierarchy declared → keep the original uniform strip.
  if (heroes.length === 0) {
    return (
      <section className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-2.5">
        {items.map((k) => <MiniKpi key={k.key} k={k} />)}
      </section>
    );
  }

  const rest = items.filter((i) => !i.hero);
  return (
    <div className="space-y-2.5">
      <section className={cn("grid grid-cols-2 gap-3", HERO_COLS[heroes.length] ?? "lg:grid-cols-4")}>
        {heroes.map((k) => <HeroKpi key={k.key} k={k} />)}
      </section>
      {rest.length > 0 && (
        <section className={cn("grid grid-cols-2 gap-2", MINI_COLS[rest.length] ?? "sm:grid-cols-4")}>
          {rest.map((k) => <MiniKpi key={k.key} k={k} />)}
        </section>
      )}
    </div>
  );
}

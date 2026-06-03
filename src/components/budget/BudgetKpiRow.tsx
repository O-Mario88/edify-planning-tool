// Budget KPI strip (8 cards) — icon + label + value + caption + delta vs prior FY.

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
};

export function BudgetKpiRow({ items }: { items: BudgetKpi[] }) {
  return (
    <section className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-2.5">
      {items.map((k) => (
        <div key={k.key} className="card px-3 py-2.5">
          <div className="flex items-center gap-1.5">
            <span className={cn("h-5 w-5 rounded-md grid place-items-center shrink-0", k.tone ?? "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]")}>
              <k.Icon size={12} />
            </span>
            <span className="text-[10px] font-semibold muted leading-tight truncate">{k.label}</span>
          </div>
          <div className="text-[15px] font-extrabold tabular leading-none mt-1.5 truncate" title={k.value}>{k.value}</div>
          {/* caption + delta share one row — no floating dead space below */}
          <div className="flex items-center justify-between gap-1 mt-1 min-h-[14px]">
            {k.caption ? <span className="text-[10px] muted leading-tight truncate">{k.caption}</span> : <span />}
            {k.delta && (
              <span className={cn("text-[10px] font-bold inline-flex items-center gap-0.5 shrink-0",
                k.deltaTone === "down" ? "text-rose-600" : "text-emerald-600")}>
                {k.deltaTone === "down" ? <ArrowDown size={9} /> : <ArrowUp size={9} />}{k.delta}
              </span>
            )}
          </div>
        </div>
      ))}
    </section>
  );
}

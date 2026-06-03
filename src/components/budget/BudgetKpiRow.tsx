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
        <div key={k.key} className="card rounded-2xl p-3">
          <div className="flex items-center gap-1.5">
            <span className={cn("h-6 w-6 rounded-lg grid place-items-center shrink-0", k.tone ?? "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]")}>
              <k.Icon size={13} />
            </span>
            <span className="text-[10.5px] font-semibold muted leading-tight truncate">{k.label}</span>
          </div>
          <div className="text-[15px] font-extrabold tabular leading-tight mt-1.5 truncate" title={k.value}>{k.value}</div>
          {k.caption && <div className="text-[10px] muted leading-tight mt-0.5 truncate">{k.caption}</div>}
          {k.delta && (
            <div className={cn("text-[10.5px] font-bold mt-1 inline-flex items-center gap-0.5",
              k.deltaTone === "down" ? "text-rose-600" : "text-emerald-600")}>
              {k.deltaTone === "down" ? <ArrowDown size={10} /> : <ArrowUp size={10} />}{k.delta}
            </div>
          )}
        </div>
      ))}
    </section>
  );
}

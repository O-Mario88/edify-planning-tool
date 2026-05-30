"use client";

import {
  Database,
  RotateCcw,
  Building2,
  GraduationCap,
  ShieldAlert,
  Users,
  ArrowUpRight,
  ArrowDownRight,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { operationalRisks, type OperationalRiskTile } from "@/lib/director-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<OperationalRiskTile["icon"], LucideIcon> = {
  database:      Database,
  rotateCcw:     RotateCcw,
  schoolX:       Building2,
  graduationCap: GraduationCap,
  shieldAlert:   ShieldAlert,
  users:         Users,
};

const toneFrame: Record<OperationalRiskTile["tone"], string> = {
  red:      "bg-[#fef2f2] text-red-700",
  amber:    "bg-orange-100 text-[#9a3412]",
  yellow:   "bg-[#fef9c3] text-[#854d0e]",
  violet:   "bg-violet-100 text-violet-700",
  rose:     "bg-rose-100 text-rose-700",
  lavender: "bg-[#eef2ff] text-[#4338ca]",
};

const valueColor: Record<OperationalRiskTile["tone"], string> = {
  red:      "text-red-700",
  amber:    "text-[#9a3412]",
  yellow:   "text-[#854d0e]",
  violet:   "text-violet-700",
  rose:     "text-rose-700",
  lavender: "text-[#4338ca]",
};

export function OperationalRiskBacklogRow() {
  return (
    <SectionCard
      icon={<ShieldAlert size={13} />}
      title="Operational Risk & Backlog"
      actions={
        <a className="text-[12px] font-semibold text-[var(--color-edify-primary)]" href="#operational-risk">
          View full risk register →
        </a>
      }
    >
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-2 2xl:grid-cols-3 gap-2 lg:gap-3">
        {operationalRisks.map((r, i) => {
          const Icon = iconMap[r.icon];
          const staggerCls = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][i] ?? "";
          return (
            <div
              key={r.key}
              className={cn(
                "card card-lift cursor-default tile-in p-2.5 overflow-hidden",
                staggerCls,
              )}
            >
              <div className={cn("w-8 h-8 rounded-md grid place-items-center shrink-0", toneFrame[r.tone])}>
                <Icon size={14} />
              </div>
              <div className={cn(
                "text-[20px] font-extrabold tabular mt-2 leading-none truncate num-hero",
                valueColor[r.tone],
                r.tone === "rose" || r.tone === "red"     ? "glow-rose"
                  : r.tone === "amber" || r.tone === "yellow" ? "glow-amber"
                  : "glow-slate",
              )}>
                {r.value}
              </div>
              <div className="text-caption muted font-semibold leading-tight mt-1 line-clamp-2 min-h-[26px]">
                {r.label}
              </div>
              <div
                className={cn(
                  "text-caption font-semibold mt-1 flex items-center gap-1 truncate",
                  r.deltaTone === "up"
                    ? "text-[var(--color-danger)]"
                    : "text-[var(--color-success)]",
                )}
              >
                {r.deltaTone === "up" ? <ArrowUpRight size={10} className="shrink-0" /> : <ArrowDownRight size={10} className="shrink-0" />}
                <span className="truncate">{r.delta} <span className="muted font-medium">vs Apr</span></span>
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

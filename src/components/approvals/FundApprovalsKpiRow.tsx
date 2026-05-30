"use client";

import {
  ArrowDownRight,
  ArrowUpRight,
  Building2,
  CheckCircle2,
  Clock,
  Folder,
  RotateCcw,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { fundApprovalKpis, type FundApprovalKpi } from "@/lib/fund-approvals-mock";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<FundApprovalKpi["icon"], LucideIcon> = {
  wallet:      Wallet,
  clock:       Clock,
  checkCircle: CheckCircle2,
  rotateCcw:   RotateCcw,
  folder:      Folder,
  building:    Building2,
};

const ICON_TONE: Record<FundApprovalKpi["iconTone"], { bg: string; fg: string }> = {
  edify:   { bg: "bg-[var(--color-edify-soft)]", fg: "text-[var(--color-edify-primary)]" },
  amber:   { bg: "bg-amber-100",                 fg: "text-amber-700" },
  emerald: { bg: "bg-emerald-100",               fg: "text-emerald-700" },
  blue:    { bg: "bg-sky-100",                   fg: "text-sky-700" },
  violet:  { bg: "bg-violet-100",                fg: "text-violet-700" },
  slate:   { bg: "bg-slate-100",                 fg: "text-slate-600" },
};

const GLOW: Record<FundApprovalKpi["iconTone"], string> = {
  edify:   "glow-slate",
  amber:   "glow-amber",
  emerald: "glow-emerald",
  blue:    "glow-slate",
  violet:  "glow-slate",
  slate:   "glow-slate",
};

export function FundApprovalsKpiRow() {
  return (
    <section className="px-3 sm:px-4 lg:px-6 pb-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5">
        {fundApprovalKpis.map((k, i) => (
          <Tile key={k.key} k={k} idx={i} />
        ))}
      </div>
    </section>
  );
}

function Tile({ k, idx }: { k: FundApprovalKpi; idx: number }) {
  const Icon = ICON_MAP[k.icon];
  const tone = ICON_TONE[k.iconTone];
  const stagger = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][idx] ?? "";
  const up = k.deltaTone === "up";
  return (
    <div className={cn("card card-lift cursor-default tile-in p-3", stagger)}>
      <div className="flex items-start gap-2.5">
        <span className={cn("w-9 h-9 rounded-full grid place-items-center shrink-0", tone.bg)}>
          <Icon size={15} className={tone.fg} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] muted font-bold uppercase tracking-wide leading-tight line-clamp-2">
            {k.label}
          </div>
        </div>
      </div>

      <div className={cn(
        "text-[18px] font-extrabold tabular leading-none mt-2.5 text-slate-900 num-hero",
        GLOW[k.iconTone],
      )}>
        {k.value}
      </div>

      <div className="mt-1.5 flex items-center gap-1.5 text-caption min-w-0">
        {k.delta && (
          <span className={cn(
            "inline-flex items-center gap-0.5 font-bold shrink-0",
            up ? "text-emerald-700" : "text-rose-700",
          )}>
            {up ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
            {k.delta}
          </span>
        )}
        {k.caption && (
          <span className="muted font-semibold truncate">{k.caption}</span>
        )}
      </div>
    </div>
  );
}

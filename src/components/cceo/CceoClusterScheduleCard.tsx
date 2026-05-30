"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  CalendarRange,
  CheckCircle2,
  Clock,
  Calendar,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  cceoClusterSchedule,
  type CceoClusterReadiness,
} from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

const READINESS_TONE: Record<CceoClusterReadiness, { chip: string; dot: string; icon: LucideIcon }> = {
  "Ready":       { chip: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500", icon: CheckCircle2 },
  "In Progress": { chip: "bg-amber-50   text-amber-700",   dot: "bg-amber-500",   icon: Clock        },
  "Planned":     { chip: "bg-slate-50   text-slate-600",   dot: "bg-slate-400",   icon: Calendar     },
};

export function CceoClusterScheduleCard() {
  return (
    <SectionCard
      icon={<CalendarRange size={13} />}
      title="Cluster Schedule"
      subtitle="May 2025"
      actions={
        <Link
          href="/calendar"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View Calendar
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      <div className="rounded-xl border border-[var(--color-edify-border)] bg-white overflow-hidden">
        <div className="grid grid-cols-[1.8fr_72px_80px_110px] gap-2 px-3 py-2 bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600 font-bold">
          <div>Cluster</div>
          <div className="text-right">Date</div>
          <div>District</div>
          <div>Readiness</div>
        </div>
        <div className="max-h-[224px] overflow-y-auto scrollbar divide-y divide-[var(--color-edify-divider)]">
          {cceoClusterSchedule.map((c) => {
            const tone = READINESS_TONE[c.readiness];
            const Icon = tone.icon;
            return (
              <div
                key={c.key}
                className="grid grid-cols-[1.8fr_72px_80px_110px] gap-2 px-3 py-2.5 items-center text-[11.5px]"
              >
                <div className="font-bold text-slate-900 leading-tight truncate">{c.cluster}</div>
                <div className="text-right tabular muted">{c.date}</div>
                <div className="muted">{c.district}</div>
                <div>
                  <span className={cn("inline-flex items-center gap-1.5 px-2 py-[2px] rounded-md text-caption font-extrabold", tone.chip)}>
                    <Icon size={11} />
                    {c.readiness}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11px] muted">
        Readiness reflects pre-cluster prep: materials, headcount, and venue confirmations.
      </div>
    </SectionCard>
  );
}

"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Activity,
  BookOpen,
  Clipboard,
  Footprints,
  GraduationCap,
  RotateCw,
  School,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { cceoMonthlyActivityBreakdown } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

// Pick a distinct icon per activity type so the row left-side reads at
// a glance — the eye learns the legend after two visits.
const ICON_FOR: Record<string, LucideIcon> = {
  cluster:     GraduationCap,
  school_me:   School,
  follow_part: Footprints,
  ssa:         ShieldCheck,
  in_school:   Activity,
  lessons:     BookOpen,
  handover:    Clipboard,
};

export function CceoMonthlyActivityBreakdownCard() {
  const b = cceoMonthlyActivityBreakdown;
  return (
    <SectionCard
      icon={<RotateCw size={13} />}
      title="Monthly Activity Breakdown"
      actions={
        <Link
          href="/planning"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      <ul className="space-y-2">
        {b.rows.map((r) => {
          const Icon = ICON_FOR[r.key] ?? Activity;
          return (
            <li key={r.key} className="flex items-center gap-2.5">
              <Icon size={13} className="text-[var(--color-edify-muted)] shrink-0" />
              <span className="text-[11.5px] font-semibold leading-tight flex-1 min-w-0 truncate max-w-[180px]">
                {r.label}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${Math.min(100, r.pct * 3)}%`, backgroundColor: r.barColor }}
                />
              </div>
              <span className="text-[11.5px] font-extrabold tabular shrink-0 w-[64px] text-right whitespace-nowrap">
                <span className="text-slate-900">{r.count}</span>
                <span className="muted font-semibold"> ({r.pct}%)</span>
              </span>
            </li>
          );
        })}
      </ul>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex items-center justify-between text-[11.5px]">
        <span className="font-bold text-slate-700">Total Activities</span>
        <span className="inline-flex items-baseline gap-1.5">
          <span className="text-[16px] font-extrabold tabular text-slate-900">{b.totalActivities}</span>
          <span className={cn(
            "inline-flex items-center gap-0.5 font-bold text-[11px]",
            b.totalDeltaTone === "up" ? "text-emerald-700" : "text-rose-700",
          )}>
            <ArrowUpRight size={11} />
            {b.totalDelta}
          </span>
        </span>
      </div>
    </SectionCard>
  );
}

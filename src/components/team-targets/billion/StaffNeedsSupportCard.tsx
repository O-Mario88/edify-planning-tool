"use client";

import Link from "next/link";
import {
  AlertOctagon,
  AlertTriangle,
  ArrowUpRight,
  Building2,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  staffNeedsSupport,
  type StaffNeedsSupportItem,
} from "@/lib/team-targets-billion-mock";
import { cn } from "@/lib/utils";

const SEVERITY_TONE: Record<StaffNeedsSupportItem["severity"], { iconBg: string; iconColor: string; icon: LucideIcon; chip: string; edge: string }> = {
  Critical: { iconBg: "bg-rose-100",  iconColor: "text-rose-600",  icon: AlertOctagon,   chip: "bg-rose-50 text-rose-700 border-rose-200",     edge: "border-l-rose-500 bg-rose-50/30" },
  High:     { iconBg: "bg-amber-100", iconColor: "text-amber-600", icon: AlertTriangle,  chip: "bg-amber-50 text-amber-700 border-amber-200",  edge: "border-l-amber-500" },
};

// Staff Needs Support — team-shaped "what's broken?" surface. Replaces
// the my-targets Needs Attention card. Each row is one staff member
// flagged by the early-warning / mid-year-below-40 / critical-risk
// triggers, with their achievement %, regional context, and the gap.
export function StaffNeedsSupportCard() {
  return (
    <SectionCard
      icon={<AlertOctagon size={13} className="text-rose-600" />}
      title="Staff Needs Support"
      actions={
        <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[10px] font-extrabold bg-rose-50 text-rose-700 border border-rose-200">
          {staffNeedsSupport.criticalCount} Critical · {staffNeedsSupport.highCount} High
        </span>
      }
    >
      <ul className="space-y-2">
        {staffNeedsSupport.items.map((s) => {
          const tone = SEVERITY_TONE[s.severity];
          const Icon = tone.icon;
          return (
            <li
              key={s.key}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] border-l-[3px] p-3 flex items-start gap-3 bg-white",
                tone.edge,
              )}
            >
              <div className="w-9 h-9 rounded-full bg-gradient-to-br from-slate-500 to-slate-700 text-white text-[11px] font-extrabold grid place-items-center shrink-0 shadow-sm">
                {s.initials}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-body font-extrabold leading-tight text-slate-900 truncate">
                    {s.staffName}
                  </div>
                  <span className="text-[11px] font-extrabold tabular text-rose-700 whitespace-nowrap shrink-0">
                    {s.achievementPct}%
                  </span>
                </div>
                <div className="text-caption muted leading-snug inline-flex items-center gap-1 mt-0.5">
                  <Building2 size={10} />
                  {s.region} · {s.trigger}
                </div>
                <div className="text-caption mt-1 inline-flex items-center gap-1.5 text-slate-700">
                  <Icon size={11} className={tone.iconColor} />
                  <span className="font-semibold">{s.gap}</span>
                </div>
              </div>
              <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap border shrink-0 self-start", tone.chip)}>
                {s.severity}
              </span>
            </li>
          );
        })}
      </ul>

      <Link
        href="/team-targets"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--color-edify-primary)] hover:underline"
      >
        View All support reviews
        <ArrowUpRight size={11} />
      </Link>
    </SectionCard>
  );
}

"use client";

import Link from "next/link";
import {
  AlertOctagon,
  AlertTriangle,
  ArrowUpRight,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  needsAttention,
  type NeedsAttentionItem,
} from "@/lib/my-targets-billion-mock";
import { cn } from "@/lib/utils";

const SEVERITY_TONE: Record<NeedsAttentionItem["severity"], { iconBg: string; iconColor: string; icon: LucideIcon; chip: string }> = {
  Critical: { iconBg: "bg-rose-100",  iconColor: "text-rose-600",  icon: AlertOctagon,   chip: "bg-rose-50 text-rose-700 border-rose-200" },
  High:     { iconBg: "bg-amber-100", iconColor: "text-amber-600", icon: AlertTriangle,  chip: "bg-amber-50 text-amber-700 border-amber-200" },
};

export function NeedsAttentionCard() {
  return (
    <SectionCard
      icon={<AlertOctagon size={13} className="text-rose-600" />}
      title="Needs Attention"
      actions={
        <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[10px] font-extrabold bg-rose-50 text-rose-700 border border-rose-200">
          {needsAttention.criticalCount} Critical
        </span>
      }
    >
      <ul className="space-y-2">
        {needsAttention.items.map((item) => {
          const tone = SEVERITY_TONE[item.severity];
          const Icon = tone.icon;
          return (
            <li
              key={item.key}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] border-l-[3px] p-3 flex items-start gap-3 bg-white",
                item.severity === "Critical" ? "border-l-rose-500 bg-rose-50/30" : "border-l-amber-500",
              )}
            >
              <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", tone.iconBg)}>
                <Icon size={14} className={tone.iconColor} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-body font-extrabold leading-tight text-slate-900">{item.title}</div>
                <div className="text-[11px] muted leading-snug mt-0.5">{item.detail}</div>
              </div>
              <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap border shrink-0", tone.chip)}>
                {item.severity}
              </span>
            </li>
          );
        })}
      </ul>

      <Link
        href="/notifications"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--color-edify-primary)] hover:underline"
      >
        View All Gaps & Warnings
        <ArrowUpRight size={11} />
      </Link>
    </SectionCard>
  );
}

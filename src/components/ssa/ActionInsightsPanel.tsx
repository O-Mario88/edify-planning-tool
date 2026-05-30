"use client";

import Link from "next/link";
import {
  AlertTriangle,
  AlertCircle,
  TrendingUp,
  ArrowRight,
  ShieldAlert,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { actionInsights, type ActionInsight } from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

const toneFrame: Record<ActionInsight["tone"], string> = {
  danger:  "bg-rose-50 border-rose-200",
  warning: "bg-amber-50 border-amber-200",
  success: "bg-emerald-50 border-emerald-200",
  info:    "bg-[var(--color-edify-soft)] border-[var(--color-edify-border)]",
};
const toneIcon: Record<ActionInsight["tone"], string> = {
  danger:  "bg-rose-100 text-rose-700",
  warning: "bg-amber-100 text-amber-700",
  success: "bg-emerald-100 text-emerald-700",
  info:    "bg-white text-[var(--color-edify-primary)]",
};
const toneIconComp: Record<ActionInsight["tone"], LucideIcon> = {
  danger:  AlertCircle,
  warning: AlertTriangle,
  success: TrendingUp,
  info:    ShieldAlert,
};

export function ActionInsightsPanel() {
  return (
    <SectionCard title="SSA Insights & Recommendations">
      {/* Cards flex to fill the card height so the panel sits level
          with whatever it's paired against — no dead space. */}
      <div className="flex-1 flex flex-col gap-2.5">
        {actionInsights.map((a) => {
          const Icon = toneIconComp[a.tone];
          return (
            <Link
              key={a.id}
              href={a.href}
              className={cn(
                "flex-1 flex items-center gap-3 rounded-xl border px-3.5 py-3 hover:opacity-95 transition-opacity",
                toneFrame[a.tone],
              )}
            >
              <span className={cn("w-9 h-9 rounded-lg grid place-items-center shrink-0", toneIcon[a.tone])}>
                <Icon size={16} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-body font-bold leading-tight">{a.title}</div>
                <div className="text-[11px] muted mt-0.5 leading-snug">{a.body}</div>
              </div>
              <ArrowRight size={13} className="text-[var(--color-edify-muted)] shrink-0" />
            </Link>
          );
        })}
      </div>
    </SectionCard>
  );
}

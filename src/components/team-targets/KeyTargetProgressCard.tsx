"use client";

import { Target, GraduationCap, MapPin, ClipboardCheck, Cloud, Building2, type LucideIcon } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { keyTargetProgress } from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

const ICON: Record<string, LucideIcon> = {
  training: GraduationCap,
  visits:   MapPin,
  ssa:      ClipboardCheck,
  sf:       Cloud,
  core:     Building2,
};

export function KeyTargetProgressCard() {
  return (
    <SectionCard
      icon={<Target size={13} />}
      title="Key Target Progress"
      subtitle="(Monthly)"
    >
      <div className="space-y-2.5">
        {keyTargetProgress.map((r) => {
          const Icon = ICON[r.key];
          return (
            <div key={r.key} className="grid grid-cols-[20px_140px_1fr_50px] items-center gap-2 text-[12px]">
              <Icon size={14} className="text-[var(--color-edify-primary)]" />
              <div className="font-semibold">{r.label}</div>
              <div className="flex items-center gap-2">
                <div className="text-[11px] muted tabular w-[88px] text-right">
                  {r.completed.toLocaleString()} / {r.target.toLocaleString()}
                </div>
                <div className="flex-1 h-2 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      r.pct >= 80 ? "bg-emerald-500" :
                      r.pct >= 60 ? "bg-amber-500"   :
                                    "bg-rose-500",
                    )}
                    style={{ width: `${r.pct}%` }}
                  />
                </div>
              </div>
              <div className="text-right tabular font-bold">{r.pct}%</div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

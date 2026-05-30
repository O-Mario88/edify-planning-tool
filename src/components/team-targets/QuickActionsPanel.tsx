"use client";

import {
  AlertTriangle,
  Scale,
  Target,
  CheckCircle2,
  Cloud,
  ShieldCheck,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { quickActionsForRows, type QuickAction } from "@/lib/team-targets-mock";
import type { StaffTargetRow } from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

const ICON: Record<QuickAction["iconKey"], LucideIcon> = {
  alertTriangle: AlertTriangle,
  scale:         Scale,
  target:        Target,
  checkCircle:   CheckCircle2,
  cloud:         Cloud,
  shield:        ShieldCheck,
};

export function QuickActionsPanel({ rows }: { rows: StaffTargetRow[] }) {
  const actions = quickActionsForRows(rows);
  return (
    <SectionCard title="Quick Actions">
      <div className="space-y-2">
        {actions.map((a) => {
          const Icon = ICON[a.iconKey];
          const isSupport = a.key === "Open Support Review Checklist";
          return (
            <a
              key={a.key}
              href={a.href}
              className={cn(
                "flex items-center gap-2.5 px-3 h-10 rounded-lg border transition-colors",
                isSupport
                  ? "border-emerald-300 bg-emerald-50 hover:bg-emerald-100 text-emerald-800"
                  : "border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/50",
              )}
            >
              <Icon size={14} className={isSupport ? "text-emerald-700" : "text-[var(--color-edify-primary)]"} />
              <span className="text-body font-semibold flex-1">{a.key}</span>
              <ChevronRight size={13} className="text-[var(--color-edify-muted)]" />
            </a>
          );
        })}
      </div>
      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-caption muted leading-snug">
        Support-first by design — there is intentionally no one-click PIP action here.
      </div>
    </SectionCard>
  );
}

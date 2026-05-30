"use client";

import {
  Bell,
  Users,
  AlertTriangle,
  Target,
  UserCheck,
  Building2,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { attentionItems, type AttentionItem } from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";

const ICON: Record<AttentionItem["icon"], LucideIcon> = {
  users:         Users,
  alertTriangle: AlertTriangle,
  target:        Target,
  userCheck:     UserCheck,
  school:        Building2,
};

const TONE: Record<AttentionItem["tone"], string> = {
  amber:  "bg-amber-100 text-amber-700",
  rose:   "bg-rose-100 text-rose-700",
  edify:  "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  violet: "bg-violet-100 text-violet-700",
  blue:   "bg-blue-100 text-blue-700",
};

export function AttentionStrip() {
  return (
    <SectionCard
      icon={<Bell size={13} />}
      title="What Needs Attention"
    >
      <div className="grid grid-cols-5 gap-3">
        {attentionItems.map((a) => {
          const Icon = ICON[a.icon];
          return (
            <div
              key={a.key}
              className="rounded-xl border border-[var(--color-edify-border)] p-2.5 flex items-start gap-2 overflow-hidden"
            >
              <span className={cn("w-8 h-8 rounded-md grid place-items-center shrink-0", TONE[a.tone])}>
                <Icon size={14} />
              </span>
              <div className="leading-tight min-w-0 flex-1">
                <div className="text-caption muted font-semibold leading-tight line-clamp-2 min-h-[26px]">
                  {a.title}
                </div>
                <div className="text-[20px] font-extrabold tabular leading-none mt-1 truncate">{a.value}</div>
                <div className="text-[10px] muted mt-0.5 truncate">{a.subtitle}</div>
                <a className="inline-flex items-center text-caption font-semibold text-[var(--color-edify-primary)] mt-1 truncate" href="/notifications">
                  {a.cta}
                </a>
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

"use client";

import {
  MapPin,
  GraduationCap,
  ShieldOff,
  Gauge,
  Building,
  Phone,
  ClipboardList,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { type PlanningSignal } from "@/lib/schools-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<PlanningSignal["icon"], LucideIcon> = {
  mapPin:        MapPin,
  graduationCap: GraduationCap,
  shieldOff:     ShieldOff,
  gauge:         Gauge,
  schoolOff:     Building,
  phone:         Phone,
};

const tone: Record<PlanningSignal["tone"], string> = {
  edify:  "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  amber:  "bg-amber-100 text-amber-800",
  violet: "bg-violet-100 text-violet-700",
  rose:   "bg-rose-100 text-rose-700",
  red:    "bg-red-100 text-red-700",
  blue:   "bg-blue-100 text-[#1e40af]",
};

const valueColor: Record<PlanningSignal["tone"], string> = {
  edify:  "text-[var(--color-edify-primary)]",
  amber:  "text-amber-800",
  violet: "text-violet-700",
  rose:   "text-rose-700",
  red:    "text-red-700",
  blue:   "text-[#1d4ed8]",
};

export function PlanningReviewSignals({ signals }: { signals: PlanningSignal[] }) {
  return (
    <SectionCard
      icon={<ClipboardList size={13} />}
      title="Planning & Review Signals"
    >
      <div className="grid grid-cols-6 gap-3">
        {signals.map((s) => {
          const Icon = iconMap[s.icon];
          return (
            <div
              key={s.key}
              className="rounded-xl border border-[var(--color-edify-border)] p-2.5 flex flex-col items-center text-center overflow-hidden"
            >
              <span className={cn("w-8 h-8 rounded-md grid place-items-center shrink-0", tone[s.tone])}>
                <Icon size={14} />
              </span>
              <div className="text-[10px] muted font-semibold mt-2 leading-tight line-clamp-2 min-h-[24px] w-full px-0.5">
                {s.label}
              </div>
              <div className={cn("text-[18px] font-extrabold tabular leading-none mt-1 truncate w-full", valueColor[s.tone])}>
                {s.value.toLocaleString()}
              </div>
            </div>
          );
        })}
      </div>
    </SectionCard>
  );
}

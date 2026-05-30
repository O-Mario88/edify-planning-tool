"use client";

import {
  Building2,
  CheckCircle2,
  Star,
  Layers,
  Clock,
  AlertTriangle,
  Trophy,
  CalendarX,
  CalendarOff,
} from "lucide-react";
import { type CorePackageSummary } from "@/lib/core-schools-mock";

const tile = (cls: string) => `w-8 h-8 rounded-full grid place-items-center shrink-0 ${cls}`;

export function CoreKpiRow({ s }: { s: CorePackageSummary }) {
  const tiles = [
    { label: "Total Core Schools",       value: s.totalCoreSchools,       icon: Building2,    bg: "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]" },
    { label: "Core Schools Assessed",     value: s.coreSchoolsAssessed,    icon: CheckCircle2, bg: "bg-emerald-100 text-emerald-700" },
    { label: "Average Core SSA",          value: s.averageSsa.toFixed(2),  icon: Star,         bg: "bg-amber-100 text-amber-700" },
    { label: "Package Complete",          value: s.packageComplete,        icon: Layers,       bg: "bg-emerald-100 text-emerald-700" },
    { label: "Behind Schedule",           value: s.behindSchedule,         icon: Clock,        bg: "bg-amber-100 text-amber-700" },
    { label: "0 SSA",                     value: s.coreSchoolsWithZeroSsa, icon: CalendarX,    bg: "bg-rose-100 text-rose-700" },
    { label: "0 Visits",                  value: s.coreSchoolsWithZeroVisits, icon: AlertTriangle, bg: "bg-rose-100 text-rose-700" },
    { label: "0 Training",                value: s.coreSchoolsWithZeroTraining, icon: CalendarOff, bg: "bg-rose-100 text-rose-700" },
    { label: "Potential Champions",       value: s.potentialChampions,     icon: Trophy,       bg: "bg-violet-100 text-violet-700" },
  ];
  return (
    <section className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-9 gap-2.5">
      {tiles.map((t) => (
        <div key={t.label} className="card p-2.5 overflow-hidden">
          <div className="flex items-start gap-2">
            <span className={tile(t.bg)}>
              <t.icon size={14} />
            </span>
            <div className="min-w-0 flex-1 text-[10px] muted font-semibold leading-tight line-clamp-2 min-h-[24px]">
              {t.label}
            </div>
          </div>
          <div className="text-[18px] font-extrabold tabular leading-none mt-1.5 truncate">
            {t.value}
          </div>
        </div>
      ))}
    </section>
  );
}

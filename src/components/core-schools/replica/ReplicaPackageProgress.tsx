"use client";

import {
  Calendar,
  ChevronRight,
  FileText,
  GraduationCap,
  ShieldCheck,
  Sparkles,
  Trophy,
  Users,
  type LucideIcon,
} from "lucide-react";
import {
  replicaMinimumCoreSupport,
  replicaPackageTiles,
  replicaRemainingTasks,
  type ReplicaPackageTile,
} from "@/lib/core-school-replica-mock";
import { cn } from "@/lib/utils";
import { InteractiveTile } from "@/components/tile-filter";

const TILE_ICON: Record<ReplicaPackageTile["icon"], LucideIcon> = {
  doc:         FileText,
  calendar:    Calendar,
  users:       Users,
  step1:       Calendar,
  step2:       Users,
  step3:       GraduationCap,
  schoolCheck: ShieldCheck,
  trophy:      Trophy,
};

const TILE_TONE: Record<ReplicaPackageTile["tone"], string> = {
  slate:  "bg-slate-100   text-slate-700",
  rose:   "bg-rose-100    text-rose-700",
  amber:  "bg-amber-100   text-amber-700",
  blue:   "bg-sky-100     text-sky-700",
  violet: "bg-violet-100  text-violet-700",
  indigo: "bg-indigo-100  text-indigo-700",
  green:  "bg-emerald-100 text-emerald-700",
  yellow: "bg-yellow-100  text-yellow-700",
};

const TASK_ICON: Record<"calendar" | "graduationCap" | "shieldCheck", LucideIcon> = {
  calendar:      Calendar,
  graduationCap: GraduationCap,
  shieldCheck:   ShieldCheck,
};

const TASK_TONE: Record<"blue" | "amber" | "green", string> = {
  blue:  "bg-sky-50     text-sky-700     border-sky-200",
  amber: "bg-amber-50   text-amber-700   border-amber-200",
  green: "bg-emerald-50 text-emerald-700 border-emerald-200",
};

const REMAINING_FILTER_ID: Record<string, string> = {
  visits:        "remaining-visits",
  trainings:     "remaining-trainings",
  verifications: "verifications-pending",
};

export function ReplicaPackageProgress({
  activeFilterId,
  onTileClick,
}: {
  activeFilterId?: string | null;
  onTileClick?: (filterId: string) => void;
}) {
  return (
    <section className="card p-3.5 lg:p-5">
      <div className="flex items-baseline justify-between gap-3 mb-3">
        <div className="flex items-baseline gap-2 min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight text-slate-900">
            Core Service Package Progress
          </h2>
          <span className="text-[11.5px] muted font-semibold">
            (4 Visits + 4 Trainings)
          </span>
        </div>
      </div>

      {/* 8-tile funnel with chevrons between. Every tile is a clickable
          filter trigger that drills the page to the schools represented
          by that stage. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-[repeat(8,minmax(0,1fr))] gap-2 lg:gap-1 items-stretch">
        {replicaPackageTiles.map((t, i) => {
          const Icon = TILE_ICON[t.icon];
          const isLast = i === replicaPackageTiles.length - 1;
          const filterId = `pkg-${t.key}`;
          const active = activeFilterId === filterId;
          return (
            <div key={t.key} className="flex items-center gap-1 min-w-0">
              <InteractiveTile
                onClick={onTileClick ? () => onTileClick(filterId) : undefined}
                active={active}
                asStatic={!onTileClick}
                className={cn(
                  "flex-1 min-w-0 card card-lift tile-in px-2.5 py-2 flex items-center gap-2",
                  ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6","stagger-7","stagger-8"][i] ?? "",
                )}
              >
                <span className={cn("h-9 w-9 rounded-lg grid place-items-center shrink-0", TILE_TONE[t.tone])}>
                  <Icon size={15} />
                </span>
                <div className="min-w-0">
                  <div className="text-[10px] muted font-semibold leading-tight truncate">{t.label}</div>
                  <div className="flex items-baseline gap-1 mt-0.5">
                    <span className="text-[16px] font-extrabold tabular leading-none num-hero">{t.count}</span>
                    <span className="text-[10px] muted font-semibold">({t.pct}%)</span>
                  </div>
                </div>
              </InteractiveTile>
              {!isLast && (
                <ChevronRight
                  size={14}
                  className="hidden xl:block text-slate-300 shrink-0"
                  aria-hidden
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Minimum Core Support Started + Remaining Tasks — two rows, full width. */}
      <div className="mt-4 space-y-3">
        <div className="rounded-xl bg-emerald-50/50 border border-emerald-200 px-3 py-2.5">
          <div className="flex items-center justify-between gap-3 mb-1.5">
            <div className="flex items-center gap-2 min-w-0">
              <Sparkles size={13} className="text-emerald-600 shrink-0" />
              <span className="text-[12px] font-extrabold text-slate-900">Minimum Core Support Started</span>
              <span className="text-[11px] muted font-semibold truncate">(at least 1 Visit + 1 Training)</span>
            </div>
            <span className="text-[13px] font-extrabold tabular text-emerald-700 shrink-0">{replicaMinimumCoreSupport.pct}%</span>
          </div>
          <div className="h-2 rounded-full bg-white overflow-hidden">
            <div
              className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-emerald-500"
              style={{ width: `${replicaMinimumCoreSupport.pct}%` }}
            />
          </div>
        </div>

        <div className="rounded-xl bg-white border border-[var(--color-edify-border)] px-3 py-2.5">
          <div className="flex items-center justify-between gap-3 mb-2">
            <span className="text-[12px] font-extrabold text-slate-900">Remaining Tasks to Complete Full Core Package</span>
          </div>
          <div className="h-2 rounded-full bg-slate-100 overflow-hidden mb-3">
            <div
              className="h-full rounded-full bg-gradient-to-r from-indigo-500 via-violet-500 to-fuchsia-500"
              style={{ width: "74%" }}
            />
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
            {replicaRemainingTasks.map((t) => {
              const Icon = TASK_ICON[t.icon];
              const filterId = REMAINING_FILTER_ID[t.key];
              const active = filterId === activeFilterId;
              return (
                <InteractiveTile
                  key={t.key}
                  onClick={onTileClick && filterId ? () => onTileClick(filterId) : undefined}
                  active={active}
                  asStatic={!onTileClick || !filterId}
                  className={cn(
                    "rounded-lg border px-2.5 py-1.5 flex items-center gap-2",
                    TASK_TONE[t.tone],
                  )}
                >
                  <Icon size={13} className="shrink-0" />
                  <span className="text-[11.5px] font-extrabold tabular shrink-0">{t.count}</span>
                  <span className="text-[11px] font-semibold truncate">{t.label}</span>
                </InteractiveTile>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

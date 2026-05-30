"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Boxes,
  Calendar,
  FileText,
  GraduationCap,
  ShieldCheck,
  Sparkles,
  Trophy,
  Users,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  corePackageTiles,
  minimumCoreSupport,
  remainingPackageTasks,
  type CceoServicePackageTile,
} from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

const TILE_ICON: Record<CceoServicePackageTile["icon"], LucideIcon> = {
  doc:         FileText,
  calendar:    Calendar,
  users:       Users,
  school1v1t:  Calendar,
  school2v2t:  Users,
  school3v3t:  GraduationCap,
  schoolCheck: ShieldCheck,
  trophy:      Trophy,
};

const TONE_BG: Record<CceoServicePackageTile["tone"], string> = {
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
  blue:  "bg-sky-50     text-sky-700     border-sky-100",
  amber: "bg-amber-50   text-amber-700   border-amber-100",
  green: "bg-emerald-50 text-emerald-700 border-emerald-100",
};

export function CoreServicePackageCard() {
  // Editorial counts — derived from the same tiles the body renders so
  // headline and body never drift. "Full package" is the 4V+4T tile;
  // the immediate-action backlog is 0V + 0T tiles combined.
  const fullPackageTile = corePackageTiles.find((t) => t.key === "4v4t");
  const championTile    = corePackageTiles.find((t) => t.key === "champ");
  const zeroVisitTile   = corePackageTiles.find((t) => t.key === "0v");
  const zeroTrainTile   = corePackageTiles.find((t) => t.key === "0t");
  const zeroBacklog     = (zeroVisitTile?.count ?? 0) + (zeroTrainTile?.count ?? 0);

  const headline = `${minimumCoreSupport.pct}% of schools have started Core support · ${fullPackageTile?.count ?? 0} at the full ${fullPackageTile?.label ?? "4V+4T"} package (${fullPackageTile?.pctOfTotal ?? 0}%) · ${championTile?.count ?? 0} in the Champion pipeline.`;

  return (
    <SectionCard
      id="service-package"
      icon={<Boxes size={13} />}
      title="Core Service Package Progress"
      subtitle={headline}
      actions={
        <Link
          href="/dashboards/cceo#service-package"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* 8 tiles — the funnel from 0 SSA → 4V+4T → Potential Champion. */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 lg:gap-3">
        {corePackageTiles.map((t, i) => {
          const Icon = TILE_ICON[t.icon];
          const staggerCls = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6","stagger-7","stagger-8"][i] ?? "";
          return (
            <div
              key={t.key}
              className={cn(
                "card card-lift cursor-default tile-in p-2.5 flex items-center gap-2.5",
                staggerCls,
              )}
            >
              <span className={cn("h-9 w-9 rounded-lg grid place-items-center shrink-0", TONE_BG[t.tone])}>
                <Icon size={15} />
              </span>
              <div className="min-w-0">
                <div className="text-caption muted font-semibold leading-tight truncate">
                  {t.label}
                </div>
                <div className="flex items-baseline gap-1 mt-0.5">
                  <span className="text-[18px] font-extrabold tabular leading-none">{t.count}</span>
                  <span className="text-caption muted font-semibold">({t.pctOfTotal}%)</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Minimum support + Remaining tasks */}
      <div className="mt-4 grid grid-cols-12 gap-3">
        {/* Minimum Core Support Started */}
        <div className="col-span-12 lg:col-span-5 rounded-xl bg-gradient-to-br from-emerald-50 to-white border border-emerald-200 p-3 flex items-center gap-3">
          <span className="h-9 w-9 rounded-lg bg-emerald-100 text-emerald-700 grid place-items-center shrink-0">
            <Sparkles size={15} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-baseline gap-2">
              <div className="text-body font-extrabold tracking-tight">
                {minimumCoreSupport.title}
              </div>
              <div className="text-caption muted">{minimumCoreSupport.subtitle}</div>
              <div className="ml-auto text-[15px] font-extrabold tabular text-emerald-700">
                {minimumCoreSupport.pct}%
              </div>
            </div>
            <div className="mt-1.5 h-2 rounded-full bg-white overflow-hidden">
              <div
                className="h-full rounded-full bg-emerald-500"
                style={{ width: `${minimumCoreSupport.pct}%` }}
              />
            </div>
          </div>
        </div>

        {/* Remaining tasks */}
        <div className="col-span-12 lg:col-span-7 rounded-xl bg-white border border-[var(--color-edify-border)] p-3">
          <div className="text-[12px] font-extrabold tracking-tight mb-2">
            Remaining Tasks to Complete Full Core Package
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {remainingPackageTasks.map((t) => {
              const Icon = TASK_ICON[t.icon];
              return (
                <div
                  key={t.key}
                  className={cn(
                    "rounded-lg border p-2 flex items-center gap-2",
                    TASK_TONE[t.tone],
                  )}
                >
                  <Icon size={13} />
                  <span className="text-[11px] font-semibold leading-tight">{t.label}</span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Trophy size={12} className="text-amber-500" />
          <span className="font-bold">Promote next:</span>
          <span className="muted">{championTile?.count ?? 0} potential Champions ready for review</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Calendar size={12} className="text-rose-600" />
          <span className="font-bold">Lift the floor:</span>
          <span className="muted">{zeroBacklog} schools still need a first visit or training</span>
        </span>
      </div>
    </SectionCard>
  );
}

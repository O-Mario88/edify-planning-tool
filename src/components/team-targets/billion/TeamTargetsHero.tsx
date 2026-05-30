"use client";

import Link from "next/link";
import {
  AlertOctagon,
  ArrowRight,
  CheckCircle2,
  Flag,
  Route,
  Target,
  TrendingUp,
  Users,
  type LucideIcon,
} from "lucide-react";
import { teamTargetsBillionHero, type TeamHeroStatusTile } from "@/lib/team-targets-billion-mock";
import { cn } from "@/lib/utils";

// Dark gradient hero for the team-targets dashboard. Same layout as
// the my-targets hero but oriented around supervising a cohort:
// "Lift the team. Close the gap." + 4 team-level status tiles + a
// primary "Open Support Reviews" CTA.
export function TeamTargetsHero() {
  const h = teamTargetsBillionHero;
  return (
    <section className="relative overflow-hidden rounded-2xl text-white">
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(135deg, #0a1422 0%, #112844 35%, #1b3f72 70%, #2a64a8 100%)",
        }}
      />
      <svg
        aria-hidden
        className="absolute bottom-0 inset-x-0 w-full h-[80%] opacity-25"
        viewBox="0 0 1600 220"
        preserveAspectRatio="none"
      >
        <path
          d="M0,180 L160,110 L320,150 L500,80 L660,130 L820,90 L980,140 L1140,80 L1300,130 L1460,90 L1600,150 L1600,220 L0,220 Z"
          fill="#08182e"
        />
      </svg>
      <div
        aria-hidden
        className="absolute right-[-15%] top-[-25%] w-[55%] h-[140%]"
        style={{
          background:
            "radial-gradient(closest-side at 60% 50%, rgba(130,180,255,0.22) 0%, rgba(130,180,255,0) 70%)",
        }}
      />

      <div className="relative p-4 sm:p-5 lg:p-6 grid grid-cols-12 gap-3 sm:gap-4 items-center">
        {/* Quote + subtext — full width below xl. */}
        <div className="col-span-12 xl:col-span-5">
          <div className="flex items-start gap-3">
            <span className="w-10 h-10 sm:w-11 sm:h-11 rounded-xl bg-white/10 ring-1 ring-white/20 grid place-items-center shrink-0 backdrop-blur">
              <Flag size={20} className="text-sky-300" />
            </span>
            <div className="min-w-0">
              <h2 className="text-[17px] sm:text-[18px] lg:text-[20px] font-extrabold tracking-tight leading-tight">
                {h.quote}
              </h2>
              <p className="text-[12px] text-white/75 leading-snug mt-1">
                {h.subtext}
              </p>
            </div>
          </div>
        </div>

        {/* 4 team status tiles. Full-width 1×4 from sm through lg so
            each tile has ~150-220px to render values like "62 / 144"
            and "1,264" cleanly. Collapses into the 5/12 slot only
            at xl+. */}
        <div className="col-span-12 xl:col-span-5 grid grid-cols-2 sm:grid-cols-4 gap-2">
          {h.statusTiles.map((t) => (
            <StatusTile key={t.key} t={t} />
          ))}
        </div>

        {/* CTA stack — side-by-side at every viewport below xl,
            column-stacked at xl+. */}
        <div className="col-span-12 xl:col-span-2 grid grid-cols-2 xl:grid-cols-1 gap-2">
          <Link
            href={h.primaryCta.href}
            className="inline-flex items-center justify-center gap-1.5 h-10 px-3 rounded-xl bg-sky-500 hover:bg-sky-400 active:bg-sky-600 text-white text-body font-extrabold shadow-[0_10px_28px_-8px_rgba(14,165,233,0.55)] transition-colors whitespace-nowrap"
          >
            {h.primaryCta.label}
            <ArrowRight size={13} />
          </Link>
          <Link
            href={h.secondaryCta.href}
            className="inline-flex items-center justify-center gap-1.5 h-10 px-3 rounded-xl border border-white/20 bg-white/5 hover:bg-white/10 text-white text-[12px] font-semibold transition-colors whitespace-nowrap backdrop-blur"
          >
            <Route size={12} />
            {h.secondaryCta.label}
          </Link>
        </div>
      </div>
    </section>
  );
}

// ───────────── StatusTile ─────────────

const ICON_FOR: Record<TeamHeroStatusTile["key"], LucideIcon> = {
  team_pace:  TrendingUp,
  on_track:   Users,
  at_risk:    AlertOctagon,
  this_week:  Target,
};

const TONE: Record<
  TeamHeroStatusTile["tone"],
  { bg: string; border: string; iconBg: string; iconText: string; valueText: string }
> = {
  good:    { bg: "bg-emerald-500/15", border: "border-emerald-400/30", iconBg: "bg-emerald-500/20", iconText: "text-emerald-300", valueText: "text-emerald-100" },
  watch:   { bg: "bg-amber-500/15",   border: "border-amber-400/30",   iconBg: "bg-amber-500/20",   iconText: "text-amber-300",   valueText: "text-amber-100"   },
  warn:    { bg: "bg-rose-500/15",    border: "border-rose-400/30",    iconBg: "bg-rose-500/20",    iconText: "text-rose-300",    valueText: "text-rose-100"    },
  neutral: { bg: "bg-white/5",        border: "border-white/15",       iconBg: "bg-white/10",       iconText: "text-white/80",    valueText: "text-white"       },
};

function StatusTile({ t }: { t: TeamHeroStatusTile }) {
  const Icon = ICON_FOR[t.key as TeamHeroStatusTile["key"]] ?? Target;
  void CheckCircle2;
  const tone = TONE[t.tone];
  return (
    <div
      className={cn(
        "rounded-xl border backdrop-blur p-2.5 flex items-center gap-2.5",
        tone.bg,
        tone.border,
      )}
    >
      <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", tone.iconBg)}>
        <Icon size={14} className={tone.iconText} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[9.5px] uppercase tracking-wide text-white/65 font-bold leading-tight">
          {t.label}
        </div>
        <div className={cn("text-[15px] font-extrabold tabular leading-none mt-0.5", tone.valueText)}>
          {t.value}
        </div>
        {t.caption && (
          <div className="text-[10px] text-white/65 font-semibold leading-tight mt-0.5 truncate">
            {t.caption}
          </div>
        )}
      </div>
    </div>
  );
}

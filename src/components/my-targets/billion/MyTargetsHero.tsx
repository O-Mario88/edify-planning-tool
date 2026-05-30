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
  type LucideIcon,
} from "lucide-react";
import { myTargetsHero, type HeroStatusTile } from "@/lib/my-targets-billion-mock";
import { cn } from "@/lib/utils";

// Dark gradient hero with mountain accent + motivational quote, four
// inline status tiles, and a primary/secondary CTA stack. Mirrors the
// reference layout exactly.
export function MyTargetsHero() {
  const h = myTargetsHero;
  return (
    <section className="relative overflow-hidden rounded-2xl text-white">
      {/* Layered backdrop — base gradient + mountain silhouette + soft
          warm glow on the right edge. */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(135deg, #0a1c14 0%, #0e2a1d 35%, #155033 70%, #1f7a4d 100%)",
        }}
      />
      <svg
        aria-hidden
        className="absolute bottom-0 inset-x-0 w-full h-[80%] opacity-30"
        viewBox="0 0 1600 220"
        preserveAspectRatio="none"
      >
        <path
          d="M0,180 L160,110 L320,150 L500,80 L660,130 L820,90 L980,140 L1140,80 L1300,130 L1460,90 L1600,150 L1600,220 L0,220 Z"
          fill="#0a1c14"
        />
      </svg>
      <div
        aria-hidden
        className="absolute right-[-15%] top-[-25%] w-[55%] h-[140%]"
        style={{
          background:
            "radial-gradient(closest-side at 60% 50%, rgba(255,200,130,0.22) 0%, rgba(255,180,90,0) 70%)",
        }}
      />

      <div className="relative p-4 sm:p-5 lg:p-6 grid grid-cols-12 gap-3 sm:gap-4 items-center">
        {/* Quote + subtext. Full width below xl so the phrase reads
            cleanly; shares 5/12 with the tile row at xl+. */}
        <div className="col-span-12 xl:col-span-5">
          <div className="flex items-start gap-3">
            <span className="w-10 h-10 sm:w-11 sm:h-11 rounded-xl bg-white/10 ring-1 ring-white/20 grid place-items-center shrink-0 backdrop-blur">
              <Flag size={18} className="text-amber-300 sm:hidden" />
              <Flag size={20} className="text-amber-300 hidden sm:block" />
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

        {/* 4 status tiles. Each tile needs ~110px of inner space for
            values like "On Track" / "7 tasks" — at lg with the old
            5/5/2 split the tiles got crushed to ~75px each. New rule:
            full-width 4-in-a-row from sm through lg (each tile ~150–
            220px), only collapsing into the 5/12 slot at xl+. */}
        <div className="col-span-12 xl:col-span-5 grid grid-cols-2 sm:grid-cols-4 gap-2">
          {h.statusTiles.map((t) => (
            <StatusTile key={t.key} t={t} />
          ))}
        </div>

        {/* CTA stack. Side-by-side at every viewport below xl so the
            two buttons share a horizontal row; column-stacked only
            at xl+ where they live in the narrow 2/12 right rail. */}
        <div className="col-span-12 xl:col-span-2 grid grid-cols-2 xl:grid-cols-1 gap-2">
          <Link
            href={h.primaryCta.href}
            className="inline-flex items-center justify-center gap-1.5 h-10 px-3 rounded-xl bg-emerald-500 hover:bg-emerald-400 active:bg-emerald-600 text-white text-body font-extrabold shadow-[0_10px_28px_-8px_rgba(16,185,129,0.55)] transition-colors whitespace-nowrap"
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

const ICON_FOR: Record<HeroStatusTile["key"], LucideIcon> = {
  fy_pace:   TrendingUp,
  quarter:   CheckCircle2,
  critical:  AlertOctagon,
  today:     Target,
};

const TONE: Record<
  HeroStatusTile["tone"],
  { bg: string; border: string; iconBg: string; iconText: string; valueText: string }
> = {
  good:    { bg: "bg-emerald-500/15", border: "border-emerald-400/30", iconBg: "bg-emerald-500/20", iconText: "text-emerald-300", valueText: "text-emerald-100" },
  watch:   { bg: "bg-amber-500/15",   border: "border-amber-400/30",   iconBg: "bg-amber-500/20",   iconText: "text-amber-300",   valueText: "text-amber-100"   },
  warn:    { bg: "bg-rose-500/15",    border: "border-rose-400/30",    iconBg: "bg-rose-500/20",    iconText: "text-rose-300",    valueText: "text-rose-100"    },
  neutral: { bg: "bg-white/5",        border: "border-white/15",       iconBg: "bg-white/10",       iconText: "text-white/80",    valueText: "text-white"       },
};

function StatusTile({ t }: { t: HeroStatusTile }) {
  const Icon = ICON_FOR[t.key as HeroStatusTile["key"]] ?? Target;
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

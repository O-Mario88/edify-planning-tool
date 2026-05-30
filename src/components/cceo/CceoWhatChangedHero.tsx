"use client";

import Link from "next/link";
import {
  AlertOctagon,
  ArrowRight,
  ArrowUpRight,
  Route,
  TrendingUp,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { cceoHero } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

// The CCEO "What Changed" hero — replaces the bland title/subtitle as
// the first thing the user reads. Pattern mirrors the CPL hero: dark
// premium gradient, name greeting, one-sentence narrative across the
// schools, three glanceable insight chips, and two clear CTAs (primary
// "Review This Week" + secondary "Open Route Plan").
export function CceoWhatChangedHero() {
  const h = cceoHero;
  return (
    <section
      className="relative overflow-hidden rounded-2xl text-white p-5 lg:p-6"
      style={{
        backgroundImage:
          "linear-gradient(135deg, #0a1623 0%, #112a44 45%, #1a3a5e 100%)",
      }}
    >
      {/* Decorative diagonal highlight — subtle glassy sheen on the
          right edge so the dark fill doesn't read as flat black. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-y-0 right-[-20%] w-[60%]"
        style={{
          background:
            "radial-gradient(closest-side at 60% 50%, rgba(82,159,255,0.18) 0%, rgba(82,159,255,0) 70%)",
        }}
      />

      <div className="relative flex items-start gap-5 flex-wrap">
        <div className="min-w-0 flex-1 max-w-[640px]">
          <div className="text-caption uppercase tracking-[0.12em] text-white/55 font-bold">
            CCEO Operating View
          </div>
          <h1 className="text-[22px] lg:text-[26px] font-extrabold tracking-tight leading-tight mt-1">
            {h.greeting}, {h.firstName}.
          </h1>
          <p className="text-[13px] lg:text-[13.5px] text-white/80 leading-snug mt-1.5">
            Across your {h.totalCoreSchools} Core Schools: SSA improved by{" "}
            <span className="font-bold text-emerald-300">+{h.ssaDelta} to {h.ssaScore}</span>,{" "}
            <span className="font-bold text-emerald-300">{h.championReady}</span> schools are ready
            for Champion Review, and{" "}
            <span className="font-bold text-rose-300">{h.criticalCount}</span> schools are below
            6.0 and need attention this week.
          </p>

          <div className="flex flex-wrap gap-2 mt-3.5">
            <InsightChip
              icon={TrendingUp}
              tone="good"
              label={`SSA +${h.ssaDelta}`}
              caption="this month"
            />
            <InsightChip
              icon={Trophy}
              tone="info"
              label={`${h.championReady} Champion-ready`}
              caption="schools"
            />
            <InsightChip
              icon={AlertOctagon}
              tone="warn"
              label={`${h.criticalCount} Critical`}
              caption="below 6.0"
            />
          </div>
        </div>

        <div className="flex flex-col gap-2 shrink-0 ml-auto">
          <Link
            href={h.primaryCta.href}
            className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 active:bg-emerald-600 text-white text-[13px] font-extrabold shadow-[0_8px_24px_-8px_rgba(16,185,129,0.55)] transition-colors whitespace-nowrap"
          >
            {h.primaryCta.label}
            <ArrowRight size={14} />
          </Link>
          <Link
            href={h.secondaryCta.href}
            className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl border border-white/20 bg-white/5 hover:bg-white/10 text-white text-body font-semibold transition-colors whitespace-nowrap backdrop-blur"
          >
            <Route size={13} />
            {h.secondaryCta.label}
          </Link>
        </div>
      </div>
    </section>
  );
}

// ───────────── InsightChip ─────────────

type ChipTone = "good" | "warn" | "info";

const CHIP_TONE: Record<ChipTone, { bg: string; border: string; text: string; iconText: string }> = {
  good: {
    bg:       "bg-emerald-500/15",
    border:   "border-emerald-400/30",
    text:     "text-emerald-100",
    iconText: "text-emerald-300",
  },
  info: {
    bg:       "bg-sky-500/15",
    border:   "border-sky-400/30",
    text:     "text-sky-100",
    iconText: "text-sky-300",
  },
  warn: {
    bg:       "bg-rose-500/15",
    border:   "border-rose-400/30",
    text:     "text-rose-100",
    iconText: "text-rose-300",
  },
};

function InsightChip({
  icon: Icon,
  tone,
  label,
  caption,
}: {
  icon: LucideIcon;
  tone: ChipTone;
  label: string;
  caption: string;
}) {
  const t = CHIP_TONE[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 border backdrop-blur",
        t.bg,
        t.border,
      )}
    >
      <Icon size={13} className={t.iconText} />
      <span className={cn("text-[12px] font-extrabold tabular", t.text)}>{label}</span>
      <span className="text-[11px] text-white/65 font-semibold">{caption}</span>
    </span>
  );
}

// Re-export for callers that may want a standalone trend pill.
export { ArrowUpRight as TrendIcon };

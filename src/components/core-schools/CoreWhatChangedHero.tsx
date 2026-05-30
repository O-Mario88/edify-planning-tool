"use client";

import Link from "next/link";
import {
  AlertOctagon,
  ArrowRight,
  CheckCircle2,
  Route,
  TrendingUp,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { coreHeroDefaults } from "@/lib/core-schools-mock";
import { cn } from "@/lib/utils";

export type CoreHeroProps = {
  firstName?: string;
  totalCoreSchools: number;
  championReady: number;
  behindSchedule: number;
  ssaYoyDelta: number;       // e.g. +0.5
  averageSsa: number;        // e.g. 7.5
};

// What Changed hero for the Core Schools page. Dark premium gradient,
// personal greeting, narrative sentence threading the day's most-load-
// bearing numbers, three glanceable insight chips, and a clear two-CTA
// stack (primary emerald · secondary outline).
export function CoreWhatChangedHero({
  firstName = "there",
  totalCoreSchools,
  championReady,
  behindSchedule,
  ssaYoyDelta,
  averageSsa,
}: CoreHeroProps) {
  const positive = ssaYoyDelta >= 0;
  return (
    <section
      className="relative overflow-hidden rounded-2xl text-white p-5 lg:p-6"
      style={{
        backgroundImage:
          "linear-gradient(135deg, #0a1623 0%, #112a44 45%, #1a3a5e 100%)",
      }}
    >
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
            Core Schools · Operating View
          </div>
          <h1 className="text-[22px] lg:text-[26px] font-extrabold tracking-tight leading-tight mt-1">
            {coreHeroDefaults.greeting}, {firstName}.
          </h1>
          <p className="text-[13px] lg:text-[13.5px] text-white/80 leading-snug mt-1.5">
            Across your {totalCoreSchools} Core Schools:{" "}
            <span className="font-bold text-emerald-300">{championReady}</span> ready for Champion
            Review, <span className="font-bold text-rose-300">{behindSchedule}</span> behind
            schedule, and average SSA at{" "}
            <span className="font-bold text-emerald-300">
              {averageSsa.toFixed(1)} ({positive ? "+" : ""}{ssaYoyDelta.toFixed(1)} YoY)
            </span>.
          </p>

          <div className="flex flex-wrap gap-2 mt-3.5">
            <InsightChip
              icon={Trophy}
              tone="info"
              label={`${championReady} Champion-ready`}
              caption="ready to formally promote"
            />
            <InsightChip
              icon={AlertOctagon}
              tone="warn"
              label={`${behindSchedule} Behind`}
              caption="schedule slipping"
            />
            <InsightChip
              icon={TrendingUp}
              tone="good"
              label={`SSA ${positive ? "+" : ""}${ssaYoyDelta.toFixed(1)} YoY`}
              caption="cohort improving"
            />
          </div>
        </div>

        <div className="flex flex-col gap-2 shrink-0 ml-auto">
          <Link
            href={coreHeroDefaults.primaryCta.href}
            className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 active:bg-emerald-600 text-white text-[13px] font-extrabold shadow-[0_8px_24px_-8px_rgba(16,185,129,0.55)] transition-colors whitespace-nowrap"
          >
            {coreHeroDefaults.primaryCta.label}
            <ArrowRight size={14} />
          </Link>
          <Link
            href={coreHeroDefaults.secondaryCta.href}
            className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl border border-white/20 bg-white/5 hover:bg-white/10 text-white text-body font-semibold transition-colors whitespace-nowrap backdrop-blur"
          >
            <Route size={13} />
            {coreHeroDefaults.secondaryCta.label}
          </Link>
        </div>
      </div>
    </section>
  );
}

// ───────────── InsightChip ─────────────

type ChipTone = "good" | "warn" | "info";

const CHIP_TONE: Record<ChipTone, { bg: string; border: string; text: string; iconText: string }> = {
  good: { bg: "bg-emerald-500/15", border: "border-emerald-400/30", text: "text-emerald-100", iconText: "text-emerald-300" },
  info: { bg: "bg-sky-500/15",     border: "border-sky-400/30",     text: "text-sky-100",     iconText: "text-sky-300"     },
  warn: { bg: "bg-rose-500/15",    border: "border-rose-400/30",    text: "text-rose-100",    iconText: "text-rose-300"    },
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

// Re-export an icon for downstream callers that want a complementary
// emerald-toned pill in their own surfaces.
export { CheckCircle2 as TrendIcon };

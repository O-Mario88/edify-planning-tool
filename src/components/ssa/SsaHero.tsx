"use client";

import Link from "next/link";
import {
  ShieldCheck,
  TrendingUp,
  ArrowRight,
  CheckCircle2,
  Building2,
  AlertTriangle,
  MapPin,
  type LucideIcon,
} from "lucide-react";
import { ssaHero, type SsaHeroTile } from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

// SSA Performance hero — the intelligence band. A deep teal-slate
// gradient with a ridge silhouette + warm glow carries the headline
// SSA story: the narrative, the headline Average SSA Score, and four
// status tiles (the KPI layer). Mirrors the billion-dollar hero
// pattern used on the CCEO /my-targets surface.

const TILE_ICON: Record<SsaHeroTile["key"], LucideIcon> = {
  completion: CheckCircle2,
  assessed:   Building2,
  high_risk:  AlertTriangle,
  below:      MapPin,
};

const TONE: Record<
  SsaHeroTile["tone"],
  { bg: string; border: string; iconBg: string; iconText: string; valueText: string }
> = {
  good:    { bg: "bg-emerald-500/15", border: "border-emerald-400/30", iconBg: "bg-emerald-500/20", iconText: "text-emerald-300", valueText: "text-emerald-100" },
  watch:   { bg: "bg-amber-500/15",   border: "border-amber-400/30",   iconBg: "bg-amber-500/20",   iconText: "text-amber-300",   valueText: "text-amber-100"   },
  warn:    { bg: "bg-rose-500/15",    border: "border-rose-400/30",    iconBg: "bg-rose-500/20",    iconText: "text-rose-300",    valueText: "text-rose-100"    },
  neutral: { bg: "bg-white/5",        border: "border-white/15",       iconBg: "bg-white/10",       iconText: "text-cyan-200",    valueText: "text-white"       },
};

export function SsaHero() {
  const h = ssaHero;
  return (
    <section className="relative overflow-hidden rounded-2xl text-white">
      {/* Layered backdrop — deep teal-slate gradient + ridge silhouette
          + a soft glow on the right edge. */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(135deg, #0a1d24 0%, #102f3a 38%, #1b4f5d 72%, #2c7d80 100%)",
        }}
      />
      <svg
        aria-hidden
        className="absolute bottom-0 inset-x-0 w-full h-[78%] opacity-25"
        viewBox="0 0 1600 220"
        preserveAspectRatio="none"
      >
        <path
          d="M0,170 L150,120 L320,158 L470,96 L640,140 L800,86 L960,150 L1120,92 L1280,140 L1440,96 L1600,150 L1600,220 L0,220 Z"
          fill="#06161c"
        />
      </svg>
      <div
        aria-hidden
        className="absolute right-[-12%] top-[-30%] w-[52%] h-[150%]"
        style={{
          background:
            "radial-gradient(closest-side at 60% 50%, rgba(120,220,210,0.20) 0%, rgba(120,220,210,0) 70%)",
        }}
      />

      <div className="relative p-4 sm:p-5 lg:p-6 grid grid-cols-12 gap-4 sm:gap-5 items-center">
        {/* Narrative + context + CTA */}
        <div className="col-span-12 xl:col-span-5">
          <div className="flex items-start gap-3">
            <span className="w-11 h-11 rounded-xl bg-white/10 ring-1 ring-white/20 grid place-items-center shrink-0 backdrop-blur">
              <ShieldCheck size={20} className="text-cyan-300" />
            </span>
            <div className="min-w-0">
              <div className="text-[10px] uppercase tracking-[0.14em] text-white/55 font-bold">
                {h.context}
              </div>
              <h2 className="text-[17px] sm:text-[18px] lg:text-[21px] font-extrabold tracking-tight leading-tight mt-1">
                {h.headline}
              </h2>
              <p className="text-[12px] text-white/70 leading-snug mt-1">{h.subtext}</p>
              <Link
                href={h.cta.href}
                className="inline-flex items-center gap-1.5 mt-3 h-9 px-3 rounded-xl bg-white/10 hover:bg-white/15 border border-white/20 text-[12px] font-bold backdrop-blur transition-colors"
              >
                {h.cta.label}
                <ArrowRight size={13} />
              </Link>
            </div>
          </div>
        </div>

        {/* Headline metric */}
        <div className="col-span-12 sm:col-span-5 xl:col-span-3">
          <div className="rounded-2xl bg-white/[0.06] border border-white/15 backdrop-blur p-4">
            <div className="text-[10px] uppercase tracking-[0.14em] text-white/55 font-bold">
              Average SSA Score
            </div>
            <div className="flex items-baseline gap-1.5 mt-1.5">
              <span className="text-[44px] lg:text-[52px] font-extrabold tabular leading-none glow-emerald">
                {h.score.value}
              </span>
              <span className="text-body-lg font-bold text-white/55">{h.score.unit}</span>
            </div>
            <div className="flex flex-wrap items-center gap-2 mt-3">
              <span className="inline-flex items-center gap-1 px-1.5 py-[3px] rounded-md bg-emerald-500/20 text-emerald-200 text-[11px] font-extrabold">
                <TrendingUp size={11} />
                {h.score.delta}
              </span>
              <span className="text-[11px] text-white/65 font-semibold">{h.score.note}</span>
            </div>
          </div>
        </div>

        {/* Status tiles */}
        <div className="col-span-12 sm:col-span-7 xl:col-span-4 grid grid-cols-2 gap-2.5">
          {h.statusTiles.map((t) => (
            <HeroTile key={t.key} t={t} />
          ))}
        </div>
      </div>
    </section>
  );
}

function HeroTile({ t }: { t: SsaHeroTile }) {
  const Icon = TILE_ICON[t.key] ?? CheckCircle2;
  const tone = TONE[t.tone];
  return (
    <div
      className={cn(
        "rounded-xl border backdrop-blur p-3 flex items-center gap-2.5",
        tone.bg,
        tone.border,
      )}
    >
      <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", tone.iconBg)}>
        <Icon size={15} className={tone.iconText} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[9.5px] uppercase tracking-wide text-white/60 font-bold leading-tight">
          {t.label}
        </div>
        <div className={cn("text-[18px] font-extrabold tabular leading-none mt-0.5", tone.valueText)}>
          {t.value}
        </div>
        <div className="text-[10px] text-white/60 font-semibold leading-tight mt-0.5 truncate">
          {t.caption}
        </div>
      </div>
    </div>
  );
}

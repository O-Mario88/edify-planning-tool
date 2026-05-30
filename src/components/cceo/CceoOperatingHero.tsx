"use client";

import Link from "next/link";
import {
  AlertOctagon,
  ArrowRight,
  Download,
  Route,
  TrendingUp,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { cceoOperatingHero } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

// The Operating View hero — photographic gradient + greeting + quote +
// three data-grounded chips + primary/secondary CTAs + tucked Export.
// Matches the dashboard reference exactly. The "photo" is rendered as
// layered CSS gradients so it doesn't depend on an external asset and
// reads as a golden-hour mountain landscape at any viewport width.
export function CceoOperatingHero({
  firstName,
}: {
  firstName?: string;
}) {
  const h = cceoOperatingHero;
  const name = firstName ?? h.firstName;
  return (
    <section className="relative overflow-hidden rounded-2xl text-white">
      {/* Layered background — base gradient + mountain silhouette + warm
          horizon glow. Stays light on the wire (zero image bytes) and
          adapts to any width. */}
      <div
        aria-hidden
        className="absolute inset-0"
        style={{
          backgroundImage:
            "linear-gradient(135deg, #0a1a14 0%, #14342a 28%, #2f5e3a 55%, #6e8b3c 78%, #c08540 100%)",
        }}
      />
      <svg
        aria-hidden
        className="absolute bottom-0 inset-x-0 w-full opacity-65"
        viewBox="0 0 1600 220"
        preserveAspectRatio="none"
      >
        <path
          d="M0,180 L120,110 L240,150 L360,90 L500,140 L620,80 L760,130 L900,70 L1040,120 L1180,90 L1320,140 L1460,100 L1600,150 L1600,220 L0,220 Z"
          fill="#0e2218"
          opacity="0.55"
        />
        <path
          d="M0,200 L160,150 L320,180 L480,140 L640,170 L800,130 L960,170 L1120,140 L1280,180 L1440,150 L1600,180 L1600,220 L0,220 Z"
          fill="#0a1a14"
          opacity="0.55"
        />
      </svg>
      <div
        aria-hidden
        className="absolute right-[-15%] top-[-15%] w-[60%] h-[110%]"
        style={{
          background:
            "radial-gradient(closest-side at 60% 50%, rgba(255,196,120,0.30) 0%, rgba(255,180,90,0) 75%)",
        }}
      />

      {/* Content layer — vertical on mobile, two-column from md up. The
          mobile order is: greeting → quote → subtext → chips → CTAs so
          the eye lands on the message before the actions. */}
      <div className="relative p-4 sm:p-5 lg:p-6 flex flex-col md:flex-row md:items-start gap-4 md:gap-5 md:flex-wrap">
        <div className="min-w-0 flex-1 md:max-w-[640px]">
          <h1 className="text-[20px] sm:text-[24px] lg:text-[28px] font-extrabold tracking-tight leading-[1.15]">
            {h.greeting}, {name}.
          </h1>
          <div className="mt-1.5 sm:mt-2 text-[13.5px] sm:text-[15px] lg:text-[16px] font-bold leading-snug text-white/95">
            {h.quote}
          </div>
          <p className="mt-1 text-[11.5px] sm:text-body text-white/75 leading-snug">
            {h.subtext}
          </p>

          <div className="flex flex-wrap gap-1.5 sm:gap-2 mt-3 sm:mt-3.5">
            {h.chips.map((c) => (
              <HeroChip key={c.key} tone={c.tone} label={c.label} caption={c.caption} />
            ))}
          </div>
        </div>

        {/* Action stack — Export sits above primary CTAs on desktop;
            on mobile the whole stack sits below content and Export
            tucks to the right of the primary button to save a row. */}
        <div className="flex flex-col gap-2 shrink-0 w-full md:w-auto md:ml-auto md:items-end">
          <div className="hidden md:flex md:justify-end">
            <button
              type="button"
              className="inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-lg bg-white/10 hover:bg-white/15 text-white text-[12px] font-semibold border border-white/15 backdrop-blur transition-colors whitespace-nowrap"
            >
              <Download size={12} className="text-white/75" />
              Export
            </button>
          </div>
          <div className="flex flex-col sm:flex-row md:flex-col gap-2">
            <Link
              href={h.primaryCta.href}
              className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 active:bg-emerald-600 text-white text-[13px] font-extrabold shadow-[0_10px_28px_-8px_rgba(16,185,129,0.55)] transition-colors whitespace-nowrap flex-1 sm:flex-none"
            >
              {h.primaryCta.label}
              <ArrowRight size={14} />
            </Link>
            <Link
              href={h.secondaryCta.href}
              className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl border border-white/20 bg-white/5 hover:bg-white/10 text-white text-body font-semibold transition-colors whitespace-nowrap backdrop-blur flex-1 sm:flex-none"
            >
              <Route size={13} />
              {h.secondaryCta.label}
            </Link>
            {/* Mobile-only Export — rendered inline so it's still reachable */}
            <button
              type="button"
              className="md:hidden inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl bg-white/10 hover:bg-white/15 text-white text-body font-semibold border border-white/15 backdrop-blur transition-colors whitespace-nowrap flex-1 sm:flex-none"
            >
              <Download size={13} className="text-white/75" />
              Export
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}

// ───────────── HeroChip ─────────────

type ChipTone = "good" | "info" | "warn";

const CHIP_TONE: Record<ChipTone, { bg: string; border: string; text: string; iconText: string; icon: LucideIcon }> = {
  good: {
    bg:       "bg-emerald-500/15",
    border:   "border-emerald-400/30",
    text:     "text-emerald-100",
    iconText: "text-emerald-300",
    icon:     TrendingUp,
  },
  info: {
    bg:       "bg-sky-500/15",
    border:   "border-sky-400/30",
    text:     "text-sky-100",
    iconText: "text-sky-300",
    icon:     Trophy,
  },
  warn: {
    bg:       "bg-rose-500/15",
    border:   "border-rose-400/30",
    text:     "text-rose-100",
    iconText: "text-rose-300",
    icon:     AlertOctagon,
  },
};

function HeroChip({
  tone,
  label,
  caption,
}: {
  tone: ChipTone;
  label: string;
  caption: string;
}) {
  const t = CHIP_TONE[tone];
  const Icon = t.icon;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 sm:gap-1.5 rounded-full px-2 sm:px-3 py-1 sm:py-1.5 border backdrop-blur",
        t.bg,
        t.border,
      )}
    >
      <Icon size={12} className={cn("shrink-0", t.iconText)} />
      <span className={cn("text-[11px] sm:text-[12px] font-extrabold tabular whitespace-nowrap", t.text)}>{label}</span>
      <span className="hidden sm:inline text-[11px] text-white/65 font-semibold whitespace-nowrap">{caption}</span>
    </span>
  );
}

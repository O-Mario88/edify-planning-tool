"use client";

import Link from "next/link";
import {
  AlertOctagon,
  ArrowRight,
  Building2,
  CalendarRange,
  Download,
  GitCompareArrows,
  Route,
  Sparkles,
  TrendingUp,
  Trophy,
  type LucideIcon,
} from "lucide-react";
import { PageHeader, type PageHeaderFilter } from "@/components/ui/PageHeader";
import { cn } from "@/lib/utils";
import type { DashboardHeroContent, HeroChip } from "@/lib/dashboard-hero-mock";

// Unified dashboard hero — a single component every role-based
// landing page renders so the experience feels coherent. Combines
// the slim header strip (title · operating-view pill · search ·
// filter pills · bell · profile) with the photographic greeting hero
// (mountain gradient · "Good morning, X." · quote · 3 KPI chips ·
// primary / secondary CTAs · tucked Export).
//
// All copy is supplied via the `content` prop so each role tells its
// own story; the greeting + first name flow from the signed-in user.
//
// On mobile/tablet the filter pills move to a horizontal-scroll strip
// below the title row, the search collapses, and the profile chip
// drops its name label to fit beside the bell.

export type DashboardHeroProps = {
  content: DashboardHeroContent;
  user: {
    name:      string;
    initials:  string;
    role:      string;
    online?:   boolean;
    avatarUrl?: string | null;
  };
  notificationsCount?: number;
  /** Greeting prefix — usually "Good morning" / "Good afternoon" / "Good evening". */
  greetingPrefix?: string;
};

export function DashboardHero({
  content,
  user,
  notificationsCount = 0,
  greetingPrefix,
}: DashboardHeroProps) {
  const firstName = user.name.split(" ")[0];
  const greeting = greetingPrefix ?? computeGreeting();

  // Header chrome (title · pill · filters · search · bell · avatar)
  // now flows through the canonical <PageHeader>. The photographic
  // greeting card below is content, not chrome — it stays as a
  // dedicated `<GreetingHero>` rendered in the page body. Voiding the
  // unused props since per-page notifications are now read from the
  // shared NotificationBell state.
  void notificationsCount;
  const filterPills: PageHeaderFilter[] = [
    { Icon: CalendarRange,    label: content.filters.month },
    { Icon: GitCompareArrows, label: content.filters.compare },
    { Icon: Building2,        label: content.filters.region },
  ];

  return (
    <div className="space-y-3 lg:space-y-4">
      <PageHeader
        title={content.title}
        searchPlaceholder="Search schools, activities, clusters…"
        filters={filterPills}
        titleBadge={
          <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wider bg-emerald-50 text-emerald-700 border border-emerald-200 whitespace-nowrap">
            <Sparkles size={9} />
            {content.pillLabel}
          </span>
        }
      />
      <div className="px-3 sm:px-4 lg:px-6">
        <GreetingHero
          greeting={greeting}
          firstName={firstName}
          quote={content.quote}
          subtext={content.subtext}
          chips={content.chips}
          primaryCta={content.primaryCta}
          secondaryCta={content.secondaryCta}
        />
      </div>
    </div>
  );
}

// HeaderStrip / FilterPill / NotificationBell / ProfileChip — removed.
// Chrome now flows through the canonical <PageHeader>; the AvatarMenu
// + NotificationBell + ⌘K command palette + breadcrumbs all come for
// free from there. Only the GreetingHero (the page's content, not its
// chrome) remains in this file.

// ───────────── GreetingHero ─────────────

function GreetingHero({
  greeting,
  firstName,
  quote,
  subtext,
  chips,
  primaryCta,
  secondaryCta,
}: {
  greeting:     string;
  firstName:    string;
  quote:        string;
  subtext:      string;
  chips:        HeroChip[];
  primaryCta:   { label: string; href: string };
  secondaryCta: { label: string; href: string };
}) {
  return (
    <section className="relative overflow-hidden rounded-2xl text-white">
      {/* Layered background — gradient + mountain silhouette + warm horizon glow. */}
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
        <path d="M0,180 L120,110 L240,150 L360,90 L500,140 L620,80 L760,130 L900,70 L1040,120 L1180,90 L1320,140 L1460,100 L1600,150 L1600,220 L0,220 Z" fill="#0e2218" opacity="0.55" />
        <path d="M0,200 L160,150 L320,180 L480,140 L640,170 L800,130 L960,170 L1120,140 L1280,180 L1440,150 L1600,180 L1600,220 L0,220 Z" fill="#0a1a14" opacity="0.55" />
      </svg>
      <div
        aria-hidden
        className="absolute right-[-15%] top-[-15%] w-[60%] h-[110%]"
        style={{
          background:
            "radial-gradient(closest-side at 60% 50%, rgba(255,196,120,0.30) 0%, rgba(255,180,90,0) 75%)",
        }}
      />

      {/* Content layer */}
      <div className="relative p-4 sm:p-5 lg:p-6 flex flex-col md:flex-row md:items-start gap-4 md:gap-5 md:flex-wrap">
        <div className="min-w-0 flex-1 md:max-w-[540px]">
          <h1 className="text-[20px] sm:text-[24px] lg:text-[28px] font-extrabold tracking-tight leading-[1.15]">
            {greeting}, {firstName}.
          </h1>
          <div className="mt-1.5 sm:mt-2 text-[13.5px] sm:text-[15px] lg:text-[16px] font-bold leading-snug text-white/95">
            {quote}
          </div>
          <p className="mt-1 text-[11.5px] sm:text-body text-white/75 leading-snug">
            {subtext}
          </p>

          <div className="flex flex-wrap gap-1.5 sm:gap-2 mt-3 sm:mt-3.5">
            {chips.map((c) => (
              <HeroChipView key={c.key} chip={c} />
            ))}
          </div>
        </div>

        {/* Team Pulse — fills the dead space mid-hero with a real
            week-pace signal (sparkline + 2 mini-stats). Desktop/tablet
            only; hidden on mobile to keep the greeting+CTAs above the
            fold. */}
        <HeroPulse />

        {/* Action stack */}
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
              href={primaryCta.href}
              className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] active:bg-emerald-600 text-white text-[13px] font-extrabold shadow-[0_10px_28px_-8px_rgba(16,185,129,0.55)] transition-colors whitespace-nowrap flex-1 sm:flex-none"
            >
              {primaryCta.label}
              <ArrowRight size={14} />
            </Link>
            <Link
              href={secondaryCta.href}
              className="inline-flex items-center justify-center gap-1.5 h-10 px-4 rounded-xl border border-white/20 bg-white/5 hover:bg-white/10 text-white text-body font-semibold transition-colors whitespace-nowrap backdrop-blur flex-1 sm:flex-none"
            >
              <Route size={13} />
              {secondaryCta.label}
            </Link>
            {/* Mobile-only Export pulled inline so it stays reachable. */}
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

// ───────────── HeroPulse ─────────────
//
// A compact "team pulse" tile that fills the mid-right of the hero.
// Two mini KPIs stacked over a 14-day completion sparkline. The data
// is mock today — when the analytics layer ships, swap `PULSE_SERIES`
// for a server-side prop. The shape and motion stay identical.
//
// Visual rules:
//   • md+ only — on mobile the hero stays text-first
//   • lives inside the same backdrop-blur tile language as the chips
//   • sparkline uses Edify orange (#f59e0b) on a soft white wash so it
//     reads against any gradient horizon

const PULSE_SERIES = [38, 42, 36, 51, 47, 58, 54, 61, 57, 64, 70, 66, 72, 78];

function HeroPulse() {
  const max = Math.max(...PULSE_SERIES);
  const min = Math.min(...PULSE_SERIES);
  const range = Math.max(1, max - min);
  const w = 220;
  const h = 56;
  const step = w / (PULSE_SERIES.length - 1);
  const points = PULSE_SERIES.map((v, i) => {
    const x = i * step;
    const y = h - ((v - min) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const areaPath = `M 0,${h} L ${points.split(" ").join(" L ")} L ${w},${h} Z`;
  const linePath = `M ${points.split(" ").join(" L ")}`;
  const last = PULSE_SERIES[PULSE_SERIES.length - 1];
  const lastX = w;
  const lastY = h - ((last - min) / range) * h;

  return (
    <div className="hidden md:flex flex-col gap-2.5 shrink-0 rounded-2xl border border-white/15 bg-white/5 backdrop-blur px-4 py-3 w-[260px]">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] uppercase tracking-wider text-white/65 font-bold">Schools touched</div>
          <div className="text-[18px] font-extrabold leading-none mt-1 num-hero">
            12<span className="text-white/55 text-[13px] font-bold">/47</span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-[10px] uppercase tracking-wider text-white/65 font-bold">Wk pace</div>
          <div className="text-[18px] font-extrabold leading-none mt-1 num-hero text-emerald-300">
            +14%
          </div>
        </div>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-[56px]" preserveAspectRatio="none" aria-hidden>
        <defs>
          <linearGradient id="pulse-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f59e0b" stopOpacity="0.45" />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={areaPath} fill="url(#pulse-fill)" />
        <path d={linePath} fill="none" stroke="#fbbf24" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={lastX} cy={lastY} r="2.8" fill="#fff" stroke="#fbbf24" strokeWidth="1.4" />
      </svg>
      <div className="flex items-center justify-between text-[10px] text-white/55 font-semibold">
        <span>Last 14 days</span>
        <span>Target 60/wk</span>
      </div>
    </div>
  );
}

const CHIP_TONE: Record<HeroChip["tone"], { bg: string; border: string; text: string; iconText: string; icon: LucideIcon }> = {
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

function HeroChipView({ chip }: { chip: HeroChip }) {
  const t = CHIP_TONE[chip.tone];
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
      <span className={cn("text-[11px] sm:text-[12px] font-extrabold tabular whitespace-nowrap", t.text)}>{chip.label}</span>
      <span className="hidden sm:inline text-[11px] text-white/65 font-semibold whitespace-nowrap">{chip.caption}</span>
    </span>
  );
}

// ───────────── helpers ─────────────

function computeGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 17) return "Good afternoon";
  return "Good evening";
}

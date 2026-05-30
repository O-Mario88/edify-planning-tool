"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  Calendar,
  ClipboardList,
  FileText,
  Footprints,
  ShieldCheck,
  Trophy,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { cceoQuickActions, type CceoQuickAction } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<CceoQuickAction["icon"], LucideIcon> = {
  clipboardList: ClipboardList,
  calendar:      Calendar,
  footprints:    Footprints,
  shieldCheck:   ShieldCheck,
  trophy:        Trophy,
  fileText:      FileText,
};

// Tone palette — each tone keeps the colored icon block + bottom accent
// bar, but the TILE SURFACE itself uses the canonical card token so
// the tile adapts to Light / Dark / Glass without per-theme overrides.
// (The previous palette used `from-color-50 via-white to-white`
// gradients that read as washed-out white blocks in dark + glass; we
// now use the standard card surface plus a soft tone tint for the
// gradient overlay, and translucent tone-based count chips that read
// in any theme.)
type TonePalette = {
  /** Optional gradient OVERLAY applied on top of the card surface —
   *  keeps the subtle tonal warmth from the light-mode design without
   *  obliterating the dark/glass surface beneath. */
  toneOverlay: string;
  iconBg:      string;
  iconShadow:  string;
  accent:      string;
  countChip:   string;
  ring:        string;
};

const TONE: Record<CceoQuickAction["tone"], TonePalette> = {
  edify: {
    toneOverlay: "from-[var(--color-edify-primary)]/[0.07] via-transparent to-transparent",
    iconBg:      "bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f] text-white",
    iconShadow:  "shadow-[0_4px_12px_-2px_rgba(82,112,131,0.45)]",
    accent:      "bg-[var(--color-edify-primary)]",
    countChip:   "bg-[var(--color-edify-primary)]/15 text-[var(--color-edify-primary)] dark:text-sky-300",
    ring:        "group-hover:ring-[var(--color-edify-primary)]/30",
  },
  amber: {
    toneOverlay: "from-amber-500/[0.08] via-transparent to-transparent",
    iconBg:      "bg-gradient-to-br from-amber-400 to-amber-600 text-white",
    iconShadow:  "shadow-[0_4px_12px_-2px_rgba(245,158,11,0.45)]",
    accent:      "bg-amber-500",
    countChip:   "bg-amber-500/15 text-amber-700 dark:text-amber-300",
    ring:        "group-hover:ring-amber-300",
  },
  violet: {
    toneOverlay: "from-violet-500/[0.08] via-transparent to-transparent",
    iconBg:      "bg-gradient-to-br from-violet-500 to-violet-700 text-white",
    iconShadow:  "shadow-[0_4px_12px_-2px_rgba(124,58,237,0.4)]",
    accent:      "bg-violet-500",
    countChip:   "bg-violet-500/15 text-violet-700 dark:text-violet-300",
    ring:        "group-hover:ring-violet-300",
  },
  blue: {
    toneOverlay: "from-sky-500/[0.08] via-transparent to-transparent",
    iconBg:      "bg-gradient-to-br from-sky-500 to-sky-700 text-white",
    iconShadow:  "shadow-[0_4px_12px_-2px_rgba(14,165,233,0.4)]",
    accent:      "bg-sky-500",
    countChip:   "bg-sky-500/15 text-sky-700 dark:text-sky-300",
    ring:        "group-hover:ring-sky-300",
  },
  red: {
    toneOverlay: "from-rose-500/[0.08] via-transparent to-transparent",
    iconBg:      "bg-gradient-to-br from-rose-500 to-rose-700 text-white",
    iconShadow:  "shadow-[0_4px_12px_-2px_rgba(244,63,94,0.45)]",
    accent:      "bg-rose-500",
    countChip:   "bg-rose-500/15 text-rose-700 dark:text-rose-300",
    ring:        "group-hover:ring-rose-300",
  },
  green: {
    toneOverlay: "from-emerald-500/[0.08] via-transparent to-transparent",
    iconBg:      "bg-gradient-to-br from-emerald-500 to-emerald-700 text-white",
    iconShadow:  "shadow-[0_4px_12px_-2px_rgba(16,185,129,0.4)]",
    accent:      "bg-emerald-500",
    countChip:   "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
    ring:        "group-hover:ring-emerald-300",
  },
};

export function CceoQuickActionsRow() {
  return (
    <SectionCard
      icon={<Zap size={13} />}
      title="Quick Actions"
      subtitle="Six shortcuts to your most-used work — counts are live."
    >
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {cceoQuickActions.map((a, i) => {
          const Icon = ICON_MAP[a.icon];
          const palette = TONE[a.tone];
          const isStatus = typeof a.count === "string";
          const staggerCls = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][i] ?? "";
          return (
            <Link
              key={a.key}
              href={a.href}
              className={cn(
                // Use the canonical `.card` surface so the tile reads
                // correctly across Light / Dark / Glass.  `card-lift`
                // gives the standard hover behaviour; `tile-in` is the
                // stagger entrance animation.
                "group relative card card-lift tile-in overflow-hidden",
                staggerCls,
                "p-3.5 flex flex-col gap-2.5 min-h-[132px]",
                "transition-all duration-300 ease-[cubic-bezier(0.2,0.6,0.2,1)] ring-2 ring-transparent",
                palette.ring,
              )}
            >
              {/* Tone overlay — a soft tint that lives ON TOP of the
                  card surface, giving the tile its colour signature
                  without obliterating the surface beneath.  Sits at
                  pointer-events-none so it can't intercept clicks. */}
              <span
                aria-hidden
                className={cn(
                  "absolute inset-0 pointer-events-none bg-gradient-to-br",
                  palette.toneOverlay,
                )}
              />
              <div className="relative flex items-start justify-between gap-2">
                <span
                  className={cn(
                    "w-9 h-9 rounded-xl grid place-items-center shrink-0",
                    palette.iconBg,
                    palette.iconShadow,
                  )}
                >
                  <Icon size={17} strokeWidth={2.25} />
                </span>
                <ArrowUpRight
                  size={14}
                  className="text-[var(--text-muted)] group-hover:text-[var(--text-primary)] group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-transform"
                />
              </div>

              <div className="relative mt-auto">
                <div className="text-[13px] font-extrabold leading-tight tracking-tight text-[var(--text-primary)]">
                  {a.title}
                </div>
                <div className="mt-1 flex items-center gap-1.5 min-w-0">
                  <span
                    className={cn(
                      "inline-flex items-center px-1.5 py-[1px] rounded-md text-caption font-extrabold tabular whitespace-nowrap num-hero",
                      palette.countChip,
                    )}
                  >
                    {a.count}
                  </span>
                  <span className="text-caption muted font-semibold truncate">
                    {a.caption}
                  </span>
                </div>
                {isStatus && (
                  <div className="sr-only">Status: {a.count}</div>
                )}
              </div>

              <span
                className={cn(
                  "absolute inset-x-0 bottom-0 h-[3px]",
                  palette.accent,
                  "opacity-60 group-hover:opacity-100 transition-opacity",
                )}
              />
            </Link>
          );
        })}
      </div>
    </SectionCard>
  );
}

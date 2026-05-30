"use client";

import Link from "next/link";
import {
  ClipboardList,
  Layers,
  Target,
  Route,
  AlertTriangle,
  Calendar,
  ArrowUpRight,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { cplQuickActions, type CplQuickAction } from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const iconMap: Record<CplQuickAction["icon"], LucideIcon> = {
  clipboardList: ClipboardList,
  layers:        Layers,
  target:        Target,
  route:         Route,
  alertTriangle: AlertTriangle,
  calendar:      Calendar,
};

// Tone palette — each tone is a coordinated set: a tinted gradient
// background, a saturated icon chip, an accent bar at the bottom.
// Used together they give every tile a distinct visual identity
// without breaking the 4-tone semantic discipline elsewhere on the
// page (this row is the only place we let decorative tones live).
type TonePalette = {
  gradient: string;
  iconBg: string;
  iconShadow: string;
  accent: string;
  countChip: string;
  ring: string;
};

const TONE: Record<CplQuickAction["tone"], TonePalette> = {
  edify: {
    gradient:   "from-[var(--color-edify-primary)]/[0.07] via-transparent to-transparent",
    iconBg:     "bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f] text-white",
    iconShadow: "shadow-[0_4px_12px_-2px_rgba(82,112,131,0.45)]",
    accent:     "bg-[var(--color-edify-primary)]",
    countChip:  "bg-[var(--color-edify-primary)]/15 text-[var(--color-edify-primary)] dark:text-sky-300",
    ring:       "group-hover:ring-[var(--color-edify-primary)]/30",
  },
  amber: {
    gradient:   "from-amber-500/[0.08] via-transparent to-transparent",
    iconBg:     "bg-gradient-to-br from-amber-400 to-amber-600 text-white",
    iconShadow: "shadow-[0_4px_12px_-2px_rgba(245,158,11,0.45)]",
    accent:     "bg-amber-500",
    countChip:  "bg-amber-500/15 text-amber-700 dark:text-amber-300",
    ring:       "group-hover:ring-amber-300",
  },
  violet: {
    gradient:   "from-violet-500/[0.08] via-transparent to-transparent",
    iconBg:     "bg-gradient-to-br from-violet-500 to-violet-700 text-white",
    iconShadow: "shadow-[0_4px_12px_-2px_rgba(124,58,237,0.4)]",
    accent:     "bg-violet-500",
    countChip:  "bg-violet-500/15 text-violet-700 dark:text-violet-300",
    ring:       "group-hover:ring-violet-300",
  },
  blue: {
    gradient:   "from-sky-500/[0.08] via-transparent to-transparent",
    iconBg:     "bg-gradient-to-br from-sky-500 to-sky-700 text-white",
    iconShadow: "shadow-[0_4px_12px_-2px_rgba(14,165,233,0.4)]",
    accent:     "bg-sky-500",
    countChip:  "bg-sky-500/15 text-sky-700 dark:text-sky-300",
    ring:       "group-hover:ring-sky-300",
  },
  red: {
    gradient:   "from-rose-500/[0.08] via-transparent to-transparent",
    iconBg:     "bg-gradient-to-br from-rose-500 to-rose-700 text-white",
    iconShadow: "shadow-[0_4px_12px_-2px_rgba(244,63,94,0.45)]",
    accent:     "bg-rose-500",
    countChip:  "bg-rose-500/15 text-rose-700 dark:text-rose-300",
    ring:       "group-hover:ring-rose-300",
  },
  green: {
    gradient:   "from-emerald-500/[0.08] via-transparent to-transparent",
    iconBg:     "bg-gradient-to-br from-emerald-500 to-emerald-700 text-white",
    iconShadow: "shadow-[0_4px_12px_-2px_rgba(16,185,129,0.4)]",
    accent:     "bg-emerald-500",
    countChip:  "bg-emerald-500/15 text-emerald-700 dark:text-emerald-300",
    ring:       "group-hover:ring-emerald-300",
  },
};

// Subtitles that lead with a count get the count split out into a
// prominent chip ("28 pending" → chip: "28" · caption: "pending").
// Subtitles that are descriptive ("Plan & optimize") render as-is.
function parseSubtitle(subtitle: string): { count?: string; caption: string } {
  // Match a number-prefixed string like "28 pending" or "164 items".
  const m = subtitle.match(/^(\d+(?:,\d{3})*)\s+(.+)$/);
  if (m) return { count: m[1], caption: m[2] };
  return { caption: subtitle };
}

export function QuickActionsRow() {
  return (
    <SectionCard
      icon={<Zap size={13} />}
      title="Quick Actions"
      subtitle="Six shortcuts to your team's most-used surfaces — counts are live."
    >
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {cplQuickActions.map((a, i) => {
          const Icon = iconMap[a.icon];
          const palette = TONE[a.tone];
          const parsed = parseSubtitle(a.subtitle);
          const staggerCls = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5","stagger-6"][i] ?? "";
          return (
            <Link
              key={a.key}
              href={a.href}
              className={cn(
                // Canonical `.card` surface so the tile reads correctly
                // in Light / Dark / Glass.  `card-lift` carries the
                // standard hover lift; `tile-in` is the entrance.
                "group relative card card-lift tile-in overflow-hidden",
                staggerCls,
                "p-3.5 flex flex-col gap-2.5 min-h-[132px]",
                "transition-all duration-300 ease-[cubic-bezier(0.2,0.6,0.2,1)] ring-2 ring-transparent",
                palette.ring,
              )}
            >
              {/* Tone overlay — soft tonal tint ON TOP of the surface,
                  pointer-events-none so it can't intercept clicks. */}
              <span
                aria-hidden
                className={cn(
                  "absolute inset-0 pointer-events-none bg-gradient-to-br",
                  palette.gradient,
                )}
              />
              {/* Top row: icon block + arrow */}
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
                  size={16}
                  className="text-[var(--text-muted)] group-hover:text-[var(--text-primary)] group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-transform"
                />
              </div>

              {/* Title + subtitle area. */}
              <div className="relative mt-auto">
                <div className="text-[13px] font-extrabold leading-tight tracking-tight text-[var(--text-primary)]">
                  {a.title}
                </div>
                <div className="mt-1 flex items-center gap-1.5 min-w-0">
                  {parsed.count && (
                    <span
                      className={cn(
                        "inline-flex items-center px-1.5 py-[1px] rounded-md text-caption font-extrabold tabular num-hero",
                        palette.countChip,
                      )}
                    >
                      {parsed.count}
                    </span>
                  )}
                  <span className="text-caption muted font-semibold truncate">
                    {parsed.caption}
                  </span>
                </div>
              </div>

              {/* Bottom accent line — always visible, intensifies on hover. */}
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

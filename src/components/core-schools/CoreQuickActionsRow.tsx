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
import { coreQuickActions, type CoreQuickAction } from "@/lib/core-schools-mock";
import { cn } from "@/lib/utils";

const ICON_MAP: Record<CoreQuickAction["icon"], LucideIcon> = {
  clipboardList: ClipboardList,
  calendar:      Calendar,
  footprints:    Footprints,
  shieldCheck:   ShieldCheck,
  trophy:        Trophy,
  fileText:      FileText,
};

// Same tone palette pattern used on the CCEO and CPL Quick Actions
// rows — coordinated trio per tone: tinted gradient bg, gradient
// icon block with drop shadow, bottom accent bar.
type TonePalette = {
  gradient:   string;
  iconBg:     string;
  iconShadow: string;
  accent:     string;
  countChip:  string;
  ring:       string;
};

const TONE: Record<CoreQuickAction["tone"], TonePalette> = {
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

export function CoreQuickActionsRow() {
  return (
    <SectionCard
      icon={<Zap size={13} />}
      title="Quick Actions"
      subtitle="Six shortcuts to the most-loaded Core School workflows — counts are live."
    >
      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {coreQuickActions.map((a) => {
          const Icon = ICON_MAP[a.icon];
          const palette = TONE[a.tone];
          return (
            <Link
              key={a.key}
              href={a.href}
              className={cn(
                // Canonical card surface — adapts to Light / Dark /
                // Glass via tokens.
                "group relative card card-lift overflow-hidden",
                "p-4 flex flex-col gap-3 min-h-[148px]",
                "transition-all duration-200 ring-2 ring-transparent",
                palette.ring,
              )}
            >
              {/* Tone overlay — soft tonal tint ON TOP of the card
                  surface, pointer-events-none. */}
              <span
                aria-hidden
                className={cn(
                  "absolute inset-0 pointer-events-none bg-gradient-to-br",
                  palette.gradient,
                )}
              />
              <div className="relative flex items-start justify-between gap-2">
                <span
                  className={cn(
                    "w-11 h-11 rounded-xl grid place-items-center shrink-0",
                    palette.iconBg,
                    palette.iconShadow,
                  )}
                >
                  <Icon size={20} strokeWidth={2.25} />
                </span>
                <ArrowUpRight
                  size={16}
                  className="text-[var(--text-muted)] group-hover:text-[var(--text-primary)] group-hover:-translate-y-0.5 group-hover:translate-x-0.5 transition-transform"
                />
              </div>

              <div className="relative mt-auto">
                <div className="text-[14.5px] font-extrabold leading-tight tracking-tight text-[var(--text-primary)]">
                  {a.title}
                </div>
                <div className="mt-1.5 flex items-center gap-1.5 min-w-0">
                  <span
                    className={cn(
                      "inline-flex items-center px-1.5 py-[1px] rounded-md text-[11px] font-extrabold tabular whitespace-nowrap",
                      palette.countChip,
                    )}
                  >
                    {a.count}
                  </span>
                  <span className="text-[11.5px] muted font-semibold truncate">
                    {a.caption}
                  </span>
                </div>
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

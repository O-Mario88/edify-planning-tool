import Link from "next/link";
import type { ReactNode } from "react";
import { ArrowUpRight, ArrowDownRight, Minus } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  KPI_ICON_BG,
  KPI_ICON_FG,
  KPI_GLOW,
  kpiStagger,
  kpiTone,
  type KpiTone,
} from "@/components/ui/kpi-tokens";

// Tile — the canonical KPI / stat / metric tile.
//
// Codifies the /approvals page's KPI tile pattern so every role's
// dashboard uses the same surface for its headline metrics. Visual
// tokens (tone → bg/fg/glow, stagger) come from `kpi-tokens` so every
// tile across the app stays in lockstep — including in dark / glass.
//
// Optional extras (render only when passed, so existing callers are
// unaffected):
//   • `unit`      — small muted unit beside the value ("%", "schools")
//   • `delta`     — the standard up/down/flat trend chip + caption
//   • `accessory` — a node to the right of the value (progress ring, …)
//
// Use `href` for clickable tiles (renders a Link); omit for static.

export type TileTone = KpiTone;

export type TileDelta = {
  dir: "up" | "down" | "flat";
  text: ReactNode;
  caption?: ReactNode;
};

const DELTA_ICON = { up: ArrowUpRight, down: ArrowDownRight, flat: Minus };
const DELTA_FG = {
  up:   "text-emerald-700 dark:text-emerald-300",
  down: "text-rose-700 dark:text-rose-300",
  flat: "text-slate-500 dark:text-slate-400",
};

export function Tile({
  label,
  value,
  unit,
  trend,
  delta,
  accessory,
  icon,
  tone = "edify",
  href,
  index,
  className,
}: {
  label:    ReactNode;
  value:    ReactNode;
  /** Small muted unit rendered beside the value. */
  unit?:    ReactNode;
  /** Optional trailing line under the value (free-form). */
  trend?:   ReactNode;
  /** Structured trend chip (takes precedence over `trend`). */
  delta?:   TileDelta;
  /** Node rendered to the right of the value (e.g. a progress ring). */
  accessory?: ReactNode;
  /** Lucide icon node, rendered inside the tinted circle. */
  icon?:    ReactNode;
  tone?:    string;
  /** Pass an href to make the tile clickable (renders as <Link>). */
  href?:    string;
  /** Stagger-animation index. Omit for no delay. */
  index?:   number;
  className?: string;
}) {
  const t = kpiTone(tone);
  const cursor = href ? "cursor-pointer" : "cursor-default";
  const DeltaIcon = delta ? DELTA_ICON[delta.dir] : null;
  const rootClass = cn(
    "card card-lift tile-in p-3",
    cursor,
    kpiStagger(index),
    className,
  );

  const body = (
    <>
      <div className="flex items-start gap-2.5">
        {icon ? (
          <span className={cn(
            "w-9 h-9 rounded-full grid place-items-center shrink-0",
            KPI_ICON_BG[t],
            KPI_ICON_FG[t],
          )}>
            {icon}
          </span>
        ) : null}
        <div className="min-w-0 flex-1">
          <div className="text-[10px] muted font-bold uppercase tracking-wide leading-tight line-clamp-2">
            {label}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between gap-2 mt-2.5 min-w-0">
        <div className="flex items-baseline gap-1 min-w-0">
          <span className={cn(
            "text-[18px] font-extrabold tabular leading-none text-[var(--text-primary)] num-hero",
            KPI_GLOW[t],
          )}>
            {value}
          </span>
          {unit ? (
            <span className="text-[13px] muted font-semibold leading-none">{unit}</span>
          ) : null}
        </div>
        {accessory ?? null}
      </div>

      {delta ? (
        <div className="flex items-center gap-1.5 min-w-0 mt-1.5">
          <span className={cn(
            "inline-flex items-center gap-0.5 text-caption font-bold tabular shrink-0",
            DELTA_FG[delta.dir],
          )}>
            {DeltaIcon ? <DeltaIcon size={11} /> : null}
            {delta.text}
          </span>
          {delta.caption ? (
            <span className="text-[10px] muted font-semibold truncate">{delta.caption}</span>
          ) : null}
        </div>
      ) : trend ? (
        <div className="t-caption font-semibold mt-1.5 leading-snug">
          {trend}
        </div>
      ) : null}
    </>
  );

  return href ? (
    <Link href={href} className={rootClass}>{body}</Link>
  ) : (
    <div className={rootClass}>{body}</div>
  );
}

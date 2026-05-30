"use client";

import type { ReactNode } from "react";
import { motion } from "motion/react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { cn } from "@/lib/utils";

// ─────────── ChipTone + StatusBadge ───────────
//
// One badge to rule them all. Replace inline `<span class="bg-rose-50
// text-rose-700 px-2 ...">` patterns with <StatusBadge tone="red">…
// </StatusBadge> everywhere. Tones map to the existing `.chip-*` classes
// in globals.css so changing the badge palette is a one-line edit.

export type ChipTone =
  | "green"   // on track / approved / verified / active
  | "amber"   // needs attention / pending
  | "red"     // critical / overdue / rejected / returned
  | "blue"    // submitted / informational
  | "grey"    // closed / draft / inactive
  | "edify"   // brand-neutral
  | "violet"; // category accent

// Tone classes — the /approvals page is the design source of truth, so
// every badge across the app reads as the same family.  Previously these
// mapped to `.chip-*` (pill shape, 11px semibold); now they render the
// rounded-md, 9.5px extrabold treatment used throughout /approvals.
//
// Dark-mode tints kept tasteful at ~15% bg / ~80% text so badges stay
// readable on the deep-teal page background.
export const toneClass: Record<ChipTone, string> = {
  green:  "bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300",
  amber:  "bg-amber-100   text-amber-700   dark:bg-amber-500/15   dark:text-amber-300",
  red:    "bg-rose-100    text-rose-700    dark:bg-rose-500/15    dark:text-rose-300",
  blue:   "bg-sky-100     text-sky-700     dark:bg-sky-500/15     dark:text-sky-300",
  grey:   "bg-slate-100   text-slate-600   dark:bg-slate-500/20   dark:text-slate-300",
  edify:  "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
  violet: "bg-violet-100  text-violet-700  dark:bg-violet-500/15  dark:text-violet-300",
};

// Canonical label → tone map. Use `statusTone("Approved")` so the same
// label always paints the same colour, regardless of which screen renders
// it. Falls back to "edify" for unknown labels.
const STATUS_TONE_MAP: Record<string, ChipTone> = {
  // Approval lifecycle
  Draft:       "grey",
  Submitted:   "blue",
  Pending:     "amber",
  "Pending Approval": "amber",
  Approved:    "green",
  Returned:    "red",
  Rejected:    "red",
  Verified:    "green",
  Cancelled:   "grey",
  // Operational status
  Active:      "green",
  "On Track":  "green",
  "Slightly Behind": "amber",
  Behind:      "amber",
  "Needs Attention": "amber",
  Overdue:     "red",
  Critical:    "red",
  "High Risk": "red",
  Closed:      "grey",
  Inactive:    "grey",
  // Finance / cost
  "Missing Cost Setting": "amber",
  "Funding Gap Detected": "red",
};

export function statusTone(label: string): ChipTone {
  return STATUS_TONE_MAP[label] ?? "edify";
}

export function StatusBadge({
  children,
  tone,
  className,
}: {
  children: ReactNode;
  /** Explicit tone override. If omitted, tone is derived from the label
   * via `statusTone()` when `children` is a string. */
  tone?: ChipTone;
  className?: string;
}) {
  const derived: ChipTone =
    tone ?? (typeof children === "string" ? statusTone(children) : "edify");
  // Inline /approvals-style markup (was `.chip` + tone class).  Same
  // shape, padding, font scale as the FundApprovalQueue status pills.
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap",
        toneClass[derived],
        className,
      )}
    >
      {children}
    </span>
  );
}

// ─────────── ProgressRing ───────────

export function ProgressRing({
  pct,
  size = 64,
  stroke = 6,
  color = "var(--color-edify-primary)",
  label,
  sublabel,
  trackColor = "#eef2f4",
  animate = true,
}: {
  pct: number;
  size?: number;
  stroke?: number;
  color?: string;
  label?: string;
  sublabel?: string;
  trackColor?: string;
  animate?: boolean;
}) {
  const r = size / 2 - stroke;
  const c = 2 * Math.PI * r;
  const off = c * (1 - pct / 100);
  return (
    <div className="relative inline-block" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={trackColor} strokeWidth={stroke} />
        {animate ? (
          <motion.circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={c}
            initial={{ strokeDashoffset: c }}
            animate={{ strokeDashoffset: off }}
            transition={{ duration: 0.8, ease: "easeOut" }}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        ) : (
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={c}
            strokeDashoffset={off}
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        )}
      </svg>
      {(label || sublabel) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center leading-tight">
          {label && <div className="text-[12px] font-extrabold tabular">{label}</div>}
          {sublabel && <div className="text-[9.5px] muted">{sublabel}</div>}
        </div>
      )}
    </div>
  );
}

// ─────────── MiniSparkline (Recharts) ───────────

function makeSpark(seed: number, trend: "up" | "down") {
  const out: { x: number; y: number }[] = [];
  let v = 50;
  for (let i = 0; i < 14; i++) {
    v += Math.sin((i + seed) * 1.3) * 6 + (trend === "up" ? 1.2 : -1.2) + Math.cos((i + seed) * 0.7) * 4;
    v = Math.max(8, Math.min(56, v));
    out.push({ x: i, y: v });
  }
  return out;
}

export function MiniSparkline({
  seed = 1,
  trend = "up",
  color,
  width = 140,
  height = 32,
}: {
  seed?: number;
  trend?: "up" | "down";
  color?: string;
  width?: number;
  height?: number;
}) {
  const data = makeSpark(seed, trend);
  const stroke = color ?? (trend === "up" ? "#16a34a" : "#ef4444");
  const id = `spark-${seed}-${trend}`;
  // ResponsiveContainer + min-width prevents Recharts' `width(-1)/height(-1)`
  // warnings when the parent measures 0 on first paint. The fixed-width
  // legacy prop is kept as a fallback in case the container can't size.
  void width;
  return (
    <div style={{ width: "100%", height }} role="img" aria-label="Trend">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity={0.22} />
              <stop offset="100%" stopColor={stroke} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="y"
            stroke={stroke}
            strokeWidth={1.8}
            fill={`url(#${id})`}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

// ─────────── DonutChart ───────────

export function DonutChart({
  slices,
  size = 110,
  thickness = 14,
  centerLabel,
  centerSublabel,
}: {
  slices: { label: string; value: number; pct: number; color: string }[];
  size?: number;
  thickness?: number;
  centerLabel?: string | number;
  centerSublabel?: string;
}) {
  const r = size / 2 - thickness;
  const c = 2 * Math.PI * r;
  // Precompute the cumulative offset for each slice so the render path is
  // pure — the React compiler rejects reassigning a let inside `.map()`.
  const lens = slices.map((s) => (s.pct / 100) * c);
  const offsets = lens.reduce<number[]>((acc) => {
    const last = acc.length === 0 ? 0 : acc[acc.length - 1] + lens[acc.length - 1];
    return [...acc, last];
  }, []);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg viewBox={`0 0 ${size} ${size}`} className="w-full h-full -rotate-90">
        {slices.map((s, i) => {
          const len = lens[i];
          const dasharray = `${len} ${c - len}`;
          return (
            <circle
              key={s.label}
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={s.color}
              strokeWidth={thickness}
              strokeDasharray={dasharray}
              strokeDashoffset={-offsets[i]}
            />
          );
        })}
      </svg>
      {(centerLabel !== undefined || centerSublabel) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center leading-tight">
          {centerLabel !== undefined && (
            <div className="text-[18px] font-extrabold tabular">{centerLabel}</div>
          )}
          {centerSublabel && <div className="text-[10px] muted">{centerSublabel}</div>}
        </div>
      )}
    </div>
  );
}

// ─────────── SectionCard ───────────

export function SectionCard({
  title,
  subtitle,
  icon,
  actions,
  children,
  className,
  span,
  id,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  span?: number; // col-span override
  id?: string;
}) {
  return (
    <section id={id} className={cn("card p-3.5 overflow-hidden rounded-2xl flex flex-col h-full", span && `col-span-${span}`, className)}>
      <div className="flex items-start justify-between gap-3 mb-2.5">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            {icon && (
              <span
                className="w-6 h-6 rounded-md flex items-center justify-center shrink-0"
                style={{ background: "var(--color-edify-soft)", color: "var(--color-edify-primary)" }}
              >
                {icon}
              </span>
            )}
            <h3 className="text-body-lg font-extrabold tracking-tight truncate">{title}</h3>
          </div>
          {subtitle && <div className="text-[11.5px] muted mt-0.5 line-clamp-2">{subtitle}</div>}
        </div>
        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
      <div className="flex-1 min-h-0 flex flex-col">{children}</div>
    </section>
  );
}

// ─────────── Generic KPI card (used outside the screenshot-specific KPI rows) ───────────

export function KpiCard({
  label,
  value,
  trend,
  trendType = "up",
  icon,
  iconTone = "edify",
  caption,
  spark,
}: {
  label: string;
  value: ReactNode;
  trend?: string;
  trendType?: "up" | "down";
  icon?: ReactNode;
  iconTone?: ChipTone;
  caption?: string;
  spark?: { seed: number; trend: "up" | "down" };
}) {
  const tile =
    iconTone === "amber"
      ? "icon-tile-amber"
      : iconTone === "red"
        ? "icon-tile-red"
        : iconTone === "green"
          ? "icon-tile-green"
          : iconTone === "blue"
            ? "icon-tile-blue"
            : iconTone === "violet"
              ? "icon-tile-violet"
              : "";
  // Tone → glow class.  Mirrors the /approvals KPI tile palette so
  // every dashboard's KPI surface reads as the same family.
  const glow =
    iconTone === "amber"
      ? "glow-amber"
      : iconTone === "red"
        ? "glow-rose"
        : iconTone === "green"
          ? "glow-emerald"
          : "glow-slate";
  const trendCls = trendType === "up" ? "text-emerald-700 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400";
  return (
    <div className="card card-lift tile-in cursor-default p-3">
      <div className="flex items-start gap-2.5">
        {icon && (
          <span className={cn("icon-tile", tile)} style={{ width: 36, height: 36 }}>
            {icon}
          </span>
        )}
        <div className="text-[10px] muted font-bold uppercase tracking-wide leading-tight line-clamp-2 min-w-0 flex-1">
          {label}
        </div>
      </div>
      <div className={cn(
        "text-[18px] font-extrabold tabular mt-2.5 leading-none num-hero text-[var(--text-primary)]",
        glow,
      )}>
        {value}
      </div>
      {caption && <div className="text-[11px] muted font-medium mt-1">{caption}</div>}
      {trend && <div className={cn("text-caption font-semibold mt-1", trendCls)}>{trend}</div>}
      {spark && (
        <div className="mt-2">
          <MiniSparkline seed={spark.seed} trend={spark.trend} />
        </div>
      )}
    </div>
  );
}

// ─────────── TableEmptyRow ───────────
//
// Drop into a <tbody> after the .map(...) to show a helpful empty state
// when the data array is empty. Spans all columns automatically.
//
//   <tbody>
//     {rows.map(...)}
//     {rows.length === 0 && (
//       <TableEmptyRow colSpan={9} title="No plans yet" body="..." />
//     )}
//   </tbody>
export function TableEmptyRow({
  colSpan,
  title,
  body,
  action,
}: {
  colSpan: number;
  title: string;
  body?: string;
  action?: ReactNode;
}) {
  return (
    <tr>
      <td colSpan={colSpan} className="py-8">
        <div className="flex flex-col items-center text-center px-4">
          <div className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center mb-2">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M22 12h-6l-2 3h-4l-2-3H2" />
              <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" />
            </svg>
          </div>
          <div className="text-body font-extrabold tracking-tight">{title}</div>
          {body && <div className="text-[11px] muted mt-1 max-w-[420px] leading-snug">{body}</div>}
          {action && <div className="mt-3">{action}</div>}
        </div>
      </td>
    </tr>
  );
}

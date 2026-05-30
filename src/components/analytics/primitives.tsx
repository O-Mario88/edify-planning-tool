"use client";

import { type ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

// Analytics primitives — a small kit of reliable, deterministic chart
// and layout components built on inline SVG + CSS. No chart library, so
// no ResponsiveContainer measure-timing issues; every render is exact.

export type Tone = "emerald" | "sky" | "violet" | "amber" | "rose" | "slate";

export const TONE: Record<
  Tone,
  { text: string; bg: string; soft: string; dot: string; ring: string; hex: string; barFrom: string }
> = {
  emerald: { text: "text-emerald-700", bg: "bg-emerald-500", soft: "bg-emerald-50", dot: "bg-emerald-500", ring: "ring-emerald-200/70", hex: "#10B981", barFrom: "from-emerald-400 to-emerald-600" },
  sky:     { text: "text-sky-700",     bg: "bg-sky-500",     soft: "bg-sky-50",     dot: "bg-sky-500",     ring: "ring-sky-200/70",     hex: "#3B82F6", barFrom: "from-sky-400 to-sky-600" },
  violet:  { text: "text-violet-700",  bg: "bg-violet-500",  soft: "bg-violet-50",  dot: "bg-violet-500",  ring: "ring-violet-200/70",  hex: "#8B5CF6", barFrom: "from-violet-400 to-violet-600" },
  amber:   { text: "text-amber-700",   bg: "bg-amber-500",   soft: "bg-amber-50",   dot: "bg-amber-500",   ring: "ring-amber-200/70",   hex: "#F59E0B", barFrom: "from-amber-400 to-amber-600" },
  rose:    { text: "text-rose-700",    bg: "bg-rose-500",    soft: "bg-rose-50",    dot: "bg-rose-500",    ring: "ring-rose-200/70",    hex: "#F43F5E", barFrom: "from-rose-400 to-rose-600" },
  slate:   { text: "text-slate-600",   bg: "bg-slate-400",   soft: "bg-slate-50",   dot: "bg-slate-400",   ring: "ring-slate-200/70",   hex: "#94A3B8", barFrom: "from-slate-300 to-slate-500" },
};

// ── Card ───────────────────────────────────────────────────────────────

export function ACard({
  title,
  subtitle,
  action,
  children,
  className,
  pad = true,
}: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  pad?: boolean;
}) {
  return (
    <article className={cn("card flex flex-col overflow-hidden", pad && "p-5 lg:p-6", className)}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 mb-3">
          <div className="min-w-0">
            {title && (
              <h3 className="text-[13.5px] font-extrabold tracking-tight text-slate-900">
                {title}
              </h3>
            )}
            {subtitle && (
              <p className="text-caption text-slate-500 font-semibold mt-0.5">{subtitle}</p>
            )}
          </div>
          {action && <div className="shrink-0">{action}</div>}
        </header>
      )}
      {children}
    </article>
  );
}

// ── Section heading (between cards) ────────────────────────────────────

export function SectionHeading({ title, sub }: { title: string; sub?: string }) {
  return (
    <div className="flex items-baseline gap-2 flex-wrap mt-1">
      <h2 className="text-[15px] font-extrabold tracking-tight text-slate-900">{title}</h2>
      {sub && <span className="text-[11px] text-slate-500 font-semibold">{sub}</span>}
    </div>
  );
}

// ── Trend chip ─────────────────────────────────────────────────────────

export function TrendChip({ value, up }: { value: string; up: boolean }) {
  const flat = value === "0" || value === "—";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-0.5 px-1.5 py-[1.5px] rounded-md text-[9.5px] font-extrabold tabular",
        flat ? "bg-slate-100 text-slate-500" : up ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700",
      )}
    >
      {flat ? <Minus size={9} /> : up ? <ArrowUpRight size={9} strokeWidth={2.6} /> : <ArrowDownRight size={9} strokeWidth={2.6} />}
      {value}
    </span>
  );
}

// ── Status badge ───────────────────────────────────────────────────────

export function StatusBadge({ label, tone }: { label: string; tone: Tone }) {
  const t = TONE[tone];
  return (
    <span className={cn("inline-flex items-center gap-1.5 pl-1.5 pr-2 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", t.soft, t.text, "ring-1", t.ring)}>
      <span className={cn("w-1.5 h-1.5 rounded-full", t.dot)} />
      {label}
    </span>
  );
}

// ── Horizontal bar (single value) ──────────────────────────────────────

export function Bar({ pct, tone = "sky", track = true }: { pct: number; tone?: Tone; track?: boolean }) {
  return (
    <div className={cn("h-[5px] rounded-full overflow-hidden", track ? "bg-slate-100" : "bg-transparent")}>
      <div
        className={cn("h-full rounded-full bg-gradient-to-r", TONE[tone].barFrom)}
        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
      />
    </div>
  );
}

// ── Grouped horizontal bars (compare 2-3 series per row) ───────────────

export type GroupBarSeries = { label: string; value: number; tone: Tone };

export function GroupedBarRow({
  name,
  series,
  max,
  meta,
}: {
  name: string;
  series: GroupBarSeries[];
  max: number;
  meta?: string;
}) {
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="text-[11.5px] font-extrabold text-slate-800 truncate">{name}</span>
        {meta && <span className="text-[10px] text-slate-400 font-semibold shrink-0">{meta}</span>}
      </div>
      <div className="flex flex-col gap-[3px]">
        {series.map((s) => (
          <div key={s.label} className="flex items-center gap-2">
            <span className="w-[58px] text-[9px] text-slate-400 font-bold uppercase tracking-[0.04em] shrink-0">
              {s.label}
            </span>
            <div className="flex-1 h-[7px] rounded-full bg-slate-100 overflow-hidden">
              <div
                className={cn("h-full rounded-full bg-gradient-to-r", TONE[s.tone].barFrom)}
                style={{ width: `${(s.value / max) * 100}%` }}
              />
            </div>
            <span className="w-[34px] text-right text-caption font-extrabold tabular text-slate-700 shrink-0">
              {s.value}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Multi-series line chart (SVG) ──────────────────────────────────────

export type LineSeries = { label: string; tone: Tone; values: number[]; dashed?: boolean };

export function LineChart({
  labels,
  series,
  height = 180,
  yMax,
  yUnit = "",
}: {
  labels: string[];
  series: LineSeries[];
  height?: number;
  yMax?: number;
  yUnit?: string;
}) {
  const W = 600;
  const H = height;
  const padL = 34;
  const padR = 8;
  const padT = 10;
  const padB = 22;
  const max = yMax ?? Math.max(...series.flatMap((s) => s.values)) * 1.1;
  const n = labels.length;
  const x = (i: number) => padL + (i / (n - 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - v / max) * (H - padT - padB);
  const ticks = 4;

  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="block" style={{ height }}>
      {/* gridlines */}
      {Array.from({ length: ticks + 1 }).map((_, i) => {
        const v = (max / ticks) * i;
        const yy = y(v);
        return (
          <g key={i}>
            <line x1={padL} y1={yy} x2={W - padR} y2={yy} stroke="#F1F5F8" strokeWidth={1} />
            <text x={padL - 6} y={yy + 3} textAnchor="end" fontSize={9} fontWeight={700} fill="#CBD5E1">
              {Math.round(v)}{yUnit}
            </text>
          </g>
        );
      })}
      {/* x labels */}
      {labels.map((l, i) => (
        <text key={l} x={x(i)} y={H - 6} textAnchor="middle" fontSize={9} fontWeight={700} fill="#94A3B8">
          {l}
        </text>
      ))}
      {/* series */}
      {series.map((s) => {
        const pts = s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
        return (
          <g key={s.label}>
            <polyline
              points={pts}
              fill="none"
              stroke={TONE[s.tone].hex}
              strokeWidth={2.5}
              strokeDasharray={s.dashed ? "5 4" : undefined}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
            {s.values.map((v, i) => (
              <circle key={i} cx={x(i)} cy={y(v)} r={3} fill="#fff" stroke={TONE[s.tone].hex} strokeWidth={2} />
            ))}
          </g>
        );
      })}
    </svg>
  );
}

export function Legend({ items }: { items: { label: string; tone: Tone; dashed?: boolean }[] }) {
  return (
    <ul className="flex items-center gap-3.5 flex-wrap">
      {items.map((it) => (
        <li key={it.label} className="inline-flex items-center gap-1.5">
          <span
            className="w-2.5 h-2.5 rounded-full"
            style={{
              backgroundColor: it.dashed ? "transparent" : TONE[it.tone].hex,
              border: it.dashed ? `2px dashed ${TONE[it.tone].hex}` : undefined,
            }}
          />
          <span className="text-caption text-slate-500 font-semibold">{it.label}</span>
        </li>
      ))}
    </ul>
  );
}

// ── Vertical column chart (baseline vs current per category) ───────────

export function ColumnChart({
  rows,
  height = 150,
  max,
}: {
  rows: { label: string; a: number; b: number }[];
  height?: number;
  max: number;
}) {
  return (
    <div className="flex items-end justify-between gap-2" style={{ height }}>
      {rows.map((r) => (
        <div key={r.label} className="flex-1 flex flex-col items-center gap-1 min-w-0">
          <div className="w-full flex items-end justify-center gap-1" style={{ height: height - 26 }}>
            <div
              className="w-1/2 max-w-[16px] rounded-t-[3px] bg-slate-200"
              style={{ height: `${(r.a / max) * 100}%` }}
              title={`Baseline ${r.a}`}
            />
            <div
              className="w-1/2 max-w-[16px] rounded-t-[3px] bg-gradient-to-t from-emerald-600 to-emerald-400"
              style={{ height: `${(r.b / max) * 100}%` }}
              title={`Current ${r.b}`}
            />
          </div>
          <span className="text-[9px] text-slate-400 font-bold">{r.label}</span>
        </div>
      ))}
    </div>
  );
}

// ── SVG donut ──────────────────────────────────────────────────────────

export function Donut({
  data,
  size = 150,
  thickness = 20,
  centerTop,
  centerMain,
  centerSub,
}: {
  data: { label: string; value: number; color: string }[];
  size?: number;
  thickness?: number;
  centerTop?: string;
  centerMain?: string;
  centerSub?: string;
}) {
  const r = (size - thickness) / 2;
  const c = 2 * Math.PI * r;
  const total = data.reduce((a, d) => a + d.value, 0) || 1;
  const gap = 3;
  // Prefix-sum cursor via slice/reduce so the .map is pure — a `let
  // cursor += arc` inside .map() trips React Compiler's
  // cannot-reassign rule.
  const arcs = data.map((d) => (d.value / total) * c);
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#F1F5F8" strokeWidth={thickness} />
        {data.map((d, i) => {
          const arc = arcs[i];
          const dash = Math.max(arc - gap, 1);
          const cursor = arcs.slice(0, i).reduce((a, b) => a + b, 0);
          const rot = (cursor / c) * 360 - 90;
          return (
            <circle
              key={i}
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke={d.color}
              strokeWidth={thickness}
              strokeDasharray={`${dash} ${c - dash}`}
              transform={`rotate(${rot} ${size / 2} ${size / 2})`}
            />
          );
        })}
      </svg>
      {(centerMain || centerTop) && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
          {centerTop && (
            <span className="text-[8px] text-slate-400 font-extrabold uppercase tracking-[0.12em]">{centerTop}</span>
          )}
          {centerMain && (
            <span className="text-[18px] font-extrabold tabular num-hero text-slate-900 leading-none mt-0.5">{centerMain}</span>
          )}
          {centerSub && (
            <span className="text-[8.5px] text-slate-500 font-semibold mt-0.5">{centerSub}</span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Data table ─────────────────────────────────────────────────────────

export type Col<T> = {
  key: string;
  header: string;
  align?: "left" | "right" | "center";
  width?: string;
  render: (row: T) => ReactNode;
};

export function DataTable<T>({
  columns,
  rows,
  minWidth = 720,
  rowKey,
}: {
  columns: Col<T>[];
  rows: T[];
  minWidth?: number;
  rowKey: (row: T, i: number) => string;
}) {
  return (
    <div className="overflow-x-auto -mx-1 px-1">
      <table className="w-full" style={{ minWidth }}>
        <thead>
          <tr className="text-[9px] text-slate-500 font-extrabold uppercase tracking-[0.07em] border-b border-[var(--color-edify-divider)]">
            {columns.map((c) => (
              <th
                key={c.key}
                scope="col"
                className={cn(
                  "py-2.5 pr-3 font-extrabold",
                  c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left",
                )}
                style={{ width: c.width }}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={rowKey(row, i)}
              className={cn("border-b border-[#F4F6F8] last:border-b-0 hover:bg-slate-50/60 transition-colors tile-in", `stagger-${(i % 8) + 1}`)}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={cn(
                    "py-2.5 pr-3 align-middle",
                    c.align === "right" ? "text-right" : c.align === "center" ? "text-center" : "text-left",
                  )}
                >
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Avatar chip ────────────────────────────────────────────────────────

const AVATAR_GRADIENTS = [
  "from-sky-400 to-sky-600",
  "from-violet-400 to-violet-600",
  "from-emerald-400 to-emerald-600",
  "from-amber-400 to-amber-600",
  "from-rose-400 to-rose-600",
];

export function Avatar({ initials, i = 0, size = 28 }: { initials: string; i?: number; size?: number }) {
  return (
    <span
      className={cn(
        "rounded-full grid place-items-center font-extrabold text-white shrink-0 bg-gradient-to-br shadow-[0_4px_10px_-4px_rgba(15,23,32,0.35)]",
        AVATAR_GRADIENTS[i % AVATAR_GRADIENTS.length],
      )}
      style={{ width: size, height: size, fontSize: size * 0.36 }}
    >
      {initials}
    </span>
  );
}

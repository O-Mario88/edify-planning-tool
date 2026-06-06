"use client";

import { useState } from "react";
import Link from "next/link";
import {
  Activity,
  ArrowUpRight,
  BookOpen,
  GraduationCap,
  Grid3x3,
  Heart,
  LineChart as LineIcon,
  MapPin,
  Scale,
  ScrollText,
  Shield,
  Sparkles,
  TrendingDown,
  Users,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  ResponsiveContainer,
  XAxis,
  YAxis,
} from "recharts";
import { SectionCard } from "@/components/ui/primitives";
import {
  cceoHeatmap,
  coreSsaTrend,
  ssaInterventionRows,
  type CceoInterventionRow,
} from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

// One card, three lenses on the same SSA dataset. Replaces the three
// competing cards (Trend / Intervention / Heatmap) that all told
// variants of the same story. Segmented control = touch-friendly on
// mobile, keyboard-navigable on desktop.

type ViewKey = "trend" | "intervention" | "district";

const VIEWS: { key: ViewKey; label: string; short: string; icon: LucideIcon }[] = [
  { key: "trend",        label: "Trend",          short: "Trend",   icon: LineIcon  },
  { key: "intervention", label: "By Intervention", short: "Bars",   icon: Activity  },
  { key: "district",     label: "By District",     short: "Heatmap", icon: Grid3x3   },
];

const ICON_MAP: Record<CceoInterventionRow["icon"], LucideIcon> = {
  heart:         Heart,
  book:          BookOpen,
  shield:        Shield,
  graduationCap: GraduationCap,
  schoolBook:    ScrollText,
  scale:         Scale,
  wallet:        Wallet,
  users:         Users,
};

function barColor(score: number) {
  if (score >= 7.5) return "#10b981"; // emerald
  if (score >= 6.5) return "#f59e0b"; // amber
  return "#ef4444";                   // rose
}

// Color ramp keyed to the SSA score (0–10). Same ramp as the original
// heatmap so the visual stays consistent.
function heatTone(score: number): { bg: string; text: string } {
  if (score >= 8.0)  return { bg: "#10b981",  text: "#ffffff" };
  if (score >= 7.5)  return { bg: "#34d399",  text: "#0f3a2c" };
  if (score >= 7.0)  return { bg: "#a7f3d0",  text: "#065f46" };
  if (score >= 6.5)  return { bg: "#fef3c7",  text: "#92400e" };
  if (score >= 6.0)  return { bg: "#fde68a",  text: "#78350f" };
  return                       { bg: "#fecaca",  text: "#991b1b" };
}

// The official 8 SSA interventions (display order matches the canonical list).
const DISTRICT_COLUMNS: { key: keyof (typeof cceoHeatmap)[number]["scores"]; label: string; short: string }[] = [
  { key: "christlike",  label: "Christ-like Behavior",        short: "Christ-like" },
  { key: "word",        label: "Exposure to the Word of God", short: "Word of God" },
  { key: "leadership",  label: "Leadership Best Practice",    short: "Leadership" },
  { key: "teaching",    label: "Teaching Environment",        short: "Teaching" },
  { key: "learning",    label: "Learning Environment",        short: "Learning" },
  { key: "government",  label: "Government Requirements",      short: "Gov't Req." },
  { key: "fees",        label: "Fees / Budget / Accounts",    short: "Fees/Budget" },
  { key: "enrollment",  label: "Enrollment",                  short: "Enrollment" },
];

export function SsaQualityCard() {
  const [view, setView] = useState<ViewKey>("trend");

  // ─── Shared computations (used by headlines + body) ───
  const lastTrend  = coreSsaTrend[coreSsaTrend.length - 1];
  const firstTrend = coreSsaTrend[0];
  const prevTrend  = coreSsaTrend[coreSsaTrend.length - 2];
  const monthDelta = +(lastTrend.score - prevTrend.score).toFixed(1);
  const totalDelta = +(lastTrend.score - firstTrend.score).toFixed(1);

  const sortedInt = [...ssaInterventionRows].sort((a, b) => b.score - a.score);
  const bestInt   = sortedInt[0];
  const worstInt  = sortedInt[sortedInt.length - 1];

  const sortedDistricts = [...cceoHeatmap].sort((a, b) => b.avg - a.avg);
  const bestDistrict    = sortedDistricts[0];
  const worstDistrict   = sortedDistricts[sortedDistricts.length - 1];
  const dimensionAverages = DISTRICT_COLUMNS.map((c) => ({
    key: c.key,
    label: c.short,
    avg: +(cceoHeatmap.reduce((a, r) => a + r.scores[c.key], 0) / cceoHeatmap.length).toFixed(1),
  }));
  const weakestDim = dimensionAverages.reduce((w, d) => (d.avg < w.avg ? d : w));

  // Headline switches per active view so each lens tells its own story.
  const headline =
    view === "trend"
      ? `${lastTrend.month} hit ${lastTrend.score} — best month in the trailing ${coreSsaTrend.length}. +${monthDelta} vs ${prevTrend.month}, +${totalDelta} since ${firstTrend.month}.`
      : view === "intervention"
        ? `${bestInt.label} leads at ${bestInt.score.toFixed(1)} — ${worstInt.label} trails at ${worstInt.score.toFixed(1)}.`
        : `${bestDistrict.district} leads at ${bestDistrict.avg.toFixed(1)} — ${worstDistrict.district} trails at ${worstDistrict.avg.toFixed(1)}.`;

  return (
    <SectionCard
      icon={<Activity size={13} />}
      title="SSA Quality"
      subtitle={headline}
      actions={
        <Link
          href="/ssa"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* Segmented control — 3 tabs in a tinted track. */}
      <div
        role="tablist"
        aria-label="SSA Quality view"
        className="inline-flex items-center gap-1 rounded-xl bg-[var(--color-edify-soft)]/60 border border-[var(--color-edify-border)] p-1 mb-3"
      >
        {VIEWS.map((v) => {
          const Icon = v.icon;
          const active = view === v.key;
          return (
            <button
              key={v.key}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls={`ssa-view-${v.key}`}
              onClick={() => setView(v.key)}
              className={cn(
                "inline-flex items-center gap-1.5 h-8 px-3 rounded-lg text-[12px] font-semibold transition-all",
                active
                  ? "bg-white text-slate-900 shadow-sm ring-1 ring-[var(--color-edify-border)]"
                  : "text-slate-600 hover:text-slate-900",
              )}
            >
              <Icon size={12} />
              <span className="hidden sm:inline">{v.label}</span>
              <span className="sm:hidden">{v.short}</span>
            </button>
          );
        })}
      </div>

      {/* Active view */}
      <div id={`ssa-view-${view}`} role="tabpanel">
        {view === "trend" && (
          <TrendView />
        )}
        {view === "intervention" && (
          <InterventionView />
        )}
        {view === "district" && (
          <DistrictView />
        )}
      </div>

      {/* Stable takeaway — works across all 3 views. */}
      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-emerald-600" />
          <span className="font-bold">Strongest:</span>
          <span className="muted">{bestInt.label} ({bestInt.score.toFixed(1)})</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <TrendingDown size={12} className="text-rose-600" />
          <span className="font-bold">Push next:</span>
          <span className="muted">{weakestDim.label} ({weakestDim.avg}) · weakest in every district</span>
        </span>
      </div>
    </SectionCard>
  );
}

// ───────────── TrendView ─────────────

function TrendView() {
  const last = coreSsaTrend[coreSsaTrend.length - 1];

  return (
    <div className="relative h-[230px] -mx-1">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={coreSsaTrend} margin={{ top: 28, right: 12, bottom: 4, left: 0 }}>
          <defs>
            <linearGradient id="ssaq-trend-area" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"  stopColor="#3257d9" stopOpacity={0.22} />
              <stop offset="100%" stopColor="#3257d9" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="#eef2f4" strokeDasharray="0" vertical={false} />
          <YAxis
            domain={[0, 10]}
            ticks={[0, 2.5, 5, 7.5, 10]}
            tick={{ fontSize: 10, fill: "var(--color-edify-muted)" }}
            axisLine={false}
            tickLine={false}
            width={28}
          />
          <XAxis
            dataKey="month"
            tick={{ fontSize: 11, fill: "var(--color-edify-muted)" }}
            axisLine={false}
            tickLine={false}
          />
          <Area
            type="monotone"
            dataKey="score"
            stroke="none"
            fill="url(#ssaq-trend-area)"
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="score"
            stroke="#3257d9"
            strokeWidth={2.5}
            dot={{ r: 4, fill: "#3257d9", strokeWidth: 2, stroke: "#ffffff" }}
            activeDot={{ r: 5 }}
          />
          <ReferenceDot
            x={last.month}
            y={last.score}
            r={5}
            fill="#3257d9"
            stroke="#ffffff"
            strokeWidth={2}
          />
        </ComposedChart>
      </ResponsiveContainer>

      <div className="absolute right-2 top-0 rounded-lg border border-[var(--color-edify-border)] bg-white shadow-md px-2 py-1.5 text-left">
        <div className="text-[10px] muted font-semibold leading-tight">
          {last.month} 2025
        </div>
        <div className="text-body-lg font-extrabold tabular leading-none mt-0.5">
          {last.score}
        </div>
        <div className="text-[10px] text-emerald-600 font-semibold inline-flex items-center gap-0.5 leading-tight mt-0.5">
          <ArrowUpRight size={10} />
          +0.3 vs prior
        </div>
      </div>
    </div>
  );
}

// ───────────── InterventionView ─────────────

function InterventionView() {
  return (
    <>
      <ul className="space-y-2 flex-1">
        {ssaInterventionRows.map((row) => {
          const Icon = ICON_MAP[row.icon];
          const widthPct = (row.score / 10) * 100;
          const color = barColor(row.score);
          return (
            <li key={row.key} className="flex items-center gap-2">
              <Icon size={13} className="text-[var(--color-edify-muted)] shrink-0" />
              <span className="text-[11px] font-semibold flex-1 min-w-0 truncate max-w-[180px]">
                {row.label}
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{ width: `${widthPct}%`, backgroundColor: color }}
                />
              </div>
              <span className="text-[11.5px] font-extrabold tabular shrink-0 w-[28px] text-right">
                {row.score.toFixed(1)}
              </span>
            </li>
          );
        })}
      </ul>
      <div className="mt-3 ml-[210px] flex justify-between text-[10px] muted tabular pr-[36px]">
        {[0, 2, 4, 6, 8, 10].map((v) => (
          <span key={v}>{v}</span>
        ))}
      </div>
    </>
  );
}

// ───────────── DistrictView ─────────────

function DistrictView() {
  return (
    <div className="overflow-x-auto -mx-2 rounded-lg">
      <table className="w-full border-separate border-spacing-x-1 border-spacing-y-1 px-2">
        <thead>
          <tr>
            <th scope="col" className="text-left text-[10px] muted font-bold uppercase tracking-wide pb-1.5">
              District
            </th>
            {DISTRICT_COLUMNS.map((c) => (
              <th
                key={c.key}
                className="text-center text-[9.5px] muted font-bold leading-tight pb-1.5"
                title={c.label}
              >
                {c.short}
              </th>
            ))}
            <th scope="col" className="text-center text-[9.5px] muted font-bold uppercase tracking-wide pb-1.5">
              Avg
            </th>
          </tr>
        </thead>
        <tbody>
          {cceoHeatmap.map((row) => (
            <tr key={row.district}>
              <td className="text-[11.5px] font-semibold whitespace-nowrap pr-2 inline-flex items-center gap-1">
                <MapPin size={10} className="text-[var(--color-edify-muted)]" />
                {row.district}
              </td>
              {DISTRICT_COLUMNS.map((c) => {
                const score = row.scores[c.key];
                const tone = heatTone(score);
                return (
                  <td key={c.key} className="text-center">
                    <span
                      className="inline-block w-full min-w-[44px] py-1.5 rounded-md text-[11px] font-extrabold tabular"
                      style={{ backgroundColor: tone.bg, color: tone.text }}
                    >
                      {score.toFixed(1)}
                    </span>
                  </td>
                );
              })}
              <td className="text-center">
                <span
                  className="inline-block w-full min-w-[44px] py-1.5 rounded-md text-[11px] font-extrabold tabular ring-1 ring-black/5"
                  style={{
                    backgroundColor: heatTone(row.avg).bg,
                    color: heatTone(row.avg).text,
                  }}
                >
                  {row.avg.toFixed(1)}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

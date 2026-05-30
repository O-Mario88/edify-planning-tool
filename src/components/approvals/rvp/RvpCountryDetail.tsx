"use client";

import {
  CheckCircle2,
  Download,
  Eye,
  GraduationCap,
  Heart,
  MessageSquare,
  Plus,
  School,
  Users,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer } from "recharts";
import {
  rvpActiveCountry,
  rvpDetailKpis,
  rvpPlanActivities,
  rvpSpendingByCategory,
  rvpSpendingTotal,
  type RvpDetailKpi,
  type RvpPlanActivity,
} from "@/lib/rvp-fund-approvals-mock";
import { cn } from "@/lib/utils";

const ACT_ICON: Record<RvpPlanActivity["icon"], LucideIcon> = {
  school:        School,
  users:         Users,
  userGroup:     UsersRound,
  graduationCap: GraduationCap,
  heart:         Heart,
};

const ACT_TONE: Record<RvpPlanActivity["iconTone"], { bg: string; fg: string }> = {
  blue:    { bg: "bg-sky-100",     fg: "text-sky-700" },
  amber:   { bg: "bg-amber-100",   fg: "text-amber-700" },
  violet:  { bg: "bg-violet-100",  fg: "text-violet-700" },
  rose:    { bg: "bg-rose-100",    fg: "text-rose-700" },
  emerald: { bg: "bg-emerald-100", fg: "text-emerald-700" },
};

export function RvpCountryDetail() {
  return (
    <article className="card p-4 flex flex-col">
      {/* Header */}
      <header className="flex items-start justify-between gap-3 flex-wrap pb-3 border-b border-[#eef2f4]">
        <div className="flex items-start gap-3 min-w-0">
          <span className="text-[32px] leading-none shrink-0">{rvpActiveCountry.flag}</span>
          <div className="min-w-0">
            <h2 className="text-[16px] font-extrabold tracking-tight">
              {rvpActiveCountry.country} — Country Plan & Funds
            </h2>
            <div className="text-[11px] muted mt-0.5 leading-tight">
              Lead: <span className="text-slate-700 font-semibold">{rvpActiveCountry.leadName} ({rvpActiveCountry.leadRole})</span>
              {" · "}
              <span className="text-slate-700 font-semibold">{rvpActiveCountry.districts} districts</span>
              {" · "}
              <span>{rvpActiveCountry.fyLabel}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-1.5 sm:gap-2 shrink-0">
          <button type="button" className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-[12px] font-semibold text-slate-700">
            <Eye size={12} />
            View Plan
          </button>
          <button type="button" className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl bg-white border border-[var(--color-edify-border)] hover:bg-slate-50 text-[12px] font-semibold text-slate-700">
            <MessageSquare size={12} />
            Message Lead
          </button>
          <button type="button" className="inline-flex items-center gap-1.5 h-9 px-3 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-[12px] font-extrabold shadow-[0_10px_28px_-12px_rgba(15,23,32,0.45)]">
            <CheckCircle2 size={12} />
            Approve All ({rvpActiveCountry.approveAllCount})
          </button>
        </div>
      </header>

      {/* Detail KPI strip — 5 tiles */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 py-4 border-b border-[#eef2f4]">
        {rvpDetailKpis.map((k, i) => (
          <DetailKpiTile key={k.key} k={k} idx={i} />
        ))}
      </div>

      {/* Tabs + actions */}
      <div className="flex items-center justify-between gap-2 flex-wrap py-3 border-b border-[#eef2f4]">
        <nav className="flex items-center gap-1 overflow-x-auto -mx-1 px-1">
          <Tab label="Plan Overview" active />
          <Tab label="Funds Requests (5)" />
          <Tab label="Budget Breakdown" />
          <Tab label="Activity Log" />
        </nav>
        <div className="flex items-center gap-1.5 shrink-0">
          <button type="button" className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[11.5px] font-semibold text-slate-700">
            <Download size={11} />
            Download
          </button>
          <button type="button" className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white hover:bg-slate-50 text-[11.5px] font-semibold text-slate-700">
            <Plus size={11} />
            Add Note
          </button>
        </div>
      </div>

      {/* Body — Plan Summary (8 cols) + Spending by Category (4 cols) */}
      <div className="grid grid-cols-12 gap-4 pt-4">
        <div className="col-span-12 lg:col-span-7">
          <h3 className="text-body font-extrabold tracking-tight mb-2.5">FY 2026 Plan Summary</h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {rvpPlanActivities.map((a, i) => (
              <ActivityTile
                key={a.key}
                a={a}
                stagger={["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5"][i] ?? ""}
              />
            ))}
          </div>
        </div>

        <div className="col-span-12 lg:col-span-5">
          <SpendingByCategory />
        </div>
      </div>
    </article>
  );
}

// ───────────── Detail KPI Tile ─────────────

function DetailKpiTile({ k, idx }: { k: RvpDetailKpi; idx: number }) {
  const stagger = ["stagger-1","stagger-2","stagger-3","stagger-4","stagger-5"][idx] ?? "";
  return (
    <div className={cn(
      "rounded-xl border border-[var(--color-edify-border)] bg-white p-2.5 card-lift cursor-default tile-in flex flex-col gap-1",
      stagger,
    )}>
      <div className="text-[9.5px] muted font-bold uppercase tracking-wide leading-tight">{k.label}</div>
      <div className="flex items-end justify-between gap-2">
        <span className="text-[16px] font-extrabold tabular text-slate-900 leading-none num-hero glow-emerald">
          {k.value}
        </span>
        {typeof k.ringPct === "number" && (
          <DetailRing pct={k.ringPct} />
        )}
      </div>
      {k.caption && <div className="text-[10px] muted font-semibold truncate">{k.caption}</div>}
    </div>
  );
}

function DetailRing({ pct }: { pct: number }) {
  const SIZE = 32;
  const STROKE = 4;
  const R = (SIZE - STROKE) / 2;
  const C = 2 * Math.PI * R;
  const dash = C * (1 - pct / 100);
  return (
    <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="-rotate-90 shrink-0">
      <circle cx={SIZE/2} cy={SIZE/2} r={R} stroke="#eef2f4" strokeWidth={STROKE} fill="none" />
      <circle cx={SIZE/2} cy={SIZE/2} r={R} stroke="#3b82f6" strokeWidth={STROKE} fill="none"
              strokeDasharray={C} strokeDashoffset={dash} strokeLinecap="round" />
    </svg>
  );
}

function Tab({ label, active }: { label: string; active?: boolean }) {
  return (
    <button
      type="button"
      className={cn(
        "h-8 px-3 rounded-lg text-[12px] font-semibold whitespace-nowrap transition-colors",
        active
          ? "bg-slate-900 text-white"
          : "text-slate-600 hover:text-slate-900 hover:bg-slate-50",
      )}
    >
      {label}
    </button>
  );
}

// ───────────── Activity Tile ─────────────

function ActivityTile({ a, stagger }: { a: RvpPlanActivity; stagger: string }) {
  const Icon = ACT_ICON[a.icon];
  const tone = ACT_TONE[a.iconTone];
  return (
    <div className={cn(
      "rounded-xl border border-[var(--color-edify-border)] bg-white p-3 flex items-center gap-2.5 card-lift cursor-default tile-in",
      stagger,
    )}>
      <span className={cn("w-9 h-9 rounded-lg grid place-items-center shrink-0", tone.bg)}>
        <Icon size={16} className={tone.fg} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-caption muted font-semibold leading-tight truncate">{a.label}</div>
        <div className="flex items-baseline gap-1 mt-0.5 flex-wrap">
          <span className="text-[15px] font-extrabold tabular text-slate-900 num-hero">{a.planned}</span>
          <span className="text-[9.5px] muted font-semibold uppercase tracking-wide">planned</span>
        </div>
        <div className="flex items-baseline gap-1 flex-wrap">
          <span className="text-[12px] font-extrabold tabular text-emerald-700 num-hero">{a.requested}</span>
          <span className="text-[9.5px] muted font-semibold">requested</span>
        </div>
      </div>
    </div>
  );
}

// ───────────── Spending by Category ─────────────

function SpendingByCategory() {
  const data = rvpSpendingByCategory.map((s) => ({ name: s.label, value: s.pct, color: s.color }));
  return (
    <div>
      <h3 className="text-body font-extrabold tracking-tight mb-2.5">Spending by Category</h3>
      <div className="flex items-center gap-4">
        <div className="relative w-[150px] h-[150px] shrink-0">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie data={data} innerRadius={50} outerRadius={70} dataKey="value" paddingAngle={1} stroke="none">
                {data.map((d, i) => <Cell key={i} fill={d.color} />)}
              </Pie>
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none">
            <span className="text-[18px] font-extrabold tabular leading-none num-hero glow-emerald">{rvpSpendingTotal}</span>
            <span className="text-[9.5px] muted font-bold uppercase tracking-wide mt-0.5">Total Requested</span>
          </div>
        </div>
        <ul className="flex-1 min-w-0 flex flex-col gap-1.5">
          {rvpSpendingByCategory.map((s) => (
            <li key={s.key} className="flex items-center gap-2 text-[11px]">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
              <span className="flex-1 muted font-semibold truncate">{s.label}</span>
              <span className="font-extrabold tabular text-slate-900 num-hero">{s.amount}</span>
              <span className="muted font-semibold tabular text-[10px]">({s.pct}%)</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

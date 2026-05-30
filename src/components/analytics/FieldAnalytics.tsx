"use client";

import { useState } from "react";
import {
  CalendarRange,
  ChevronDown,
  Download,
  Database,
  SlidersHorizontal,
  LifeBuoy,
  ClipboardCheck,
} from "lucide-react";
import {
  analyticsMeta,
  insightHero,
  storyKpis,
  type StoryKpi,
} from "@/lib/analytics-mock";
import type { DonorMetricSnapshot } from "@/lib/donor-metrics-types";
import { DonorReportingImpact } from "@/components/donor-reporting/DonorReportingImpact";
import { TONE, TrendChip } from "./primitives";
import {
  OverviewTab,
  StaffTab,
  SchoolsTab,
  SsaTab,
  OneTestTab,
  PartnersTab,
  FundingTab,
  SupportTab,
} from "./tabs";
import { PageHeader } from "@/components/ui/PageHeader";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "staff",    label: "Staff Performance" },
  { key: "schools",  label: "School Improvement" },
  { key: "ssa",      label: "SSA" },
  { key: "onetest",  label: "One Test Literacy" },
  { key: "partners", label: "Partner Delivery" },
  { key: "funding",  label: "Funding" },
  { key: "support",  label: "Support Signals" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

const FILTERS = [
  "FY 2024/25",
  "May 2025",
  "Uganda",
  "All Districts",
  "All Program Leads",
  "All Activity Types",
];

export function FieldAnalytics({
  role = "CountryProgramLead",
  userName = "Daniel Mwangi",
  donorSnapshot,
}: {
  role?: string;
  userName?: string;
  donorSnapshot?: DonorMetricSnapshot;
}) {
  const [tab, setTab] = useState<TabKey>("overview");

  const roleLabel =
    role === "CountryDirector"
      ? "Country Director view"
      : role === "RVP"
        ? "Regional VP view"
        : role === "ImpactAssessment"
          ? "Impact Assessment view"
          : role === "HumanResource"
            ? "People & Performance view"
            : role === "CCEO"
              ? "My performance view"
              : "Program Lead view";

  return (
    <>
      {/* ── Header ──────────────────────────────────────────────── */}
      <PageHeader
        title="Field Performance & School Improvement Analytics"
        subtitle="Track staff activity, verified field work, school improvement, SSA growth, and literacy outcomes from one evidence dashboard."
        titleBadge={
          <span className="inline-flex items-center gap-1 text-[10px] font-extrabold uppercase tracking-[0.12em] text-[var(--color-edify-primary)] bg-[var(--color-edify-soft)] px-2 py-[3px] rounded-md">
            Impact Analytics · {roleLabel} · {userName}
          </span>
        }
        actions={
          <>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 h-10 px-3 rounded-xl bg-white ring-1 ring-[var(--color-edify-border)] hover:ring-slate-300 text-body font-semibold text-slate-700 shadow-sm transition-all"
            >
              <Database size={13} className="text-slate-400" />
              View Raw Data
            </button>
            <button
              type="button"
              className="inline-flex items-center gap-1.5 h-10 px-3.5 rounded-xl bg-slate-900 hover:bg-slate-800 text-white text-body font-extrabold shadow-[0_10px_28px_-12px_rgba(15,23,32,0.55)] transition-colors"
            >
              <Download size={13} strokeWidth={2.4} />
              Export Report
            </button>
          </>
        }
        meta={
          <div className="flex items-center gap-1.5 flex-wrap">
            {FILTERS.map((f, i) => (
              <button
                key={f}
                type="button"
                className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg bg-white ring-1 ring-[var(--color-edify-border)] hover:ring-slate-300 text-[11px] font-semibold text-slate-700 shadow-sm transition-all"
              >
                {i === 0 && <CalendarRange size={12} className="text-slate-400" />}
                {f}
                <ChevronDown size={11} className="text-slate-400" />
              </button>
            ))}
            <button
              type="button"
              className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg bg-[var(--color-edify-soft)] ring-1 ring-[var(--color-edify-border)] hover:ring-slate-300 text-[11px] font-extrabold text-[var(--color-edify-primary)] transition-all"
            >
              <SlidersHorizontal size={12} />
              More filters
            </button>
          </div>
        }
      />

      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 space-y-4">
        {/* ── Insight Hero ──────────────────────────────────────── */}
        <section className="rounded-2xl overflow-hidden relative bg-gradient-to-br from-[#0F1722] via-[#15202E] to-[#1C2F3A] ring-1 ring-[#26344A] shadow-[0_18px_44px_-18px_rgba(15,23,32,0.45)]">
          <div
            className="absolute inset-0 opacity-[0.5] pointer-events-none"
            style={{
              background:
                "radial-gradient(420px 200px at 88% 12%, rgba(16,185,129,0.18), transparent 70%), radial-gradient(360px 200px at 12% 95%, rgba(59,130,246,0.16), transparent 70%)",
            }}
          />
          <div className="relative p-5 lg:p-6">
            <div className="flex items-center gap-2 mb-2.5">
              <span className="text-[9.5px] font-extrabold uppercase tracking-[0.14em] text-emerald-300">
                This Month&apos;s biggest finding
              </span>
              <span className="text-[9.5px] font-semibold text-slate-400">
                {analyticsMeta.periodLabel} · {analyticsMeta.country}
              </span>
            </div>
            <p className="text-[15px] lg:text-[16.5px] font-bold text-white leading-[1.5] max-w-[860px] tracking-tight">
              {insightHero.headline}
            </p>

            <div className="flex items-center gap-1.5 flex-wrap mt-3.5">
              {insightHero.chips.map((c) => (
                <span
                  key={c.label}
                  className={cn(
                    "inline-flex items-center gap-1.5 px-2.5 py-[5px] rounded-lg text-[11px] font-extrabold tabular ring-1",
                    "bg-white/[0.06] ring-white/10 text-white",
                  )}
                >
                  <span className={cn("w-1.5 h-1.5 rounded-full", TONE[c.tone].bg)} />
                  {c.label}
                </span>
              ))}
            </div>

            <div className="flex items-center gap-2 mt-4 flex-wrap">
              <button
                type="button"
                className="inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-emerald-500 hover:bg-emerald-400 text-white text-[12px] font-extrabold shadow-[0_12px_28px_-12px_rgba(16,185,129,0.7)] transition-colors"
              >
                <LifeBuoy size={14} strokeWidth={2.4} />
                Review Staff Needing Support
              </button>
              <button
                type="button"
                className="inline-flex items-center gap-1.5 h-9 px-4 rounded-xl bg-white/[0.08] hover:bg-white/[0.14] ring-1 ring-white/15 text-white text-[12px] font-extrabold transition-colors"
              >
                <ClipboardCheck size={14} strokeWidth={2.4} />
                Open Verification Backlog
              </button>
            </div>
          </div>
        </section>

        {/* ── Donor Reporting Impact ───────────────────────────── */}
        {donorSnapshot && <DonorReportingImpact snapshot={donorSnapshot} />}

        {/* ── KPI Story Strip ──────────────────────────────────── */}
        <section className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-5 gap-3">
          {storyKpis.map((k, i) => (
            <KpiCard key={k.key} k={k} stagger={`stagger-${i + 1}`} />
          ))}
        </section>

        {/* ── Tabs ─────────────────────────────────────────────── */}
        {/* Phone: native select — 8 tabs in a horizontal scroller forces
            thumb-dragging to find a tab. The OS-rendered picker shows
            them all at once. `top-14` clears the sticky MobileTopBar
            (h-14 / 56px, z-30) — without the offset the select scrolls
            up behind the dark chrome and becomes unreachable. */}
        <div className="md:hidden sticky top-14 z-20 bg-[var(--color-page)]/95 backdrop-blur-sm py-1.5 -mx-1 px-1">
          <label className="block">
            <span className="sr-only">Select analytics tab</span>
            <div className="relative">
              <select
                value={tab}
                onChange={(e) => setTab(e.target.value as TabKey)}
                className="w-full h-11 pl-3.5 pr-9 rounded-xl bg-slate-900 text-white text-[13px] font-extrabold appearance-none shadow-[0_8px_18px_-8px_rgba(15,23,32,0.45)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]"
              >
                {TABS.map((t) => (
                  <option key={t.key} value={t.key} className="text-slate-900 bg-white">
                    {t.label}
                  </option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-white pointer-events-none" />
            </div>
          </label>
        </div>

        {/* Tablet + desktop: pill row. Wraps naturally so all 8 fit
            without horizontal scroll on common laptop widths. */}
        <nav className="hidden md:flex flex-wrap items-center gap-1.5 pb-1 sticky top-0 z-10 bg-[var(--color-page)]/95 backdrop-blur-sm py-1.5">
          {TABS.map((t) => {
            const active = t.key === tab;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={cn(
                  "h-9 px-3.5 rounded-lg text-[11.5px] font-extrabold whitespace-nowrap transition-all duration-200",
                  active
                    ? "bg-slate-900 text-white shadow-[0_8px_18px_-8px_rgba(15,23,32,0.45)]"
                    : "bg-white text-slate-600 ring-1 ring-[var(--color-edify-border)] hover:ring-slate-300 hover:text-slate-900",
                )}
              >
                {t.label}
              </button>
            );
          })}
        </nav>

        {/* ── Active tab panel ─────────────────────────────────── */}
        <div className="space-y-4">
          {tab === "overview" && <OverviewTab />}
          {tab === "staff"    && <StaffTab />}
          {tab === "schools"  && <SchoolsTab />}
          {tab === "ssa"      && <SsaTab />}
          {tab === "onetest"  && <OneTestTab />}
          {tab === "partners" && <PartnersTab />}
          {tab === "funding"  && <FundingTab />}
          {tab === "support"  && <SupportTab />}
        </div>
      </div>
    </>
  );
}

// ── KPI Story Card ──────────────────────────────────────────────────────

function KpiCard({ k, stagger }: { k: StoryKpi; stagger: string }) {
  const t = TONE[k.tone];
  return (
    <article className={cn("card card-lift cursor-default tile-in p-4 flex flex-col bg-white", stagger)}>
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="text-[9px] text-slate-500 font-extrabold uppercase tracking-[0.08em] leading-tight">
          {k.label}
        </span>
        <TrendChip value={k.trend} up={k.trendUp} />
      </div>
      <div className="flex items-baseline gap-1.5">
        <span className={cn("text-[26px] font-extrabold tabular num-hero leading-none text-slate-900")}>
          {k.hero}
        </span>
        <span className="text-caption font-semibold text-slate-500 truncate">{k.sub}</span>
      </div>
      <div className="mt-2 pt-2 border-t border-[var(--color-edify-divider)] flex items-center gap-1.5">
        <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", t.bg)} />
        <span className="text-[10px] font-semibold text-slate-500 leading-tight">{k.detail}</span>
      </div>
    </article>
  );
}

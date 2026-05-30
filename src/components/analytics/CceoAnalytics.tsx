"use client";

// CCEO Analytics — the evidence centre for a single field officer.
// Renders as page content inside the shared (shell) layout — the CCEO
// sidebar + chrome come from the route-group layout, so this surface
// never mounts its own navigation.

import { useState } from "react";
import {
  ChevronDown, ClipboardList, ShieldCheck, Cloud, TrendingUp,
  TrendingDown, Building2, GraduationCap, BadgeCheck,
  RefreshCw, Upload, Download, Sparkles, CheckCircle2, AlertTriangle,
  ArrowUp, ArrowDown, Info, RotateCcw, Clock, CalendarCheck, Navigation,
  Handshake, BookOpen, Users, MoreHorizontal, type LucideIcon,
} from "lucide-react";
import { Donut } from "@/components/analytics/primitives";
import { PageHeader } from "@/components/ui/PageHeader";
import { DonorReportingImpact } from "@/components/donor-reporting/DonorReportingImpact";
import type { DonorMetricSnapshot } from "@/lib/donor-metrics-types";

/* ───────────────────────── Card shell ───────────────────────── */

function Card({
  title, subtitle, action, children, className = "",
}: {
  title?: string; subtitle?: string; action?: string;
  children: React.ReactNode; className?: string;
}) {
  return (
    <section className={"bg-white rounded-xl border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(16,24,40,0.04)] flex flex-col " + className}>
      {(title || action) && (
        <div className="flex items-start justify-between gap-3 px-4 pt-3.5">
          <div className="min-w-0">
            {title && <h3 className="text-[13px] font-bold text-[#1a2330]">{title}</h3>}
            {subtitle && <p className="text-caption text-muted font-medium mt-0.5">{subtitle}</p>}
          </div>
          {action && <button className="text-[11px] font-semibold text-[#2f6fe0] hover:underline shrink-0">{action}</button>}
        </div>
      )}
      {children}
    </section>
  );
}

/* ───────────────────────── Charts ───────────────────────── */

function Sparkline({ values, color }: { values: number[]; color: string }) {
  const W = 220, H = 46, pad = 4;
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || 1;
  const x = (i: number) => pad + (i / (values.length - 1)) * (W - 2 * pad);
  const y = (v: number) => pad + (1 - (v - min) / span) * (H - 2 * pad);
  const line = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const area = `${pad},${H} ${line} ${W - pad},${H}`;
  const gid = "sp" + color.replace("#", "");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full" style={{ height: H }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.22" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={area} fill={`url(#${gid})`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {values.map((v, i) => (
        <circle key={i} cx={x(i)} cy={y(v)} r={i === values.length - 1 ? 2.6 : 1.8} fill="#fff" stroke={color} strokeWidth="1.6" />
      ))}
    </svg>
  );
}

const TREND = {
  labels: ["Week 1", "Week 2", "Week 3", "Week 4", "Week 5"],
  sub: ["Apr 28 – May 4", "May 5 – May 11", "May 12 – May 18", "May 19 – May 25", "May 26 – Jun 1"],
  series: [
    { label: "Planned",   color: "#94a3b8", dashed: true,  values: [10, 21, 30, 35, 37] },
    { label: "Completed", color: "#22c55e", dashed: false, values: [8, 16, 23, 27, 28] },
    { label: "Verified",  color: "#3b82f6", dashed: false, values: [5, 11, 16, 20, 22] },
  ],
};

function TrendChart() {
  const W = 760, H = 250, padL = 30, padR = 10, padT = 12, padB = 42;
  const yMax = 40, n = TREND.labels.length;
  const x = (i: number) => padL + (i / (n - 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - v / yMax) * (H - padT - padB);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
      {[0, 10, 20, 30, 40].map((v) => (
        <g key={v}>
          <line x1={padL} y1={y(v)} x2={W - padR} y2={y(v)} stroke="#eef1f4" strokeWidth="1" />
          <text x={padL - 7} y={y(v) + 3} textAnchor="end" fontSize="9" fontWeight="700" fill="#b3bcc5">{v}</text>
        </g>
      ))}
      {TREND.labels.map((l, i) => (
        <g key={l}>
          <text x={x(i)} y={H - 24} textAnchor="middle" fontSize="9.5" fontWeight="700" fill="#5b6675">{l}</text>
          <text x={x(i)} y={H - 11} textAnchor="middle" fontSize="8" fontWeight="600" fill="#aab3bd">{TREND.sub[i]}</text>
        </g>
      ))}
      {TREND.series.map((s) => (
        <g key={s.label}>
          <polyline
            points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
            fill="none" stroke={s.color} strokeWidth="2.4"
            strokeDasharray={s.dashed ? "5 4" : undefined}
            strokeLinecap="round" strokeLinejoin="round"
          />
          {s.values.map((v, i) => (
            <circle key={i} cx={x(i)} cy={y(v)} r="3" fill="#fff" stroke={s.color} strokeWidth="2" />
          ))}
        </g>
      ))}
    </svg>
  );
}

const SSA = [0.12, 0.2, 0.16, 0.28, 0.31, 0.4, 0.36, 0.5, 0.6];

function SsaAreaChart() {
  const W = 360, H = 150, padL = 30, padR = 8, padT = 10, padB = 22;
  const n = SSA.length;
  const x = (i: number) => padL + (i / (n - 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v + 1) / 2) * (H - padT - padB);
  const line = SSA.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const months = ["Jan", "Feb", "Mar", "Apr", "May"];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
      <defs>
        <linearGradient id="ssaFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#22c55e" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#22c55e" stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {[1, 0.5, 0, -0.5, -1].map((v) => (
        <g key={v}>
          <line x1={padL} y1={y(v)} x2={W - padR} y2={y(v)} stroke={v === 0 ? "#dfe4e9" : "#f0f2f4"} strokeWidth="1" />
          <text x={padL - 6} y={y(v) + 3} textAnchor="end" fontSize="8" fontWeight="700" fill="#b3bcc5">
            {v > 0 ? `+${v.toFixed(1)}` : v.toFixed(1)}
          </text>
        </g>
      ))}
      <polygon points={`${x(0)},${y(0)} ${line} ${x(n - 1)},${y(0)}`} fill="url(#ssaFill)" />
      <polyline points={line} fill="none" stroke="#22c55e" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
      {SSA.map((v, i) => (
        <circle key={i} cx={x(i)} cy={y(v)} r="2.4" fill="#fff" stroke="#22c55e" strokeWidth="1.6" />
      ))}
      {months.map((m, i) => (
        <text key={m} x={x(i * 2)} y={H - 6} textAnchor="middle" fontSize="8.5" fontWeight="700" fill="#9aa6b1">{m}</text>
      ))}
    </svg>
  );
}

const FUNNEL = [
  { label: "Planned Activities",        value: 17, pct: 100, color: "#3b82f6" },
  { label: "Completed Activities",      value: 12, pct: 71,  color: "#2ea3e6" },
  { label: "Submitted for Verification",value: 10, pct: 59,  color: "#1bbcc4" },
  { label: "Verified by IA",            value: 8,  pct: 47,  color: "#2bb558" },
  { label: "Salesforce Logged",         value: 10, pct: 59,  color: "#1f9d4e" },
];

function Funnel() {
  const widths = [148, 122, 100, 84, 74, 66];
  const cx = 80, bandH = 36, gap = 6;
  return (
    <svg viewBox="0 0 160 210" className="shrink-0" style={{ width: 156, height: 205 }}>
      {FUNNEL.map((b, i) => {
        const yTop = i * (bandH + gap) + 2;
        const tW = widths[i], bW = widths[i + 1];
        const pts = `${cx - tW / 2},${yTop} ${cx + tW / 2},${yTop} ${cx + bW / 2},${yTop + bandH} ${cx - bW / 2},${yTop + bandH}`;
        return <polygon key={b.label} points={pts} fill={b.color} />;
      })}
    </svg>
  );
}

/* ───────────────────────── Page data ───────────────────────── */

const FILTERS = [
  { label: "Financial Year", value: "FY 2024/25" },
  { label: "Term",           value: "Term 2" },
  { label: "Month",          value: "May 2025" },
  { label: "Week",           value: "Week 3 (May 12 – May 18)" },
];

const INSIGHT_STATS = [
  { value: "71%",  label: "Plan Completion",   trend: "12% vs last week", dir: "up" as const,   color: "#16a34a" },
  { value: "65%",  label: "Verified Rate",     trend: "8% vs last week",  dir: "up" as const,   color: "#16a34a" },
  { value: "+0.6", label: "SSA Growth",        trend: "0.3",              dir: "up" as const,   color: "#16a34a" },
  { value: "+9pp", label: "One Test Gain",     trend: "4pp",              dir: "up" as const,   color: "#16a34a" },
  { value: "2",    label: "Schools Improved",  trend: "1",                dir: "up" as const,   color: "#d2901f" },
  { value: "1",    label: "Overdue Activities",trend: "1",                dir: "down" as const, color: "#e0524a" },
];

const TABS = ["Overview", "Plan vs Done", "School Improvement", "SSA", "One Test Literacy", "Activity Types", "Evidence & Salesforce", "Accountability"];

type Kpi = {
  n: number; title: string; icon: LucideIcon; tone: string; bg: string;
  big: string; sub: string;
  spark?: { values: number[]; color: string };
  progress?: number;
};

const KPIS: Kpi[] = [
  { n: 1, title: "Planned Activities",   icon: ClipboardList, tone: "#2f74d9", bg: "#e6f0fc", big: "17", sub: "Target: 24", progress: 71 },
  { n: 2, title: "Completed Activities", icon: CheckCircle2,  tone: "#13a45c", bg: "#e4f6ec", big: "12", sub: "vs 9 last month",     spark: { values: [4, 6, 5, 8, 9, 11, 10, 12], color: "#22c55e" } },
  { n: 3, title: "Verified Activities",  icon: ShieldCheck,   tone: "#7c5cc4", bg: "#efe9fb", big: "8",  sub: "65% of completed",    spark: { values: [2, 3, 4, 4, 6, 6, 7, 8],    color: "#8b5cf6" } },
  { n: 4, title: "Salesforce Logged",    icon: Cloud,         tone: "#d2901f", bg: "#fdf0db", big: "10", sub: "83% of completed",    spark: { values: [3, 5, 4, 6, 7, 8, 9, 10],   color: "#f59e0b" } },
  { n: 5, title: "Schools Improved",     icon: Building2,     tone: "#13a45c", bg: "#e4f6ec", big: "2",  sub: "vs 1 last month",     spark: { values: [0, 1, 1, 1, 2, 1, 2, 2],    color: "#22c55e" } },
  { n: 6, title: "Overdue Activities",   icon: AlertTriangle, tone: "#e0524a", bg: "#fce8e6", big: "1",  sub: "vs 0 last month",     spark: { values: [2, 1, 2, 1, 1, 2, 1, 1],    color: "#ef4444" } },
];

const ACTIVITY_ROWS: { name: string; icon: LucideIcon; color: string; p: number; c: number; v: number; rate: string }[] = [
  { name: "Cluster Trainings",       icon: GraduationCap, color: "#13a45c", p: 4, c: 3, v: 2, rate: "75%" },
  { name: "School Visits (Staff)",   icon: Building2,     color: "#2f74d9", p: 6, c: 4, v: 3, rate: "67%" },
  { name: "School Visits (Partner)", icon: Building2,     color: "#2f74d9", p: 3, c: 2, v: 1, rate: "67%" },
  { name: "In-School Coaching",      icon: BookOpen,      color: "#7c5cc4", p: 2, c: 2, v: 2, rate: "100%" },
  { name: "Mentor Sessions",         icon: Users,         color: "#d2901f", p: 1, c: 1, v: 1, rate: "100%" },
  { name: "Partner Meetings",        icon: Handshake,     color: "#e0524a", p: 1, c: 0, v: 0, rate: "0%" },
  { name: "Community Engagement",    icon: Sparkles,      color: "#5b6b78", p: 0, c: 0, v: 0, rate: "—" },
  { name: "Other Activities",        icon: MoreHorizontal,color: "#5b6b78", p: 0, c: 0, v: 0, rate: "—" },
];

const SF_STATUS: { label: string; icon: LucideIcon; tone: string; value: number; delta: number }[] = [
  { label: "Salesforce IDs Logged", icon: Cloud,       tone: "#2f74d9", value: 10, delta: 2 },
  { label: "Pending Salesforce IDs",icon: Clock,       tone: "#d2901f", value: 2,  delta: -1 },
  { label: "Evidence Submitted",    icon: Upload,      tone: "#7c5cc4", value: 10, delta: 2 },
  { label: "Evidence Verified",     icon: BadgeCheck,  tone: "#13a45c", value: 8,  delta: 2 },
  { label: "Returned for Correction",icon: RotateCcw,  tone: "#e0524a", value: 1,  delta: -1 },
];

const RECENT: { activity: string; type: string; place: string; week: string; status: string; verif: string; verifTone: string; sf: string; impact: string }[] = [
  { activity: "Cluster Training – Child Protection", type: "Cluster Training",   place: "Kitgum Central Cluster Hub", week: "Week 3", status: "Completed", verif: "Verified",  verifTone: "green", sf: "Logged", impact: "SSA +0.5" },
  { activity: "School Visit – Pope John PS",         type: "School Visit (Staff)",place: "Pope John Primary School",  week: "Week 3", status: "Completed", verif: "Submitted", verifTone: "amber", sf: "Logged", impact: "SSA +0.8" },
  { activity: "In-School Coaching Session",          type: "In-School Coaching", place: "St. Peter Primary School",   week: "Week 3", status: "Completed", verif: "Verified",  verifTone: "green", sf: "Logged", impact: "SSA +0.6" },
];

const FOCUS = [
  { icon: AlertTriangle, tone: "#d2901f", bg: "#fdf0db", text: "1 activity is overdue. Please update or reschedule." },
  { icon: Info,          tone: "#2f74d9", bg: "#e6f0fc", text: "2 Salesforce IDs are pending. Log them to stay on track." },
  { icon: CheckCircle2,  tone: "#13a45c", bg: "#e4f6ec", text: "Keep up the good work! Your verified rate improved by 8%." },
];

const QUICK = [
  { label: "Log Activity",    icon: CalendarCheck, tone: "#13a45c", bg: "#e4f6ec" },
  { label: "Smart Route",     icon: Navigation,    tone: "#2f74d9", bg: "#e6f0fc" },
  { label: "Upload Evidence", icon: Upload,        tone: "#7c5cc4", bg: "#efe9fb" },
  { label: "View My Plan",    icon: ClipboardList, tone: "#d2901f", bg: "#fdf0db" },
];

/* ───────────────────────── Page ───────────────────────── */

export function CceoAnalytics({
  donorSnapshot,
}: {
  donorSnapshot?: DonorMetricSnapshot;
} = {}) {
  const [tab, setTab] = useState("Overview");

  return (
    <div className="min-h-screen bg-[#f7f8fa] text-[#1a2330]">
      <PageHeader
        title="CCEO Analytics"
        subtitle="Track your planned activities, verified delivery, school improvement, SSA growth, and literacy outcomes."
        actions={
          <>
            <span className="hidden lg:inline text-[11px] text-muted font-medium">Last synced: May 12, 2025 8:30 AM</span>
            <button className="grid place-items-center h-10 w-10 rounded-xl border border-[var(--color-edify-divider)] bg-white text-[#6b7785] hover:bg-[#f8fafb]">
              <RefreshCw size={15} />
            </button>
            <button className="flex items-center gap-1.5 h-10 px-3 rounded-xl border border-[var(--color-edify-divider)] bg-white text-body font-semibold text-[#3a4753] hover:bg-[#f8fafb]">
              <Upload size={14} className="text-[#6b7785]" /> Export Report
            </button>
            <button className="flex items-center gap-1.5 h-10 px-3 rounded-xl border border-[var(--color-edify-divider)] bg-white text-body font-semibold text-[#3a4753] hover:bg-[#f8fafb]">
              <Download size={14} className="text-[#6b7785]" /> Download PDF
            </button>
          </>
        }
      />
      <div className="px-7 py-6 space-y-5">

          {/* Filters */}
          <Card className="p-4">
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
              {FILTERS.map((f) => (
                <button key={f.label} className="flex flex-col items-start rounded-lg border border-[var(--color-edify-divider)] px-3 py-2 hover:bg-[#f8fafb] text-left">
                  <span className="text-[10px] text-muted font-semibold">{f.label}</span>
                  <span className="flex items-center justify-between gap-2 w-full mt-0.5">
                    <span className="text-body font-semibold text-[#1a2330] truncate">{f.value}</span>
                    <ChevronDown size={14} className="text-[#b3bcc5] shrink-0" />
                  </span>
                </button>
              ))}
            </div>
          </Card>

          {/* Key Insights */}
          <Card className="p-4">
            <div className="flex flex-col xl:flex-row gap-5">
              <div className="xl:w-[380px] shrink-0">
                <div className="flex items-center gap-2 mb-2">
                  <span className="grid place-items-center h-7 w-7 rounded-lg bg-[#eef0ff] text-[#6366f1]">
                    <Sparkles size={15} />
                  </span>
                  <h3 className="text-[13.5px] font-extrabold">Key Insights</h3>
                </div>
                <p className="text-[12px] text-[#5b6675] leading-relaxed">
                  You completed 71% of planned activities this week. 65% of your completed activities have been
                  verified. Schools you visited this month improved SSA by +0.6 on average and One Test literacy
                  increased by +9pp.
                </p>
                <p className="text-caption text-muted font-medium mt-2">Data period: Apr 1 – May 12, 2025</p>
              </div>
              <div className="flex-1 grid grid-cols-3 lg:grid-cols-6 gap-2.5">
                {INSIGHT_STATS.map((s) => (
                  <div key={s.label} className="rounded-lg border border-[var(--color-edify-divider)] bg-[#fbfcfd] px-2.5 py-2.5 text-center">
                    <div className="text-[19px] font-extrabold leading-none" style={{ color: s.color }}>{s.value}</div>
                    <div className="text-[10px] text-[#7c8896] font-medium mt-1.5 leading-tight">{s.label}</div>
                    <div className={"flex items-center justify-center gap-0.5 mt-1.5 text-[10px] font-bold " + (s.dir === "up" ? "text-green-600" : "text-[#e0524a]")}>
                      {s.dir === "up" ? <ArrowUp size={10} /> : <ArrowDown size={10} />}
                      {s.trend}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </Card>

          {/* Donor Reporting Impact — single-officer scope: drop the
              multi-district geography block since a CCEO only ever
              covers one district. */}
          {donorSnapshot && (
            <DonorReportingImpact snapshot={donorSnapshot} hideDistricts />
          )}

          {/* Tabs — phone uses a native select to put all 8 tabs one
              tap away; tablet+ keeps the underline-pill row. `top-14`
              clears the sticky MobileTopBar so the select stays in
              reach as the user scrolls. */}
          <div className="md:hidden sticky top-14 z-20 bg-[var(--color-page)]/95 backdrop-blur-sm py-1.5 -mx-1 px-1">
            <div className="relative">
              <select
                value={tab}
                onChange={(e) => setTab(e.target.value)}
                className="w-full h-11 pl-3.5 pr-9 rounded-xl bg-white border-2 border-[#2f6fe0] text-[13px] font-extrabold text-[#1a2330] appearance-none shadow-sm focus:outline-none focus:ring-2 focus:ring-[#2f6fe0]"
              >
                {TABS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <ChevronDown size={14} className="absolute right-3 top-1/2 -translate-y-1/2 text-[#2f6fe0] pointer-events-none" />
            </div>
          </div>
          <div className="hidden md:flex flex-wrap items-center gap-1 border-b border-[var(--color-edify-divider)] -mt-1">
            {TABS.map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={
                  "px-3 py-2.5 text-body font-semibold border-b-2 -mb-px transition-colors " +
                  (tab === t
                    ? "border-[#2f6fe0] text-[#1a2330]"
                    : "border-transparent text-muted hover:text-[#3a4753]")
                }
              >
                {t}
              </button>
            ))}
          </div>

          {/* KPI row */}
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-4">
            {KPIS.map((k) => (
              <div key={k.n} className="bg-white rounded-xl border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(16,24,40,0.04)] p-3.5 flex flex-col">
                <div className="flex items-center gap-2">
                  <span className="grid place-items-center h-7 w-7 rounded-lg shrink-0" style={{ background: k.bg, color: k.tone }}>
                    <k.icon size={15} />
                  </span>
                  <span className="text-[11.5px] font-bold text-[#3a4753] leading-tight">{k.n}. {k.title}</span>
                </div>
                <div className="flex items-baseline gap-1.5 mt-3">
                  <span className="text-[27px] font-extrabold leading-none">{k.big}</span>
                  <span className="text-caption text-muted font-medium">This Month</span>
                </div>
                {k.progress != null ? (
                  <div className="mt-2.5">
                    <div className="flex items-center justify-between text-[10px] text-muted font-medium mb-1">
                      <span>This Month</span>
                      <span>{k.sub}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full bg-[var(--color-edify-divider)] overflow-hidden">
                        <div className="h-full rounded-full bg-[#2f74d9]" style={{ width: `${k.progress}%` }} />
                      </div>
                      <span className="text-caption font-bold text-[#2f74d9]">{k.progress}%</span>
                    </div>
                    <button className="text-[11px] font-semibold text-[#2f6fe0] hover:underline mt-2.5">View Plan</button>
                  </div>
                ) : (
                  <>
                    <div className="text-caption text-muted font-medium mt-1">{k.sub}</div>
                    <div className="mt-auto pt-2">
                      {k.spark && <Sparkline values={k.spark.values} color={k.spark.color} />}
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>

          {/* Row: trend / funnel */}
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
            {/* Trend */}
            <Card className="xl:col-span-7">
              <div className="flex items-center justify-between gap-2 px-4 pt-3.5">
                <h3 className="text-[13px] font-bold">Plan vs Completed vs Verified Trend</h3>
                <button className="flex items-center gap-1 h-7 px-2 rounded-md border border-[var(--color-edify-divider)] text-[11px] font-semibold text-secondary">
                  By Week <ChevronDown size={12} className="text-muted" />
                </button>
              </div>
              <div className="flex items-center gap-3.5 px-4 mt-2">
                {TREND.series.map((s) => (
                  <span key={s.label} className="flex items-center gap-1.5 text-caption font-semibold text-[#6b7785]">
                    <span
                      className="h-2.5 w-2.5 rounded-full"
                      style={s.dashed ? { border: `2px dashed ${s.color}` } : { background: s.color }}
                    />
                    {s.label}
                  </span>
                ))}
              </div>
              <div className="px-3 pt-1">
                <TrendChart />
              </div>
              <div className="px-4 pb-3.5">
                <button className="text-[11px] font-semibold text-[#2f6fe0] hover:underline">View Detailed Trend</button>
              </div>
            </Card>

            {/* Funnel */}
            <Card title="Verification Funnel" subtitle="This Month" className="xl:col-span-5">
              <div className="flex items-center gap-3 px-4 pt-3">
                <Funnel />
                <div className="flex-1 flex flex-col">
                  {FUNNEL.map((b) => (
                    <div key={b.label} className="h-[42px] flex flex-col justify-center border-b border-[#f4f6f8] last:border-b-0">
                      <div className="flex items-center gap-1.5">
                        <span className="h-2 w-2 rounded-sm shrink-0" style={{ background: b.color }} />
                        <span className="text-[11px] font-medium text-[#3a4753] truncate">{b.label}</span>
                      </div>
                      <div className="text-body font-extrabold pl-3.5">
                        {b.value} <span className="text-caption text-muted font-semibold">({b.pct}%)</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
              <div className="px-4 py-3">
                <button className="text-[11px] font-semibold text-[#2f6fe0] hover:underline">View Verification Backlog</button>
              </div>
            </Card>
          </div>

          {/* Row: improvement summaries */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {/* School improvement */}
            <Card title="School Improvement Status" subtitle="This Month" action="View school list">
              <div className="flex-1 flex items-center gap-4 px-4 py-5">
                <Donut
                  size={132} thickness={22}
                  data={[
                    { label: "Improved",  value: 2, color: "#22c55e" },
                    { label: "No Change", value: 1, color: "#f59e0b" },
                    { label: "Declined",  value: 0.0001, color: "#ef4444" },
                  ]}
                  centerMain="3" centerSub="Schools"
                />
                <div className="flex-1 space-y-2.5">
                  {[
                    { c: "#22c55e", l: "Improved",  v: "2 (67%)" },
                    { c: "#f59e0b", l: "No Change", v: "1 (33%)" },
                    { c: "#ef4444", l: "Declined",  v: "0 (0%)" },
                  ].map((r) => (
                    <div key={r.l} className="flex items-center gap-2 text-[11.5px]">
                      <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: r.c }} />
                      <span className="text-[#5b6675] font-medium flex-1">{r.l}</span>
                      <span className="font-bold text-[#1a2330]">{r.v}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Card>

            {/* SSA score improvement */}
            <Card title="SSA Score Improvement" subtitle="This Month" action="View SSA details">
              <div className="px-4 pt-3">
                <div className="flex items-end justify-between">
                  <span className="text-[11px] text-muted font-semibold">Avg. SSA Gain (May)</span>
                  <div className="text-right">
                    <div className="text-[22px] font-extrabold text-green-600 leading-none">+0.6</div>
                    <div className="flex items-center justify-end gap-0.5 text-[10px] font-bold text-green-600 mt-1">
                      <ArrowUp size={10} /> 0.3 vs last month
                    </div>
                  </div>
                </div>
                <div className="mt-1">
                  <SsaAreaChart />
                </div>
              </div>
              <div className="px-4 pb-3" />
            </Card>

            {/* One test literacy */}
            <Card title="One Test Literacy Progress" subtitle="This Month" action="View literacy outcomes">
              <div className="flex-1 flex items-center gap-4 px-4 py-5">
                <Donut
                  size={132} thickness={22}
                  data={[
                    { label: "Above",  value: 11, color: "#22c55e" },
                    { label: "Near",   value: 5,  color: "#f59e0b" },
                    { label: "Below",  value: 2,  color: "#ef4444" },
                  ]}
                  centerMain="18" centerSub="Learners Assessed"
                />
                <div className="flex-1 space-y-2.5">
                  {[
                    { c: "#22c55e", l: "Above Benchmark", v: "11 (61%)" },
                    { c: "#f59e0b", l: "Near Benchmark",  v: "5 (28%)" },
                    { c: "#ef4444", l: "Below Benchmark", v: "2 (11%)" },
                  ].map((r) => (
                    <div key={r.l} className="flex items-center gap-2 text-[11.5px]">
                      <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ background: r.c }} />
                      <span className="text-[#5b6675] font-medium flex-1">{r.l}</span>
                      <span className="font-bold text-[#1a2330]">{r.v}</span>
                    </div>
                  ))}
                </div>
              </div>
            </Card>

          </div>

          {/* Row: activity completion + evidence status */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
            {/* Activity completion table */}
            <Card title="Activity Completion by Type">
              <div className="px-4 pt-2.5">
                <table className="w-full table-fixed">
                  <colgroup>
                    <col className="w-[40%]" />
                    <col className="w-[15%]" />
                    <col className="w-[15%]" />
                    <col className="w-[15%]" />
                    <col className="w-[15%]" />
                  </colgroup>
                  <thead>
                    <tr className="text-[8.5px] text-muted font-bold uppercase border-b border-[var(--color-edify-divider)] align-bottom">
                      <th className="text-left font-bold py-2">Activity Type</th>
                      <th className="text-right font-bold py-2">Planned</th>
                      <th className="text-right font-bold py-2">Completed</th>
                      <th className="text-right font-bold py-2">Verified</th>
                      <th className="text-right font-bold py-2">Completion Rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ACTIVITY_ROWS.map((r) => (
                      <tr key={r.name} className="border-b border-[#f4f6f8]">
                        <td className="py-2 pr-2">
                          <span className="flex items-center gap-2 min-w-0">
                            <r.icon size={14} style={{ color: r.color }} className="shrink-0" />
                            <span className="text-[11.5px] font-medium text-[#3a4753] truncate">{r.name}</span>
                          </span>
                        </td>
                        <td className="text-right text-[12px] font-semibold tabular-nums">{r.p}</td>
                        <td className="text-right text-[12px] font-semibold tabular-nums">{r.c}</td>
                        <td className="text-right text-[12px] font-semibold tabular-nums">{r.v}</td>
                        <td className="text-right text-[12px] font-semibold tabular-nums text-[#5b6675]">{r.rate}</td>
                      </tr>
                    ))}
                    <tr className="border-t-2 border-[var(--color-edify-divider)]">
                      <td className="py-2.5 text-[12px] font-extrabold">Total</td>
                      <td className="text-right text-[12px] font-extrabold tabular-nums">17</td>
                      <td className="text-right text-[12px] font-extrabold tabular-nums">12</td>
                      <td className="text-right text-[12px] font-extrabold tabular-nums">8</td>
                      <td className="text-right text-[12px] font-extrabold tabular-nums">71%</td>
                    </tr>
                  </tbody>
                </table>
              </div>
              <div className="px-4 py-3">
                <button className="text-[11px] font-semibold text-[#2f6fe0] hover:underline">View All activity types</button>
              </div>
            </Card>

            {/* Salesforce & evidence */}
            <Card title="Salesforce &amp; Evidence Status" subtitle="This Month" action="View evidence quality">
              <div className="px-4 flex-1 flex flex-col">
                {SF_STATUS.map((r) => (
                  <div key={r.label} className="flex-1 flex items-center gap-3 border-b border-[var(--color-edify-divider)] last:border-b-0">
                    <span className="grid place-items-center h-9 w-9 rounded-lg shrink-0" style={{ background: r.tone + "1f", color: r.tone }}>
                      <r.icon size={16} />
                    </span>
                    <span className="text-[12px] font-medium text-[#3a4753] flex-1 leading-tight">{r.label}</span>
                    <span className="text-body-lg font-extrabold tabular-nums">{r.value}</span>
                    <span className={"flex items-center justify-end gap-0.5 w-[36px] text-caption font-bold " + (r.delta > 0 ? "text-green-600" : "text-[#e0524a]")}>
                      {r.delta > 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                      {Math.abs(r.delta)}
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          </div>

          {/* Row: recent / focus / quick */}
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-5">
            {/* Recent activities */}
            <div className="xl:col-span-6">
              <Card title="Recent Activities" action="View All activities">
                <div className="px-4 pt-2.5">
                  <table className="w-full table-fixed">
                    <colgroup>
                      <col className="w-[20%]" />
                      <col className="w-[15%]" />
                      <col className="w-[17%]" />
                      <col className="w-[10%]" />
                      <col className="w-[12%]" />
                      <col className="w-[12%]" />
                      <col className="w-[8%]" />
                      <col className="w-[8%]" />
                    </colgroup>
                    <thead>
                      <tr className="text-[8px] text-muted font-bold uppercase border-b border-[var(--color-edify-divider)] align-bottom">
                        <th className="text-left font-bold py-1.5 pr-1.5">Activity</th>
                        <th className="text-left font-bold py-1.5 pr-1.5">Type</th>
                        <th className="text-left font-bold py-1.5 pr-1.5 leading-[1.25]">School / Location</th>
                        <th className="text-left font-bold py-1.5 pr-1.5">Planned</th>
                        <th className="text-left font-bold py-1.5 pr-1.5">Status</th>
                        <th className="text-left font-bold py-1.5 pr-1.5">Verif.</th>
                        <th className="text-left font-bold py-1.5 pr-1.5">SF</th>
                        <th className="text-left font-bold py-1.5">Impact</th>
                      </tr>
                    </thead>
                    <tbody>
                      {RECENT.map((r) => (
                        <tr key={r.activity} className="border-b border-[#f4f6f8] last:border-b-0">
                          <td className="py-2.5 pr-2 text-[11px] font-semibold text-[#1a2330]">{r.activity}</td>
                          <td className="py-2.5 pr-2 text-caption text-[#6b7785]">{r.type}</td>
                          <td className="py-2.5 pr-2 text-caption text-[#6b7785]">{r.place}</td>
                          <td className="py-2.5 pr-2 text-caption text-[#6b7785]">{r.week}</td>
                          <td className="py-2.5 pr-2">
                            <span className="px-1.5 py-0.5 rounded-md bg-[#e4f6ec] text-[#15803d] text-[9.5px] font-bold">{r.status}</span>
                          </td>
                          <td className="py-2.5 pr-2">
                            <span className={"px-1.5 py-0.5 rounded-md text-[9.5px] font-bold " + (r.verifTone === "green" ? "bg-[#e4f6ec] text-[#15803d]" : "bg-[#fdf0db] text-[#b06a12]")}>
                              {r.verif}
                            </span>
                          </td>
                          <td className="py-2.5 pr-2">
                            <span className="px-1.5 py-0.5 rounded-md bg-[#e6f0fc] text-[#2563c9] text-[9.5px] font-bold">{r.sf}</span>
                          </td>
                          <td className="py-2.5 text-caption font-bold text-green-600">{r.impact}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="px-4 py-3" />
              </Card>
            </div>

            {/* What to focus on */}
            <div className="xl:col-span-3">
              <Card title="What to Focus On" className="h-full">
                <div className="px-4 flex-1 flex flex-col">
                  {FOCUS.map((f) => (
                    <div key={f.text} className="flex-1 flex items-center gap-3 border-b border-[var(--color-edify-divider)] last:border-b-0">
                      <span className="grid place-items-center h-8 w-8 rounded-lg shrink-0" style={{ background: f.bg, color: f.tone }}>
                        <f.icon size={15} />
                      </span>
                      <p className="text-[12px] text-[#5b6675] leading-snug">{f.text}</p>
                    </div>
                  ))}
                </div>
              </Card>
            </div>

            {/* Quick actions */}
            <div className="xl:col-span-3">
              <Card title="Quick Actions" className="h-full">
                <div className="flex-1 grid grid-cols-2 grid-rows-2 gap-2.5 px-4 py-3">
                  {QUICK.map((q) => (
                    <button key={q.label} className="flex flex-col items-center justify-center gap-2 rounded-xl border border-[var(--color-edify-divider)] hover:bg-[#f8fafb] transition-colors">
                      <span className="grid place-items-center h-9 w-9 rounded-xl" style={{ background: q.bg, color: q.tone }}>
                        <q.icon size={17} />
                      </span>
                      <span className="text-caption font-semibold text-secondary text-center leading-tight">{q.label}</span>
                    </button>
                  ))}
                </div>
              </Card>
            </div>
          </div>
        </div>
    </div>
  );
}

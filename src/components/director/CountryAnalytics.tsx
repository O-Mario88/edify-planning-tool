"use client";

// Country Performance & Impact Analytics — national executive cockpit.
// Renders as page content inside the shared (shell) layout — the Country
// Director sidebar + chrome come from the route-group layout, so this
// surface never mounts its own navigation rail.

import { useState } from "react";
import {
  ChevronDown, Star, Users, Zap, Building2, GraduationCap, ShieldCheck,
  Wallet, ClipboardCheck, FileText, FileSpreadsheet, Download,
  MoreHorizontal, Filter, Sparkles, ArrowUp, ArrowDown, TriangleAlert,
  BookOpen, Lock, RefreshCw, MapPin, TrendingUp, type LucideIcon,
} from "lucide-react";
import { Donut } from "@/components/analytics/primitives";
import { PageHeader } from "@/components/ui/PageHeader";
import { DonorReportingImpact } from "@/components/donor-reporting/DonorReportingImpact";
import type { DonorMetricSnapshot } from "@/lib/donor-metrics-types";

/* ───────────────────────── Primitives ───────────────────────── */

function Card({
  title, subtitle, action, children, className = "", pad = false,
}: {
  title?: string; subtitle?: string; action?: string;
  children: React.ReactNode; className?: string; pad?: boolean;
}) {
  return (
    <section className={"bg-white rounded-xl border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(16,24,40,0.04)] flex flex-col " + className}>
      {(title || action) && (
        <div className="flex items-start justify-between gap-2 px-3.5 pt-3">
          <div className="min-w-0">
            {title && <h3 className="text-body font-bold text-[#1a2330] leading-tight">{title}</h3>}
            {subtitle && <p className="text-[9.5px] text-muted font-semibold mt-0.5">{subtitle}</p>}
          </div>
          {action && <button className="text-[10px] font-semibold text-[#2f6fe0] hover:underline shrink-0">{action}</button>}
        </div>
      )}
      <div className={pad ? "p-3.5 flex-1 flex flex-col" : "flex-1 flex flex-col"}>{children}</div>
    </section>
  );
}

function Ring({ pct, color, size = 56, label }: { pct: number; color: string; size?: number; label?: string }) {
  const sw = size * 0.15, r = (size - sw) / 2, c = 2 * Math.PI * r;
  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#eef1f4" strokeWidth={sw} />
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={sw}
          strokeLinecap="round" strokeDasharray={`${(pct / 100) * c} ${c}`}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-[13px] font-extrabold text-[#1a2330] leading-none">{pct}%</span>
        {label && <span className="text-[7px] text-muted font-semibold mt-0.5">{label}</span>}
      </div>
    </div>
  );
}

function Sparkline({ values, color, height = 38 }: { values: number[]; color: string; height?: number }) {
  const W = 200, H = height, pad = 3;
  const max = Math.max(...values), min = Math.min(...values), span = max - min || 1;
  const x = (i: number) => pad + (i / (values.length - 1)) * (W - 2 * pad);
  const y = (v: number) => pad + (1 - (v - min) / span) * (H - 2 * pad);
  const line = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const gid = "g" + color.replace("#", "") + values.length;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="w-full" style={{ height }}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.2" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`${pad},${H} ${line} ${W - pad},${H}`} fill={`url(#${gid})`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function MiniSpark({ values, color }: { values: number[]; color: string }) {
  const W = 56, H = 20, pad = 2;
  const max = Math.max(...values), min = Math.min(...values), span = max - min || 1;
  const x = (i: number) => pad + (i / (values.length - 1)) * (W - 2 * pad);
  const y = (v: number) => pad + (1 - (v - min) / span) * (H - 2 * pad);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-[56px] h-[20px]">
      <polyline
        points={values.map((v, i) => `${x(i)},${y(v)}`).join(" ")}
        fill="none" stroke={color} strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
      />
    </svg>
  );
}

function MiniArea({ values, color }: { values: number[]; color: string }) {
  const W = 200, H = 70, padL = 4, padR = 4, padT = 6, padB = 16;
  const max = Math.max(...values) * 1.15, min = Math.min(0, ...values);
  const x = (i: number) => padL + (i / (values.length - 1)) * (W - padL - padR);
  const y = (v: number) => padT + (1 - (v - min) / (max - min)) * (H - padT - padB);
  const line = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const months = ["Jan", "Feb", "Mar", "Apr", "May"];
  const gid = "ar" + color.replace("#", "");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      <polygon points={`${x(0)},${H - padB} ${line} ${x(values.length - 1)},${H - padB}`} fill={`url(#${gid})`} />
      <polyline points={line} fill="none" stroke={color} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      {months.map((m, i) => (
        <text key={m} x={x(i)} y={H - 4} textAnchor="middle" fontSize="7.5" fontWeight="700" fill="#aab3bd">{m}</text>
      ))}
    </svg>
  );
}

const FUNNEL = [
  { label: "Planned Activities",   value: "1,240", pct: 100, color: "#3b82f6" },
  { label: "Completed Activities", value: "1,042", pct: 84,  color: "#2f9fe6" },
  { label: "Salesforce Submitted", value: "896",   pct: 72,  color: "#22b7c4" },
  { label: "IA Verified",          value: "856",   pct: 69,  color: "#2bb572" },
  { label: "Accounted For",        value: "702",   pct: 57,  color: "#49b34e" },
  { label: "School Impacted",      value: "645",   pct: 52,  color: "#2f9d3f" },
];

function Funnel() {
  const w = [124, 105, 90, 78, 68, 60, 54];
  const cx = 66, bandH = 26, gap = 5;
  return (
    <svg viewBox="0 0 132 190" className="shrink-0" style={{ width: 116, height: 168 }}>
      {FUNNEL.map((b, i) => {
        const yTop = i * (bandH + gap) + 2;
        const t = w[i], bw = w[i + 1];
        return (
          <polygon
            key={b.label}
            points={`${cx - t / 2},${yTop} ${cx + t / 2},${yTop} ${cx + bw / 2},${yTop + bandH} ${cx - bw / 2},${yTop + bandH}`}
            fill={b.color}
          />
        );
      })}
    </svg>
  );
}

const MAP_PATCHES: { points: string; color: string }[] = [
  { points: "26,60 78,46 96,82 44,96", color: "#e0594a" },
  { points: "78,46 134,40 150,78 96,82", color: "#e8943a" },
  { points: "134,40 184,58 188,96 150,78", color: "#9ccc3a" },
  { points: "44,96 96,82 110,128 56,138", color: "#e8c33a" },
  { points: "96,82 150,78 158,124 110,128", color: "#5cb85c" },
  { points: "150,78 188,96 184,134 158,124", color: "#1f9d4e" },
  { points: "56,138 110,128 96,164 60,158", color: "#5cb85c" },
  { points: "110,128 158,124 150,160 96,164", color: "#e8943a" },
];

function UgandaMap() {
  return (
    <svg viewBox="0 0 214 200" className="w-full h-auto">
      {MAP_PATCHES.map((p, i) => (
        <polygon key={i} points={p.points} fill={p.color} stroke="#ffffff" strokeWidth="1.6" strokeLinejoin="round" />
      ))}
    </svg>
  );
}

/* ───────────────────────── Page data ───────────────────────── */

const FILTERS = ["FY 2024/25", "Q4 (Apr – Jun)", "May 2025", "Week 3 (May 12 – May 18)"];

const INSIGHT_STATS = [
  { value: "84%",       label: "Activities Completed", trend: "11% vs last period", dir: "up" as const,   color: "#ffffff" },
  { value: "69%",       label: "IA Verified Rate",     trend: "7% vs last period",  dir: "up" as const,   color: "#ffffff" },
  { value: "+0.6",      label: "SSA Avg Gain",         trend: "0.3 vs last period", dir: "up" as const,   color: "#ffffff" },
  { value: "+8pp",      label: "One Test Gain",        trend: "5pp vs last period", dir: "up" as const,   color: "#ffffff" },
  { value: "UGX 22.4M", label: "Outstanding",          trend: "9% vs last period",  dir: "up" as const,   color: "#f5b945" },
  { value: "14",        label: "Staff Need Support",   trend: "2 vs last period",   dir: "down" as const, color: "#f0867a" },
];

const KPI_DECISIONS = [
  { icon: ClipboardCheck, tone: "#7c5cc4", bg: "#efe9fb", title: "Verification Backlog",     text: "186 completed activities are waiting for IA verification.",      cta: "Open IA Backlog" },
  { icon: TriangleAlert,  tone: "#d2901f", bg: "#fdf0db", title: "Accountability Risk",       text: "UGX 22.4M is outstanding in field accountability.",             cta: "Review Open Funds" },
  { icon: Users,          tone: "#e0524a", bg: "#fce8e6", title: "Program Lead Team Behind",  text: "Team North is at 58% verified progress against 72% expected.",  cta: "Open Team Support Review" },
  { icon: BookOpen,       tone: "#2f74d9", bg: "#e6f0fc", title: "Literacy Concern",          text: "47 schools declined in One Test results despite support.",      cta: "Review Literacy Decline Schools" },
  { icon: Lock,           tone: "#d2901f", bg: "#fdf0db", title: "Funding Gate",              text: "Week 3 release blocked for 6 staff due to pending NetSuite IDs.", cta: "Review Accountability Gate" },
];

const PL_ROWS = [
  { name: "Team North",   p: 245, c: 198, v: 143, rate: "58%", trend: [6, 5, 5, 4, 3, 3], tone: "#e0524a" },
  { name: "Team Central", p: 310, c: 268, v: 199, rate: "64%", trend: [4, 5, 5, 6, 6, 7], tone: "#d2901f" },
  { name: "Team East",    p: 280, c: 246, v: 184, rate: "66%", trend: [4, 4, 5, 5, 6, 6], tone: "#16a34a" },
  { name: "Team West",    p: 230, c: 186, v: 142, rate: "62%", trend: [5, 5, 4, 5, 6, 6], tone: "#d2901f" },
  { name: "Team South",   p: 175, c: 144, v: 108, rate: "62%", trend: [4, 5, 5, 5, 5, 6], tone: "#16a34a" },
];

const ACTIVITY_ROWS = [
  { name: "Cluster Trainings",       p: 210, c: 182, v: 156, rate: 87 },
  { name: "School Visits (Staff)",   p: 316, c: 256, v: 199, rate: 81 },
  { name: "School Visits (Partner)", p: 134, c: 108, v: 82,  rate: 81 },
  { name: "In-School Coaching",      p: 148, c: 112, v: 86,  rate: 76 },
  { name: "Mentor Sessions",         p: 92,  c: 76,  v: 62,  rate: 83 },
  { name: "Partner Meetings",        p: 96,  c: 72,  v: 60,  rate: 75 },
  { name: "Community Engagement",    p: 64,  c: 48,  v: 34,  rate: 75 },
  { name: "Other Activities",        p: 180, c: 128, v: 97,  rate: 71 },
];

const IA_ROWS = [
  { label: "Submitted for Verification", value: "896" },
  { label: "Verified",                   value: "856", note: "69%", tone: "#16a34a" },
  { label: "Returned",                   value: "26",  note: "3%",  tone: "#e0524a" },
  { label: "Pending Review",             value: "166", note: "15%", tone: "#d2901f" },
  { label: "Overdue",                    value: "48",  note: "4%",  tone: "#e0524a" },
];

const FIN_ROWS = [
  { label: "Budget (YTD)",     value: "UGX 1.20B" },
  { label: "Disbursed",        value: "UGX 92.8M" },
  { label: "Accounted",        value: "UGX 70.4M", note: "76%", tone: "#16a34a" },
  { label: "Outstanding",      value: "UGX 22.4M", note: "24%", tone: "#d2901f" },
  { label: "Variance vs Plan", value: "-8%",       tone: "#e0524a" },
];

const TOP_SCHOOLS = [
  { school: "Pope John PS",  district: "Kitgum", issue: "Declining SSA",     date: "May 2, 2025",  action: "Targeted Coaching" },
  { school: "St. Peter PS",  district: "Lamwo",  issue: "No Progress",       date: "Apr 20, 2025", action: "Follow-Up Visit" },
  { school: "Oyeta PS",      district: "Agago",  issue: "Low Literacy Gain", date: "May 3, 2025",  action: "Instructional Support" },
  { school: "Kanyawara PS",  district: "Gulu",   issue: "No Recent Activity",date: "Apr 30, 2025", action: "Schedule Visit" },
  { school: "Adilang PS",    district: "Gulu",   issue: "Low Verification",  date: "Apr 28, 2025", action: "Evidence Support" },
];

const RISK_SIGNALS = [
  { area: "CCEOs Need Support",    week: "14",        trend: [3, 4, 4, 5, 6, 6], tone: "#e0524a", change: "2",  up: true },
  { area: "Overdue Activities",    week: "1",         trend: [2, 1, 2, 1, 1, 1], tone: "#e0524a", change: "1",  up: true },
  { area: "Salesforce IDs Pending",week: "118",       trend: [4, 5, 6, 7, 8, 9], tone: "#e0524a", change: "18", up: true },
  { area: "Verification Overdue",  week: "48",        trend: [3, 4, 4, 5, 5, 6], tone: "#e0524a", change: "3",  up: true },
  { area: "Accountability Overdue",week: "UGX 22.4M", trend: [4, 4, 5, 5, 6, 6], tone: "#16a34a", change: "9%", up: true },
];

const QUICK_ACTIONS = [
  { label: "Team Support Review", icon: Users,        tone: "#2f74d9", bg: "#e6f0fc" },
  { label: "Verification Backlog",icon: ClipboardCheck,tone: "#d2901f", bg: "#fdf0db" },
  { label: "Accountability Review",icon: ShieldCheck, tone: "#e0524a", bg: "#fce8e6" },
  { label: "District Drilldown",  icon: MapPin,       tone: "#13a45c", bg: "#e4f6ec" },
  { label: "School Drilldown",    icon: Building2,    tone: "#7c5cc4", bg: "#efe9fb" },
  { label: "Generate RVP Summary",icon: FileText,     tone: "#2f74d9", bg: "#e6f0fc" },
];

/* ───────────────────────── Page ───────────────────────── */

export function CountryAnalytics({
  donorSnapshot,
}: {
  donorSnapshot?: DonorMetricSnapshot;
} = {}) {
  const [tab, setTab] = useState("");
  void tab; void setTab;

  return (
    <div className="min-h-screen bg-[#f4f6f8] text-[#1a2330]">
      <PageHeader
        title="Country Performance & Impact Analytics"
        Icon={Star}
        iconClassName="text-[#e8b53a]"
        subtitle="A national view of field delivery, school improvement, literacy progress, fund accountability, and verified impact."
        actions={
          <>
            <button className="flex items-center gap-1.5 h-10 px-3 rounded-xl bg-[#1f2733] text-white text-body font-semibold hover:bg-[#28323f]">
              <FileText size={14} /> Generate Country Report
            </button>
            <button disabled title="Excel export is coming soon" className="flex items-center gap-1.5 h-10 px-3 rounded-xl border border-[var(--color-edify-divider)] bg-white text-body font-semibold text-[#3a4753] opacity-50 cursor-not-allowed">
              <FileSpreadsheet size={14} className="text-[#6b7785]" /> Export Excel
            </button>
            <button disabled title="PDF download is coming soon" className="flex items-center gap-1.5 h-10 px-3 rounded-xl border border-[var(--color-edify-divider)] bg-white text-body font-semibold text-[#3a4753] opacity-50 cursor-not-allowed">
              <Download size={14} className="text-[#6b7785]" /> Download PDF
            </button>
            <button className="grid place-items-center h-10 w-10 rounded-xl border border-[var(--color-edify-divider)] bg-white text-[#6b7785] hover:bg-[#f8fafb]">
              <MoreHorizontal size={16} />
            </button>
          </>
        }
      />
      <div className="px-6 py-5 space-y-4">

          {/* Filters */}
          <div className="flex items-center gap-2.5 flex-wrap">
            {FILTERS.map((f) => (
              <button key={f} className="flex items-center gap-2 h-9 px-3 rounded-lg border border-[var(--color-edify-divider)] bg-white text-[11.5px] font-semibold text-[#3a4753] hover:bg-[#f8fafb]">
                {f}
                <ChevronDown size={13} className="text-muted" />
              </button>
            ))}
            <span className="text-[11px] text-muted font-semibold ml-1">Comparison</span>
            <button className="flex items-center gap-2 h-9 px-3 rounded-lg border border-[var(--color-edify-divider)] bg-white text-[11.5px] font-semibold text-[#3a4753] hover:bg-[#f8fafb]">
              vs Apr 14 – May 11
              <ChevronDown size={13} className="text-muted" />
            </button>
            <button disabled title="Advanced filtering is coming soon" className="flex items-center gap-1.5 h-9 px-3.5 rounded-lg border border-[var(--color-edify-divider)] bg-white text-[11.5px] font-semibold text-[#3a4753] opacity-50 cursor-not-allowed ml-auto">
              <Filter size={13} className="text-[#6b7785]" /> Filters
            </button>
          </div>

          {/* National Insight */}
          <section className="rounded-2xl bg-[#202b3a] text-white p-5">
            <div className="flex flex-col xl:flex-row gap-5">
              <div className="xl:w-[330px] shrink-0">
                <div className="flex items-center gap-2 mb-2">
                  <span className="grid place-items-center h-7 w-7 rounded-lg bg-white/10">
                    <Sparkles size={15} className="text-[#9db4ff]" />
                  </span>
                  <h2 className="text-body-lg font-extrabold">National Insight</h2>
                </div>
                <p className="text-[12px] font-semibold leading-relaxed">
                  Uganda is on track for field execution this month, but verification and accountability are slowing down impact record.
                </p>
                <p className="text-[11px] text-white/55 leading-relaxed mt-1.5">
                  Teams completed 84% of planned activities, but only 69% have been IA verified. Schools receiving
                  verified coaching improved SSA by +0.6 on average, while One Test literacy scores improved by ~8
                  percentage points in assessed schools. UGX 22.4M remains outstanding in field accountability.
                </p>
                <div className="flex items-center gap-3 mt-2.5">
                  <span className="text-[9.5px] text-white/45 font-semibold">Data period: Apr 1 – May 18, 2025</span>
                  <button className="text-[9.5px] font-semibold text-[#9db4ff] hover:underline">View Methodology</button>
                </div>
              </div>

              <div className="flex-1 grid grid-cols-3 lg:grid-cols-6 gap-px bg-white/10 rounded-xl overflow-hidden">
                {INSIGHT_STATS.map((s) => (
                  <div key={s.label} className="bg-[#202b3a] px-2.5 py-3 text-center">
                    <div className="text-[18px] font-extrabold leading-none" style={{ color: s.color }}>{s.value}</div>
                    <div className="text-[9px] text-white/55 font-semibold mt-1.5 leading-tight">{s.label}</div>
                    <div className={"flex items-center justify-center gap-0.5 mt-1.5 text-[9px] font-bold " + (s.dir === "up" ? "text-[#5fc98a]" : "text-[#f0867a]")}>
                      {s.dir === "up" ? <ArrowUp size={9} /> : <ArrowUp size={9} />}
                      {s.trend}
                    </div>
                  </div>
                ))}
              </div>

              <div className="xl:w-[210px] shrink-0 flex flex-col gap-2">
                <button className="h-9 rounded-lg bg-[#2f6fe0] text-white text-[11.5px] font-bold hover:brightness-110">Review National Risks</button>
                <button className="h-9 rounded-lg border border-white/20 text-white text-[11.5px] font-semibold hover:bg-white/5">Open Verification Backlog</button>
                <button className="h-9 rounded-lg border border-white/20 text-white text-[11.5px] font-semibold hover:bg-white/5">Review Accountability</button>
              </div>
            </div>
          </section>

          {/* Donor Reporting Impact — national rollup, deduplicated and
              evidence-gated. Sits between the National Insight narrative
              and the operational KPI grid so donor numbers lead. */}
          {donorSnapshot && <DonorReportingImpact snapshot={donorSnapshot} />}

          {/* Country KPI Summary */}
          <div>
            <h2 className="text-body-lg font-extrabold tracking-tight mb-2.5">Country KPI Summary</h2>
            <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3.5">
              {/* 1 Field Execution */}
              <Card pad>
                <KpiHead n={1} title="Field Execution" icon={Zap} tone="#2f74d9" bg="#e6f0fc" />
                <div className="flex items-start justify-between gap-2 mt-2.5">
                  <div className="space-y-1.5">
                    <Stat big="1,042" label="Completed" />
                    <Stat med="1,240" label="Planned" />
                  </div>
                  <Ring pct={84} color="#2f74d9" />
                </div>
                <div className="mt-auto pt-2.5"><Sparkline values={[18, 26, 22, 31, 35, 33, 40]} color="#22c55e" /></div>
                <ViewDetails />
              </Card>
              {/* 2 Verified Delivery */}
              <Card pad>
                <KpiHead n={2} title="Verified Delivery" icon={ShieldCheck} tone="#13a45c" bg="#e4f6ec" />
                <div className="flex items-start justify-between gap-2 mt-2.5">
                  <div className="space-y-1.5">
                    <Stat big="856" label="IA Verified" />
                    <Stat med="69%" label="of Planned" />
                  </div>
                  <Ring pct={69} color="#13a45c" />
                </div>
                <div className="mt-auto pt-2.5"><Sparkline values={[12, 16, 15, 20, 23, 24, 28]} color="#22c55e" /></div>
                <ViewDetails />
              </Card>
              {/* 3 School Improvement */}
              <Card pad>
                <KpiHead n={3} title="School Improvement" icon={TrendingUp} tone="#13a45c" bg="#e4f6ec" />
                <div className="flex items-start justify-between gap-2 mt-2.5">
                  <Stat big="+0.6" label="Avg SSA Gain" />
                  <div className="text-right space-y-1">
                    <div><span className="text-[15px] font-extrabold">412</span> <span className="text-[9.5px] text-muted font-semibold">Improved</span></div>
                    <div><span className="text-[15px] font-extrabold">73</span> <span className="text-[9.5px] text-muted font-semibold">Declined</span></div>
                  </div>
                </div>
                <div className="mt-auto pt-2.5"><Sparkline values={[3, 4, 4, 5, 6, 6, 7]} color="#22c55e" /></div>
                <ViewDetails />
              </Card>
              {/* 4 Literacy Outcome */}
              <Card pad>
                <KpiHead n={4} title="Literacy Outcome" icon={GraduationCap} tone="#7c5cc4" bg="#efe9fb" />
                <div className="flex items-start justify-between gap-2 mt-2.5">
                  <Stat big="+8pp" label="One Test Gain" />
                  <div className="text-right space-y-1">
                    <div><span className="text-body-lg font-extrabold">21,480</span><span className="block text-[9.5px] text-muted font-semibold">Learners Assessed</span></div>
                    <div><span className="text-[13px] font-extrabold">64%</span> <span className="text-[9.5px] text-muted font-semibold">At Benchmark</span></div>
                  </div>
                </div>
                <div className="mt-auto pt-2.5"><Sparkline values={[2, 3, 3, 4, 5, 6, 8]} color="#22c55e" /></div>
                <ViewDetails />
              </Card>
              {/* 5 Finance & Accountability */}
              <Card pad>
                <KpiHead n={5} title="Finance & Accountability" icon={Wallet} tone="#d2901f" bg="#fdf0db" />
                <div className="mt-3 space-y-2.5 flex-1">
                  <Stat big="UGX 92.8M" label="Disbursed" />
                  <div className="border-t border-[var(--color-edify-divider)] pt-2">
                    <span className="text-body-lg font-extrabold">UGX 70.4M</span>
                    <span className="block text-[9.5px] text-muted font-semibold">Accounted (76%)</span>
                  </div>
                  <div className="border-t border-[var(--color-edify-divider)] pt-2">
                    <span className="text-body-lg font-extrabold text-[#d2901f]">UGX 22.4M</span>
                    <span className="block text-[9.5px] text-muted font-semibold">Outstanding (24%)</span>
                  </div>
                </div>
                <ViewDetails />
              </Card>
              {/* 6 Staff / Team Risk */}
              <Card pad>
                <KpiHead n={6} title="Staff / Team Risk" icon={Users} tone="#e0524a" bg="#fce8e6" />
                <div className="mt-3 space-y-2.5 flex-1">
                  <Stat big="14" label="Staff Need Support" />
                  <div className="border-t border-[var(--color-edify-divider)] pt-2">
                    <span className="text-body-lg font-extrabold">3</span>
                    <span className="block text-[9.5px] text-muted font-semibold">PL Teams Behind</span>
                  </div>
                  <div className="border-t border-[var(--color-edify-divider)] pt-2">
                    <span className="text-body-lg font-extrabold">118</span>
                    <span className="block text-[9.5px] text-muted font-semibold">Salesforce IDs Pending</span>
                  </div>
                </div>
                <ViewDetails />
              </Card>
            </div>
          </div>

          {/* Decisions Required This Week */}
          <div>
            <h2 className="flex items-center gap-2 text-body-lg font-extrabold tracking-tight mb-2.5">
              Decisions Required This Week
              <span className="h-[18px] min-w-[18px] px-1 grid place-items-center rounded-full bg-[#e0524a] text-white text-[10px] font-bold">5</span>
            </h2>
            <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-5 gap-3.5">
              {KPI_DECISIONS.map((d) => (
                <div key={d.title} className="bg-white rounded-xl border border-[var(--color-edify-divider)] shadow-[0_1px_2px_rgba(16,24,40,0.04)] p-3.5 flex flex-col">
                  <div className="flex items-start gap-2.5">
                    <span className="grid place-items-center h-8 w-8 rounded-lg shrink-0" style={{ background: d.bg, color: d.tone }}>
                      <d.icon size={16} />
                    </span>
                    <h3 className="text-[12px] font-bold leading-snug mt-0.5">{d.title}</h3>
                  </div>
                  <p className="text-[11px] text-[#6b7785] leading-snug mt-2 flex-1">{d.text}</p>
                  <button className="text-caption font-bold text-[#2f6fe0] hover:underline mt-2.5 text-left">{d.cta} →</button>
                </div>
              ))}
            </div>
          </div>

          {/* Row 7-10 */}
          <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
            {/* 7 Program Lead Team Performance */}
            <Card title="7. Program Lead Team Performance" action="View All" className="xl:col-span-3">
              <div className="px-3.5 pt-2 pb-3 flex-1">
                <table className="w-full table-fixed">
                  <colgroup>
                    <col className="w-[27%]" /><col className="w-[14%]" /><col className="w-[15%]" /><col className="w-[13%]" /><col className="w-[15%]" /><col className="w-[16%]" />
                  </colgroup>
                  <thead>
                    <tr className="text-[7.5px] text-muted font-bold uppercase border-b border-[var(--color-edify-divider)] align-bottom">
                      <th className="text-left font-bold py-1.5">Program Lead</th>
                      <th className="text-right font-bold py-1.5">Planned</th>
                      <th className="text-right font-bold py-1.5">Completed</th>
                      <th className="text-right font-bold py-1.5">Verified</th>
                      <th className="text-right font-bold py-1.5">Ver. Rate</th>
                      <th className="text-right font-bold py-1.5">Trend</th>
                    </tr>
                  </thead>
                  <tbody>
                    {PL_ROWS.map((r) => (
                      <tr key={r.name} className="border-b border-[#f4f6f8]">
                        <td className="py-1.5 text-caption font-semibold text-[#1a2330] truncate">{r.name}</td>
                        <td className="py-1.5 text-right text-caption tabular-nums">{r.p}</td>
                        <td className="py-1.5 text-right text-caption tabular-nums">{r.c}</td>
                        <td className="py-1.5 text-right text-caption tabular-nums">{r.v}</td>
                        <td className="py-1.5 text-right text-caption font-bold tabular-nums" style={{ color: r.tone }}>{r.rate}</td>
                        <td className="py-1.5 text-right"><span className="inline-block"><MiniSpark values={r.trend} color={r.tone} /></span></td>
                      </tr>
                    ))}
                    <tr className="border-t-2 border-[var(--color-edify-divider)]">
                      <td className="py-2 text-caption font-extrabold">Total</td>
                      <td className="py-2 text-right text-caption font-extrabold tabular-nums">1,240</td>
                      <td className="py-2 text-right text-caption font-extrabold tabular-nums">1,042</td>
                      <td className="py-2 text-right text-caption font-extrabold tabular-nums">776</td>
                      <td className="py-2 text-right text-caption font-extrabold tabular-nums">63%</td>
                      <td />
                    </tr>
                  </tbody>
                </table>
              </div>
            </Card>

            {/* 8 CCEO Performance Overview */}
            <Card title="8. CCEO Performance Overview" action="View All" className="xl:col-span-3">
              <div className="px-3.5 py-3 flex-1 flex flex-col">
                <div className="flex items-center gap-3 flex-1">
                  <Donut
                    size={108} thickness={18}
                    data={[
                      { label: "High",   value: 24, color: "#22c55e" },
                      { label: "Medium", value: 46, color: "#f59e0b" },
                      { label: "Low",    value: 22, color: "#ef4444" },
                    ]}
                    centerMain="62%" centerSub="Avg Verified Rate"
                  />
                  <div className="flex-1 space-y-2">
                    {[
                      { c: "#22c55e", l: "High (≥70%)",     v: "24 (26%)" },
                      { c: "#f59e0b", l: "Medium (40–69%)", v: "46 (50%)" },
                      { c: "#ef4444", l: "Low (<40%)",      v: "22 (24%)" },
                    ].map((r) => (
                      <div key={r.l} className="flex items-center gap-1.5 text-caption">
                        <span className="h-2 w-2 rounded-full shrink-0" style={{ background: r.c }} />
                        <span className="text-[#5b6675] font-medium flex-1">{r.l}</span>
                        <span className="font-bold">{r.v}</span>
                      </div>
                    ))}
                  </div>
                </div>
                <div className="text-[10px] text-muted font-semibold border-t border-[var(--color-edify-divider)] pt-2 mt-1">Total CCEOs: 92</div>
              </div>
            </Card>

            {/* 9 Field Execution Funnel */}
            <Card title="9. Field Execution Funnel" action="View Funnel" className="xl:col-span-3">
              <div className="px-3.5 py-3 flex-1 flex items-center gap-2">
                <Funnel />
                <div className="flex-1 flex flex-col">
                  {FUNNEL.map((b) => (
                    <div key={b.label} className="py-1 border-b border-[#f4f6f8] last:border-b-0">
                      <div className="flex items-center gap-1.5">
                        <span className="h-1.5 w-1.5 rounded-sm shrink-0" style={{ background: b.color }} />
                        <span className="text-[9.5px] text-[#5b6675] font-medium leading-tight">{b.label}</span>
                      </div>
                      <div className="text-[11px] font-extrabold pl-3 leading-tight">
                        {b.value} <span className="text-[9px] text-muted font-semibold">({b.pct}%)</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </Card>

            {/* 10 Activity Completion by Type */}
            <Card title="10. Activity Completion by Type" subtitle="This Month" action="View All" className="xl:col-span-3">
              <div className="px-3.5 pt-2 pb-3 flex-1">
                <table className="w-full table-fixed">
                  <colgroup>
                    <col className="w-[38%]" /><col className="w-[14%]" /><col className="w-[15%]" /><col className="w-[13%]" /><col className="w-[20%]" />
                  </colgroup>
                  <thead>
                    <tr className="text-[7.5px] text-muted font-bold uppercase border-b border-[var(--color-edify-divider)] align-bottom">
                      <th className="text-left font-bold py-1.5">Activity Type</th>
                      <th className="text-right font-bold py-1.5">Plan</th>
                      <th className="text-right font-bold py-1.5">Done</th>
                      <th className="text-right font-bold py-1.5">Ver.</th>
                      <th className="text-right font-bold py-1.5">Completion</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ACTIVITY_ROWS.map((r) => (
                      <tr key={r.name} className="border-b border-[#f4f6f8]">
                        <td className="py-[5px] text-[10px] font-medium text-[#3a4753] truncate">{r.name}</td>
                        <td className="py-[5px] text-right text-[10px] tabular-nums">{r.p}</td>
                        <td className="py-[5px] text-right text-[10px] tabular-nums">{r.c}</td>
                        <td className="py-[5px] text-right text-[10px] tabular-nums">{r.v}</td>
                        <td className="py-[5px]">
                          <div className="flex items-center gap-1 justify-end">
                            <div className="w-[34px] h-1.5 rounded-full bg-[var(--color-edify-divider)] overflow-hidden">
                              <div className="h-full rounded-full bg-[#16a34a]" style={{ width: `${r.rate}%` }} />
                            </div>
                            <span className="text-[9.5px] font-bold tabular-nums w-[24px] text-right">{r.rate}%</span>
                          </div>
                        </td>
                      </tr>
                    ))}
                    <tr className="border-t-2 border-[var(--color-edify-divider)]">
                      <td className="py-2 text-[10px] font-extrabold">Total</td>
                      <td className="py-2 text-right text-[10px] font-extrabold tabular-nums">1,240</td>
                      <td className="py-2 text-right text-[10px] font-extrabold tabular-nums">982</td>
                      <td className="py-2 text-right text-[10px] font-extrabold tabular-nums">776</td>
                      <td className="py-2 text-right text-[10px] font-extrabold tabular-nums">79%</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </Card>
          </div>

          {/* Row 11-14 */}
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
            {/* 11 School Improvement (SSA) */}
            <Card title="11. School Improvement (SSA)" subtitle="This Month" action="View Details">
              <div className="px-3.5 py-3 flex-1 flex flex-col">
                <div className="flex items-baseline gap-1.5">
                  <span className="text-[20px] font-extrabold text-green-600 leading-none">+0.6</span>
                  <span className="flex items-center gap-0.5 text-[9.5px] font-bold text-green-600"><ArrowUp size={9} />0.3 vs last month</span>
                </div>
                <div className="text-[8.5px] text-muted font-semibold mt-0.5">Avg. SSA Gain (May)</div>
                <MiniArea values={[0.2, 0.32, 0.3, 0.45, 0.6]} color="#22c55e" />
                <div className="flex items-center gap-2.5 mt-1 border-t border-[var(--color-edify-divider)] pt-2">
                  <Donut
                    size={86} thickness={15}
                    data={[
                      { label: "Improved",  value: 412, color: "#22c55e" },
                      { label: "No Change", value: 100, color: "#f59e0b" },
                      { label: "Declined",  value: 73,  color: "#ef4444" },
                    ]}
                    centerMain="585" centerSub="Total Schools"
                  />
                  <div className="flex-1 space-y-1.5">
                    {[
                      { c: "#22c55e", l: "Improved",  v: "412 (70%)" },
                      { c: "#f59e0b", l: "No Change", v: "100 (17%)" },
                      { c: "#ef4444", l: "Declined",  v: "73 (13%)" },
                    ].map((r) => (
                      <div key={r.l} className="flex items-center gap-1.5 text-[9.5px]">
                        <span className="h-2 w-2 rounded-full shrink-0" style={{ background: r.c }} />
                        <span className="text-[#5b6675] font-medium flex-1">{r.l}</span>
                        <span className="font-bold">{r.v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </Card>

            {/* 12 One Test Literacy Outcomes */}
            <Card title="12. One Test Literacy Outcomes" subtitle="This Month" action="View Details">
              <div className="px-3.5 py-3 flex-1 flex flex-col">
                <div className="flex items-baseline gap-1.5">
                  <span className="text-[20px] font-extrabold text-green-600 leading-none">+8pp</span>
                  <span className="flex items-center gap-0.5 text-[9.5px] font-bold text-green-600"><ArrowUp size={9} />5pp vs last month</span>
                </div>
                <div className="text-[8.5px] text-muted font-semibold mt-0.5">Avg. Gain (May)</div>
                <MiniArea values={[2, 3.4, 3, 5.5, 8]} color="#22c55e" />
                <div className="flex items-center gap-2.5 mt-1 border-t border-[var(--color-edify-divider)] pt-2">
                  <Donut
                    size={86} thickness={15}
                    data={[
                      { label: "Above", value: 13747, color: "#22c55e" },
                      { label: "Near",  value: 4514,  color: "#f59e0b" },
                      { label: "Below", value: 3159,  color: "#ef4444" },
                    ]}
                    centerMain="21,480" centerSub="Learners"
                  />
                  <div className="flex-1 space-y-1.5">
                    {[
                      { c: "#22c55e", l: "Above Benchmark", v: "13,747 (64%)" },
                      { c: "#f59e0b", l: "Near Benchmark",  v: "4,514 (21%)" },
                      { c: "#ef4444", l: "Below Benchmark", v: "3,159 (15%)" },
                    ].map((r) => (
                      <div key={r.l} className="flex items-center gap-1.5 text-[9.5px]">
                        <span className="h-2 w-2 rounded-full shrink-0" style={{ background: r.c }} />
                        <span className="text-[#5b6675] font-medium flex-1">{r.l}</span>
                        <span className="font-bold">{r.v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </Card>

            {/* 13 IA Verification Overview */}
            <Card title="13. IA Verification Overview" subtitle="This Month" action="View Details">
              <div className="px-3.5 py-3 flex-1 flex items-center gap-3">
                <div className="flex-1 space-y-2">
                  {IA_ROWS.map((r) => (
                    <div key={r.label} className="flex items-center gap-2 text-caption border-b border-[#f4f6f8] last:border-b-0 pb-1.5 last:pb-0">
                      <span className="text-[#5b6675] font-medium flex-1 leading-tight">{r.label}</span>
                      <span className="font-extrabold">{r.value}</span>
                      {r.note && <span className="text-[9px] font-bold w-[26px] text-right" style={{ color: r.tone }}>{r.note}</span>}
                    </div>
                  ))}
                </div>
                <div className="flex flex-col items-center shrink-0">
                  <Ring pct={69} color="#2f74d9" size={72} label="Verified Rate" />
                  <div className="flex items-center gap-0.5 text-[9px] font-bold text-green-600 mt-1.5"><ArrowUp size={9} />7% vs last month</div>
                </div>
              </div>
            </Card>

            {/* 14 Finance to Field Overview */}
            <Card title="14. Finance to Field Overview" subtitle="This Month" action="View Details">
              <div className="px-3.5 py-3 flex-1 flex items-center gap-3">
                <div className="flex-1 space-y-2">
                  {FIN_ROWS.map((r) => (
                    <div key={r.label} className="flex items-center gap-2 text-caption border-b border-[#f4f6f8] last:border-b-0 pb-1.5 last:pb-0">
                      <span className="text-[#5b6675] font-medium flex-1 leading-tight">{r.label}</span>
                      <span className="font-extrabold" style={r.tone ? { color: r.tone } : undefined}>{r.value}</span>
                      {r.note && <span className="text-[9px] font-bold w-[26px] text-right" style={{ color: r.tone }}>{r.note}</span>}
                    </div>
                  ))}
                </div>
                <div className="flex flex-col items-center shrink-0">
                  <Ring pct={76} color="#d2901f" size={72} label="Accounted" />
                  <div className="flex items-center gap-0.5 text-[9px] font-bold text-[#e0524a] mt-1.5"><ArrowDown size={9} />8% vs plan</div>
                </div>
              </div>
            </Card>
          </div>

          {/* Row 15-17 + Quick Actions */}
          <div className="grid grid-cols-1 xl:grid-cols-4 gap-4">
            {/* 15 District Performance Snapshot */}
            <Card title="15. District Performance Snapshot" action="View Map">
              <div className="px-3.5 py-3 flex-1 flex gap-2">
                <div className="w-[112px] shrink-0"><UgandaMap /></div>
                <div className="flex-1 min-w-0 space-y-2.5">
                  <div>
                    <div className="text-[9px] font-bold uppercase tracking-wide text-muted mb-1">Top Districts</div>
                    {[["1. Gulu", "72%"], ["2. Lira", "69%"], ["3. Arua", "68%"]].map(([d, v]) => (
                      <div key={d} className="flex items-center justify-between text-caption py-[3px]">
                        <span className="font-semibold text-[#3a4753]">{d}</span>
                        <span className="font-bold text-green-600">{v}</span>
                      </div>
                    ))}
                  </div>
                  <div className="border-t border-[var(--color-edify-divider)] pt-1.5">
                    <div className="text-[9px] font-bold uppercase tracking-wide text-muted mb-1">Lowest Districts</div>
                    {[["1. Kitgum", "28%"], ["2. Nwoya", "32%"], ["3. Amudat", "35%"]].map(([d, v]) => (
                      <div key={d} className="flex items-center justify-between text-caption py-[3px]">
                        <span className="font-semibold text-[#3a4753]">{d}</span>
                        <span className="font-bold text-[#e0524a]">{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            </Card>

            {/* 16 Top Schools Needing Attention */}
            <Card title="16. Top Schools Needing Attention">
              <div className="px-3.5 pt-2 pb-3 flex-1">
                <table className="w-full table-fixed">
                  <colgroup>
                    <col className="w-[24%]" /><col className="w-[17%]" /><col className="w-[22%]" /><col className="w-[19%]" /><col className="w-[18%]" />
                  </colgroup>
                  <thead>
                    <tr className="text-[7.5px] text-muted font-bold uppercase border-b border-[var(--color-edify-divider)] align-bottom">
                      <th className="text-left font-bold py-1.5">School</th>
                      <th className="text-left font-bold py-1.5">District</th>
                      <th className="text-left font-bold py-1.5">Issue</th>
                      <th className="text-left font-bold py-1.5">Last Activity</th>
                      <th className="text-left font-bold py-1.5">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {TOP_SCHOOLS.map((r) => (
                      <tr key={r.school} className="border-b border-[#f4f6f8] last:border-b-0">
                        <td className="py-2 text-[9.5px] font-semibold text-[#1a2330] truncate">{r.school}</td>
                        <td className="py-2 text-[9.5px] text-[#6b7785] truncate">{r.district}</td>
                        <td className="py-2"><span className="text-[8.5px] font-bold text-[#b06a12] bg-[#fdf0db] rounded px-1 py-0.5 leading-tight inline-block">{r.issue}</span></td>
                        <td className="py-2 text-[9px] text-[#6b7785] truncate">{r.date}</td>
                        <td className="py-2 text-[9px] font-semibold text-[#2f6fe0] truncate">{r.action}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            {/* 17 Staff Support & Risk Signals */}
            <Card title="17. Staff Support & Risk Signals">
              <div className="px-3.5 pt-2 pb-3 flex-1">
                <table className="w-full table-fixed">
                  <colgroup>
                    <col className="w-[40%]" /><col className="w-[18%]" /><col className="w-[22%]" /><col className="w-[20%]" />
                  </colgroup>
                  <thead>
                    <tr className="text-[7.5px] text-muted font-bold uppercase border-b border-[var(--color-edify-divider)] align-bottom">
                      <th className="text-left font-bold py-1.5">Risk Area</th>
                      <th className="text-right font-bold py-1.5">This Week</th>
                      <th className="text-center font-bold py-1.5">Trend</th>
                      <th className="text-right font-bold py-1.5">Change</th>
                    </tr>
                  </thead>
                  <tbody>
                    {RISK_SIGNALS.map((r) => (
                      <tr key={r.area} className="border-b border-[#f4f6f8] last:border-b-0">
                        <td className="py-2 text-[9.5px] font-medium text-[#3a4753] truncate">{r.area}</td>
                        <td className="py-2 text-right text-caption font-extrabold tabular-nums">{r.week}</td>
                        <td className="py-2"><div className="flex justify-center"><MiniSpark values={r.trend} color={r.tone} /></div></td>
                        <td className="py-2 text-right">
                          <span className="inline-flex items-center gap-0.5 text-[9.5px] font-bold text-[#e0524a]">
                            <ArrowUp size={9} />{r.change}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>

            {/* Quick Actions */}
            <Card title="Quick Actions">
              <div className="px-3.5 py-3 flex-1 grid grid-cols-2 grid-rows-3 gap-2">
                {QUICK_ACTIONS.map((q) => (
                  <button key={q.label} className="flex flex-col items-center justify-center gap-1.5 rounded-lg border border-[var(--color-edify-divider)] hover:bg-[#f8fafb] transition-colors py-2">
                    <span className="grid place-items-center h-8 w-8 rounded-lg" style={{ background: q.bg, color: q.tone }}>
                      <q.icon size={15} />
                    </span>
                    <span className="text-[9.5px] font-semibold text-secondary text-center leading-tight">{q.label}</span>
                  </button>
                ))}
              </div>
            </Card>
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between gap-4 pt-1 pb-2">
            <p className="text-caption text-muted">
              All data is real-time and automatically updated from field, Salesforce, NetSuite, and impact assessment systems.
            </p>
            <div className="flex items-center gap-1.5 text-caption text-muted font-medium shrink-0">
              Data last synced: May 12, 2025 8:30 AM
              <RefreshCw size={12} />
            </div>
          </div>
        </div>
    </div>
  );
}

/* ───────────────────────── Small bits ───────────────────────── */

function KpiHead({ n, title, icon: Icon, tone, bg }: { n: number; title: string; icon: LucideIcon; tone: string; bg: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="grid place-items-center h-7 w-7 rounded-lg shrink-0" style={{ background: bg, color: tone }}>
        <Icon size={15} />
      </span>
      <span className="text-[11px] font-bold text-[#3a4753] leading-tight">{n}. {title}</span>
    </div>
  );
}

function Stat({ big, med, label }: { big?: string; med?: string; label: string }) {
  return (
    <div>
      {big && <span className="text-[19px] font-extrabold leading-none">{big}</span>}
      {med && <span className="text-[15px] font-extrabold leading-none">{med}</span>}
      <span className="block text-[9.5px] text-muted font-semibold mt-0.5">{label}</span>
    </div>
  );
}

function ViewDetails() {
  return <button className="text-caption font-semibold text-[#2f6fe0] hover:underline mt-2.5 text-left">View Details</button>;
}

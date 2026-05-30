"use client";

import Link from "next/link";
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from "recharts";
import {
  ArrowUpRight,
  ChevronRight,
  Target,
  UserCheck,
  ClipboardList,
  UserX,
  Cloud,
  Wallet,
  GraduationCap,
  Activity,
  ShieldCheck,
  Building2,
  Footprints,
  FileText,
  CheckCircle2,
  AlertTriangle,
  FileWarning,
  Route,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { CplBottomNav } from "@/components/mobile/CplBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { ProgressRing } from "@/components/ui/primitives";
import { PersonalTargetsCard } from "@/components/cpl/PersonalTargetsCard";
import { TeamBacklogSnapshotCard } from "@/components/cpl/TeamBacklogSnapshotCard";
import { FundingExecutionCard } from "@/components/cpl/FundingExecutionCard";
import { SchoolsNeedingSsaCard } from "@/components/refresh-followup/SchoolsNeedingSsaCard";
import { TrainingFollowUpCard } from "@/components/refresh-followup/TrainingFollowUpCard";
import { CceoPerformanceTable } from "@/components/cpl/CceoPerformanceTable";
import { SchoolSsaIntelligenceCard } from "@/components/cpl/SchoolSsaIntelligenceCard";
import { QuickActionsRow } from "@/components/cpl/QuickActionsRow";
import type { CurrentUser } from "@/lib/schools-mock";
import {
  cplMobileHero,
  cplMobileKpis,
  cplWeekSummary,
  cplTeamTrend,
  cplImmediateAttention,
  cplPersonalFieldwork,
  cplFieldworkSummary,
  type CplFieldworkTile,
  type CplMobileKpi,
  type CplWeekTile,
  type CplImmediateAttention as Attention,
} from "@/lib/cpl-mock";
import {
  getClientVerificationFor,
  CLIENT_SSA_VERIFICATION_RATE,
} from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

const VERIFY_BAR = {
  Met:       "bg-emerald-500",
  "On Track":"bg-sky-500",
  "At Risk": "bg-amber-500",
  Behind:    "bg-rose-500",
} as const;

const VERIFY_PILL = {
  Met:       "bg-emerald-100 text-emerald-700",
  "On Track":"bg-sky-100     text-sky-700",
  "At Risk": "bg-amber-100   text-amber-700",
  Behind:    "bg-rose-100    text-rose-700",
} as const;

const KPI_ICON: Record<CplMobileKpi["icon"], LucideIcon> = {
  target:        Target,
  userTarget:    UserCheck,
  clipboardList: ClipboardList,
  userAlert:     UserX,
  cloud:         Cloud,
  wallet:        Wallet,
};

const KPI_TONE: Record<CplMobileKpi["iconTone"], string> = {
  edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
  amber: "bg-amber-100 text-amber-700",
  rose:  "bg-rose-100 text-rose-600",
  blue:  "bg-blue-100 text-blue-700",
};

const CAPTION_TONE: Record<CplMobileKpi["captionTone"], string> = {
  edify: "text-emerald-600",
  amber: "text-amber-700",
  rose:  "text-rose-600",
};

const WEEK_ICON: Record<CplWeekTile["icon"], LucideIcon> = {
  graduationCap:   GraduationCap,
  schoolActivity:  Activity,
  shieldCheck:     ShieldCheck,
  checkCircle:     CheckCircle2,
};

const WEEK_TONE: Record<CplWeekTile["tone"], { bg: string; text: string }> = {
  edify:  { bg: "bg-[var(--color-edify-soft)]/80", text: "text-[var(--color-edify-primary)]" },
  amber:  { bg: "bg-amber-100",                    text: "text-amber-700" },
  violet: { bg: "bg-violet-100",                   text: "text-violet-700" },
  green:  { bg: "bg-emerald-100",                  text: "text-emerald-700" },
};

const STATUS_TONE: Record<CplWeekTile["status"], string> = {
  Planned: "text-[var(--color-edify-primary)]",
  Pendied: "text-amber-600",
  Due:     "text-emerald-600",
};

const ATTN_ICON: Record<Attention["icon"], LucideIcon> = {
  alertTriangle: AlertTriangle,
  fileWarning:   FileWarning,
  route:         Route,
};

const ATTN_TONE: Record<Attention["tone"], string> = {
  amber: "bg-amber-100 text-amber-700",
  rose:  "bg-rose-100 text-rose-600",
  edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
};

export function CplHomeView({ user }: { user?: CurrentUser } = {}) {
  const heroLines = cplMobileHero.title.split("\n");
  const verify = getClientVerificationFor(user?.staffId ?? "STF-DM-014");
  const verifyRatePct = Math.round(CLIENT_SSA_VERIFICATION_RATE * 100);

  return (
    <MobileShell>
      <MobileTopBar
        title={cplMobileHero.greeting}
        monthLabel={cplMobileHero.monthLabel}
        notificationsCount={cplMobileHero.notificationCount}
      />

      <main className="flex-1 px-3 pt-3 pb-4 space-y-3 bg-[var(--color-page)]">
        {/* Hero card — dark with achievement ring */}
        <section
          className="rounded-2xl p-4 text-white flex items-center gap-3"
          style={{ backgroundImage: "linear-gradient(180deg, #0e1c2c 0%, #0a1623 100%)" }}
        >
          <div className="flex-1 min-w-0">
            {heroLines.map((line, i) => (
              <div
                key={i}
                className="text-[19px] leading-[1.15] font-extrabold tracking-tight"
              >
                {line}
              </div>
            ))}
            <p className="mt-2 text-[11.5px] text-white/65 leading-snug">
              {cplMobileHero.subtitle}
            </p>
          </div>
          <div className="shrink-0 relative" style={{ width: 92, height: 92 }}>
            <ProgressRing
              pct={cplMobileHero.monthlyAchievementPct}
              size={92}
              stroke={9}
              color="#10d3a4"
              trackColor="rgba(255,255,255,0.12)"
            />
            <div className="absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none px-2">
              <div className="text-[19px] font-extrabold tabular leading-none">
                {cplMobileHero.monthlyAchievementPct}%
              </div>
              <div className="text-[8px] text-white/70 leading-[1.15] mt-1">
                {cplMobileHero.monthlyAchievementLabel}
              </div>
            </div>
          </div>
        </section>

        {/* 6 KPI cards — 3-col grid */}
        <section className="grid grid-cols-3 gap-2">
          {cplMobileKpis.map((k) => {
            const Icon = KPI_ICON[k.icon];
            return (
              <div
                key={k.key}
                className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-2.5 shadow-sm"
              >
                <span className={cn("w-7 h-7 rounded-md grid place-items-center", KPI_TONE[k.iconTone])}>
                  <Icon size={14} />
                </span>
                <div className="text-[10px] muted font-semibold leading-tight line-clamp-2 min-h-[24px] mt-1.5">
                  {k.label}
                </div>
                <div className="text-[18px] font-extrabold tabular leading-none mt-1">{k.value}</div>
                <div
                  className={cn(
                    "mt-1 inline-flex items-center gap-0.5 text-[10px] font-semibold",
                    CAPTION_TONE[k.captionTone],
                  )}
                >
                  {k.caption}
                  <ArrowUpRight size={10} />
                </div>
              </div>
            );
          })}
        </section>

        {/* My Field Work — CPLs also do trainings, visits, SSAs */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 shadow-sm">
          <div className="flex items-baseline justify-between mb-2 px-0.5">
            <div className="min-w-0">
              <h3 className="text-[13px] font-extrabold tracking-tight">My Field Work</h3>
              <div className="text-caption muted">
                {cplFieldworkSummary.daysInField} days in field · {cplFieldworkSummary.schoolsTouched} schools touched
              </div>
            </div>
            <Link
              href="/my-targets"
              className="text-[11px] font-semibold text-emerald-600 inline-flex items-center gap-0.5"
            >
              View targets
              <ChevronRight size={11} />
            </Link>
          </div>
          <div className="grid grid-cols-3 gap-2">
            {cplPersonalFieldwork.slice(0, 3).map((t) => (
              <FieldworkTile key={t.key} t={t} />
            ))}
          </div>
          <div className="grid grid-cols-2 gap-2 mt-2">
            {cplPersonalFieldwork.slice(3).map((t) => (
              <FieldworkTile key={t.key} t={t} />
            ))}
          </div>
          <Link
            href="/field-intelligence"
            className="mt-3 h-9 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-white inline-flex w-full items-center justify-center gap-1.5 text-[12px] font-extrabold shadow-sm shadow-emerald-500/25"
          >
            <FileText size={12} />
            Submit my Daily Field Debrief
          </Link>
        </section>

        {/* Client SSA Verification — 10% per-cycle quota */}
        {verify && (
          <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 shadow-sm">
            <div className="flex items-baseline justify-between mb-1.5 px-0.5">
              <div className="min-w-0">
                <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
                  <ShieldCheck size={13} className="text-emerald-600" />
                  Client SSA Verification
                </h3>
                <div className="text-caption muted leading-snug">
                  Verify {verifyRatePct}% of your {verify.assignedClients} Client schools this cycle.
                </div>
              </div>
              <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold whitespace-nowrap shrink-0", VERIFY_PILL[verify.status])}>
                {verify.status}
              </span>
            </div>
            <div className="flex items-center gap-2 mt-1">
              <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                <div className={cn("h-full rounded-full", VERIFY_BAR[verify.status])} style={{ width: `${Math.min(100, verify.pct)}%` }} />
              </div>
              <span className="text-caption font-extrabold tabular shrink-0">
                {verify.verified} / {verify.target}
              </span>
            </div>
            <Link
              href="/ssa/core-candidates"
              className="mt-2 text-[11px] font-semibold text-emerald-600 inline-flex items-center gap-0.5"
            >
              Open verification queue
              <ChevronRight size={11} />
            </Link>
          </section>
        )}

        {/* This Week — 4 small tiles */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 shadow-sm">
          <div className="flex items-center justify-between mb-2 px-0.5">
            <h3 className="text-[13px] font-extrabold tracking-tight">This Week</h3>
            <Link
              href={cplWeekSummary.cta.href}
              className="text-[11px] font-semibold text-emerald-600 inline-flex items-center gap-0.5"
            >
              {cplWeekSummary.cta.label}
              <ChevronRight size={11} />
            </Link>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {cplWeekSummary.tiles.map((t) => {
              const Icon = WEEK_ICON[t.icon];
              const tone = WEEK_TONE[t.tone];
              return (
                <div
                  key={t.key}
                  className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-2 flex flex-col items-center text-center"
                >
                  <span className={cn("w-7 h-7 rounded-md grid place-items-center mb-1", tone.bg, tone.text)}>
                    <Icon size={13} />
                  </span>
                  <div className="text-[9.5px] muted font-semibold leading-tight line-clamp-2 min-h-[24px]">
                    {t.label}
                  </div>
                  <div className="text-[15px] font-extrabold tabular leading-none mt-1">{t.value}</div>
                  <div className={cn("text-[9px] font-semibold mt-0.5", STATUS_TONE[t.status])}>
                    {t.status}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* Operational cards — same data the desktop dashboard surfaces,
            stacked vertically so the CPL on mobile can act on the same
            queues without needing to switch to desktop. The CCEO table
            and SSA-intelligence card render their mobile-stacked
            variants automatically (md:hidden swap). */}
        {user && (
          <>
            <PersonalTargetsCard />
            <CceoPerformanceTable />
            <SchoolSsaIntelligenceCard />
            <SchoolsNeedingSsaCard user={user} />
            <TrainingFollowUpCard user={user} />
            <TeamBacklogSnapshotCard />
            <FundingExecutionCard />
            <QuickActionsRow />
          </>
        )}

        {/* Bottom row: Team trend + Immediate Attention */}
        <section className="grid grid-cols-2 gap-2">
          <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 shadow-sm">
            <div className="flex items-baseline gap-1.5 mb-1">
              <h3 className="text-[12px] font-extrabold tracking-tight">Team Trend</h3>
              <span className="text-[10px] muted">(Last 8 Weeks)</span>
            </div>
            <div className="h-[120px] -mx-1.5">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={cplTeamTrend} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                  <YAxis
                    domain={[0, 100]}
                    ticks={[0, 25, 50, 75, 100]}
                    tickFormatter={(v) => `${v}%`}
                    tick={{ fontSize: 9, fill: "var(--color-edify-muted)" }}
                    axisLine={false}
                    tickLine={false}
                    width={28}
                  />
                  <XAxis
                    dataKey="week"
                    tick={{ fontSize: 9, fill: "var(--color-edify-muted)" }}
                    axisLine={false}
                    tickLine={false}
                    interval={0}
                  />
                  <Tooltip
                    contentStyle={{ fontSize: 11, borderRadius: 8 }}
                    formatter={(v) => [`${v}%`, "Achievement"]}
                  />
                  <Line
                    type="monotone"
                    dataKey="pct"
                    stroke="#10b981"
                    strokeWidth={2}
                    dot={{ r: 3, fill: "#10b981" }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 shadow-sm">
            <h3 className="text-[12px] font-extrabold tracking-tight mb-1.5">Immediate Attention</h3>
            <div className="space-y-1">
              {cplImmediateAttention.map((a) => {
                const Icon = ATTN_ICON[a.icon];
                return (
                  <Link
                    key={a.key}
                    href={a.href}
                    className="flex items-center gap-2 py-1.5 active:bg-[var(--color-edify-soft)]/40 rounded-md"
                  >
                    <span className={cn("w-6 h-6 rounded-md grid place-items-center shrink-0", ATTN_TONE[a.tone])}>
                      <Icon size={12} />
                    </span>
                    <div className="flex-1 text-[11px] font-semibold leading-tight">{a.label}</div>
                    <ChevronRight size={12} className="text-[var(--color-edify-muted)] shrink-0" />
                  </Link>
                );
              })}
            </div>
          </div>
        </section>
      </main>

      <CplBottomNav />
    </MobileShell>
  );
}

// Compact tile for the CPL "My Field Work" strip.
const FW_ICON: Record<CplFieldworkTile["icon"], LucideIcon> = {
  schoolVisit: Building2,
  training:    GraduationCap,
  ssa:         ShieldCheck,
  follow:      Footprints,
  debrief:     FileText,
};

const FW_TONE: Record<CplFieldworkTile["tone"], { bg: string; text: string }> = {
  edify:  { bg: "bg-[var(--color-edify-soft)]/80", text: "text-[var(--color-edify-primary)]" },
  green:  { bg: "bg-emerald-100", text: "text-emerald-700" },
  amber:  { bg: "bg-amber-100",   text: "text-amber-700" },
  violet: { bg: "bg-violet-100",  text: "text-violet-700" },
  blue:   { bg: "bg-sky-100",     text: "text-sky-700" },
};

function FieldworkTile({ t }: { t: CplFieldworkTile }) {
  const Icon = FW_ICON[t.icon];
  const tone = FW_TONE[t.tone];
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] p-2.5">
      <span className={cn("w-7 h-7 rounded-md grid place-items-center", tone.bg, tone.text)}>
        <Icon size={13} />
      </span>
      <div className="text-[9.5px] muted font-semibold leading-tight line-clamp-2 min-h-[22px] mt-1.5">
        {t.label}
      </div>
      <div className="text-[15px] font-extrabold tabular leading-none mt-0.5">
        {t.value}
        <span className="text-caption muted font-semibold tabular"> / {t.total}</span>
      </div>
    </div>
  );
}

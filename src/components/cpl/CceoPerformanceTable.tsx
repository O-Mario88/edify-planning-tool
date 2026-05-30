"use client";

import {
  Users,
  ChevronRight,
  Crown,
  AlertTriangle,
  ArrowUpRight,
  ShieldCheck,
  Database,
  Building2,
  type LucideIcon,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import {
  cceoPerformance,
  type CceoPerformanceRow,
  type RouteQuality,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const riskTone = (r: CceoPerformanceRow["riskStatus"]) =>
  r === "Low" ? "green" : r === "Medium" ? "amber" : "red";

const routeDot: Record<RouteQuality, string> = {
  Good:    "bg-[var(--color-success)]",
  Average: "bg-[var(--color-edify-orange)]",
  Poor:    "bg-[var(--color-danger)]",
};

const routeLabel: Record<RouteQuality, string> = {
  Good:    "text-[var(--color-success)]",
  Average: "text-[var(--color-edify-orange)]",
  Poor:    "text-[var(--color-danger)]",
};

// "612 (75%)" → { count: 612, pct: 75 }. Defensive — falls back to
// zeros if the mock string ever drifts so the table never crashes.
function parseVerified(s: string): { count: number; pct: number } {
  const m = s.match(/^(\d+)\s*\((\d+)%\)$/);
  if (!m) return { count: 0, pct: 0 };
  return { count: Number(m[1]), pct: Number(m[2]) };
}

// Backlog thresholds drive the row's chip colour so the eye can spot
// trouble at a glance without reading every number.
const BACKLOG_HIGH = 20;
const BACKLOG_MED  = 10;

// Verification thresholds keep the verified bar in sync with the
// risk badge. Anything below 65% paints red even if the staff card
// elsewhere reads "Low" risk.
const VERIFY_TARGET = 75;
const VERIFY_WATCH  = 65;

export function CceoPerformanceTable() {
  // Headline KPIs — computed from the same rows so the strip and the
  // table never drift. These four answer: how big is the team, who's
  // at risk, how much work is sitting unverified, and is the average
  // verification rate above the 75% bar.
  const teamSize       = cceoPerformance.length;
  const totalSchools   = cceoPerformance.reduce((a, c) => a + c.schoolsAssigned, 0);
  const atRiskCount    = cceoPerformance.filter((c) => c.riskStatus !== "Low").length;
  const totalBacklog   = cceoPerformance.reduce((a, c) => a + c.backlog, 0);
  const totalSfPending = cceoPerformance.reduce((a, c) => a + c.salesforcePending, 0);
  const avgVerifyPct   = Math.round(
    cceoPerformance.reduce((a, c) => a + parseVerified(c.verifiedActivities).pct, 0) / teamSize,
  );

  // Leader / laggard picked off verification %. The leader gets a
  // crown chip on the avatar; the laggard gets a rose dot. Both are
  // surfaced in the footer takeaway too so the CPL knows where to
  // focus coaching capacity.
  const sortedByVerify = [...cceoPerformance].sort(
    (a, b) => parseVerified(b.verifiedActivities).pct - parseVerified(a.verifiedActivities).pct,
  );
  const topPerformer = sortedByVerify[0];
  const laggard      = sortedByVerify[sortedByVerify.length - 1];

  return (
    <SectionCard
      icon={<Users size={13} />}
      title="CCEO Performance"
      subtitle={`${teamSize} CCEOs covering ${totalSchools} schools · ${atRiskCount} at risk · ${avgVerifyPct}% avg verification`}
      actions={
        <a
          className="inline-flex items-center gap-1 text-[var(--text-body)] font-semibold text-[var(--color-edify-primary)]"
          href="#cceo-performance"
        >
          View All CCEOs
          <ArrowUpRight size={11} />
        </a>
      }
    >
      {/* KPI strip — four stat tiles answering "what's the shape of
          this team right now?" before the per-CCEO breakdown below. */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
        <StatTile
          icon={Users}
          label="Team Size"
          value={teamSize}
          caption={`${totalSchools} schools covered`}
          tone="primary"
          stagger="stagger-1"
        />
        <StatTile
          icon={AlertTriangle}
          label="At Risk"
          value={atRiskCount}
          caption={atRiskCount === 0 ? "All clear" : "Medium / High risk status"}
          tone={atRiskCount > 0 ? "warn" : "good"}
          stagger="stagger-2"
        />
        <StatTile
          icon={Database}
          label="Total Backlog"
          value={totalBacklog}
          caption={`${totalSfPending} pending Salesforce IDs`}
          tone={totalBacklog > 50 ? "warn" : "neutral"}
          stagger="stagger-3"
        />
        <StatTile
          icon={ShieldCheck}
          label="Avg Verification"
          value={`${avgVerifyPct}%`}
          caption={avgVerifyPct >= VERIFY_TARGET ? "Above the 75% target" : "Below target — push verification"}
          tone={avgVerifyPct >= VERIFY_TARGET ? "good" : "warn"}
          stagger="stagger-4"
        />
      </div>

      {/* Mobile-stacked variant — one card per CCEO. Avatar with
          leader / laggard badge, then verification bar, then a 3-up
          micro-stat row (schools / backlog / route). Risk pill sits
          top-right so the at-a-glance read is "who and how risky". */}
      <div className="md:hidden space-y-2">
        {cceoPerformance.map((c) => {
          const verified = parseVerified(c.verifiedActivities);
          const isTop    = c.id === topPerformer.id;
          const isLag    = c.id === laggard.id && c.riskStatus !== "Low";

          const backlogTone =
            c.backlog >= BACKLOG_HIGH ? "rose"
            : c.backlog >= BACKLOG_MED ? "amber"
            : "emerald";
          const verifyBarColor =
            verified.pct >= VERIFY_TARGET ? "bg-emerald-500"
            : verified.pct >= VERIFY_WATCH ? "bg-amber-500"
            : "bg-rose-500";
          const edge =
            c.riskStatus === "High" ? "border-l-rose-500"
            : c.riskStatus === "Medium" ? "border-l-amber-500"
            : "border-l-emerald-500";

          return (
            <div
              key={c.id}
              className={cn("rounded-xl border border-[var(--color-edify-border)] border-l-[3px] bg-white p-3 space-y-2.5", edge)}
            >
              <div className="flex items-center gap-2.5">
                <div className="relative shrink-0">
                  <div className="w-9 h-9 rounded-full bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f] text-white text-[11px] font-extrabold grid place-items-center shadow-sm">
                    {c.initials}
                  </div>
                  {isTop && (
                    <span className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-emerald-500 grid place-items-center ring-2 ring-white">
                      <Crown size={9} className="text-white" />
                    </span>
                  )}
                  {isLag && !isTop && (
                    <span className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-rose-500 ring-2 ring-white" />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-body font-bold leading-tight truncate text-slate-900">{c.name}</div>
                  <div className="text-[11px] muted leading-tight inline-flex items-center gap-1 mt-0.5">
                    <Building2 size={10} />
                    {c.region}
                  </div>
                </div>
                <StatusBadge tone={riskTone(c.riskStatus)}>{c.riskStatus}</StatusBadge>
              </div>

              <div>
                <div className="flex items-center justify-between mb-1 text-caption">
                  <span className="font-bold uppercase tracking-wide text-slate-500">Verified</span>
                  <span className="font-extrabold tabular text-slate-900">
                    {verified.count} <span className="muted font-semibold">({verified.pct}%)</span>
                  </span>
                </div>
                <div className="h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div
                    className={cn("h-full rounded-full", verifyBarColor)}
                    style={{ width: `${verified.pct}%` }}
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 pt-1">
                <MobileMicroStat label="Schools" value={c.schoolsAssigned} />
                <MobileMicroStat
                  label="Backlog"
                  value={c.backlog}
                  tone={backlogTone === "rose" ? "warn" : backlogTone === "amber" ? "watch" : "good"}
                />
                <MobileMicroStat
                  label="Route"
                  value={c.routeQuality}
                  tone={
                    c.routeQuality === "Good" ? "good"
                    : c.routeQuality === "Average" ? "watch"
                    : "warn"
                  }
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Desktop table — 9 columns at xl, 7 columns below. Sticky
          header keeps the column labels in view as the CPL scrolls
          a long roster. The verified column collapses count + bar +
          % into a single visual gauge. */}
      <div className="hidden md:block overflow-x-auto scrollbar -mx-1 px-1 rounded-xl border border-[var(--color-edify-border)] bg-white">
        <table className="w-full text-[12px]">
          <thead className="sticky top-0 z-[1]">
            <tr className="bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[10px] uppercase tracking-wide text-slate-600">
              <th scope="col" className="text-left font-bold py-2 px-2.5">CCEO</th>
              <th scope="col" className="text-right font-bold py-2 px-2.5">Schools</th>
              <th scope="col" className="text-right font-bold py-2 px-2.5 hidden xl:table-cell">Planned</th>
              <th scope="col" className="text-left font-bold py-2 px-2.5 min-w-[170px]">Verified</th>
              <th scope="col" className="text-right font-bold py-2 px-2.5 hidden xl:table-cell">SF&nbsp;Pending</th>
              <th scope="col" className="text-right font-bold py-2 px-2.5">Backlog</th>
              <th scope="col" className="text-left font-bold py-2 px-2.5">Route</th>
              <th scope="col" className="text-left font-bold py-2 px-2.5">Risk</th>
              <th scope="col" className="py-2 px-2.5"><span className="sr-only">Open</span></th>
            </tr>
          </thead>
          <tbody>
            {cceoPerformance.map((c, idx) => {
              const verified = parseVerified(c.verifiedActivities);
              const isTop    = c.id === topPerformer.id;
              const isLag    = c.id === laggard.id && c.riskStatus !== "Low";
              const last     = idx === cceoPerformance.length - 1;

              const backlogTone =
                c.backlog >= BACKLOG_HIGH ? "rose"
                : c.backlog >= BACKLOG_MED ? "amber"
                : "emerald";

              const verifyBarColor =
                verified.pct >= VERIFY_TARGET ? "bg-emerald-500"
                : verified.pct >= VERIFY_WATCH ? "bg-amber-500"
                : "bg-rose-500";

              return (
                <tr
                  key={c.id}
                  className={cn(
                    "transition-colors hover:bg-[var(--color-edify-soft)]/40 cursor-pointer",
                    !last && "border-b border-[#eef2f4]",
                  )}
                >
                  <td className="py-2 px-2.5">
                    <div className="flex items-center gap-2">
                      <div className="relative shrink-0">
                        <div className="w-7 h-7 rounded-full bg-gradient-to-br from-[var(--color-edify-primary)] to-[#344f5f] text-white text-[10px] font-extrabold grid place-items-center shadow-sm">
                          {c.initials}
                        </div>
                        {isTop && (
                          <span
                            className="absolute -top-1 -right-1 w-3.5 h-3.5 rounded-full bg-emerald-500 grid place-items-center ring-2 ring-white"
                            title="Top performer — highest verification %"
                          >
                            <Crown size={8} className="text-white" />
                          </span>
                        )}
                        {isLag && !isTop && (
                          <span
                            className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-rose-500 ring-2 ring-white"
                            title="Needs support — lowest verification % and elevated risk"
                          />
                        )}
                      </div>
                      <div className="min-w-0">
                        <div className="text-[12px] font-bold leading-tight whitespace-nowrap text-slate-900">
                          {c.name}
                        </div>
                        <div className="text-caption muted leading-tight inline-flex items-center gap-1 mt-0.5">
                          <Building2 size={9} />
                          {c.region}
                        </div>
                      </div>
                    </div>
                  </td>

                  <td className="py-2 px-2.5 text-right tabular font-semibold">
                    {c.schoolsAssigned}
                  </td>

                  <td className="py-2 px-2.5 text-right tabular hidden xl:table-cell muted">
                    {c.plannedActivities.toLocaleString()}
                  </td>

                  <td className="py-2 px-2.5 min-w-[170px]">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                        <div
                          className={cn("h-full rounded-full", verifyBarColor)}
                          style={{ width: `${verified.pct}%` }}
                        />
                      </div>
                      <span className="text-[11px] font-bold tabular text-right whitespace-nowrap w-[74px]">
                        <span className="text-slate-900">{verified.count}</span>
                        <span className="muted font-semibold"> ({verified.pct}%)</span>
                      </span>
                    </div>
                  </td>

                  <td className="py-2 px-2.5 text-right tabular hidden xl:table-cell muted">
                    {c.salesforcePending}
                  </td>

                  <td className="py-2 px-2.5 text-right">
                    <span
                      className={cn(
                        "inline-flex items-center justify-center min-w-[32px] px-1.5 py-[2px] rounded-md text-[11px] font-extrabold tabular",
                        backlogTone === "rose"   && "bg-rose-50 text-rose-700",
                        backlogTone === "amber"  && "bg-amber-50 text-amber-700",
                        backlogTone === "emerald" && "bg-emerald-50 text-emerald-700",
                      )}
                    >
                      {c.backlog}
                    </span>
                  </td>

                  <td className="py-2 px-2.5">
                    <span className="inline-flex items-center gap-1.5">
                      <span className={cn("w-2 h-2 rounded-full inline-block", routeDot[c.routeQuality])} />
                      <span className={cn("font-semibold", routeLabel[c.routeQuality])}>
                        {c.routeQuality}
                      </span>
                    </span>
                  </td>

                  <td className="py-2 px-2.5">
                    <StatusBadge tone={riskTone(c.riskStatus)}>{c.riskStatus}</StatusBadge>
                  </td>

                  <td className="py-2 px-2.5 text-right">
                    <ChevronRight size={14} className="text-[var(--color-edify-muted)] inline-block" />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Takeaway footer — same data the table shows, but framed as
          "who to celebrate / who needs support" so the CPL leaves the
          card with a decision, not a stat blob. */}
      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px]">
        <span className="inline-flex items-center gap-1.5">
          <Crown size={12} className="text-emerald-600" />
          <span className="font-semibold text-slate-600">Top performer:</span>
          <span className="font-extrabold text-slate-900">{topPerformer.name}</span>
          <span className="muted">
            {parseVerified(topPerformer.verifiedActivities).pct}% verified · backlog {topPerformer.backlog}
          </span>
        </span>
        {laggard.riskStatus !== "Low" && (
          <span className="inline-flex items-center gap-1.5">
            <AlertTriangle size={12} className="text-rose-600" />
            <span className="font-semibold text-slate-600">Needs support:</span>
            <span className="font-extrabold text-slate-900">{laggard.name}</span>
            <span className="muted">
              {parseVerified(laggard.verifiedActivities).pct}% verified · backlog {laggard.backlog}
            </span>
          </span>
        )}
      </div>
    </SectionCard>
  );
}

// ───────────── MobileMicroStat ─────────────

const MICRO_TONE: Record<"good" | "watch" | "warn" | "neutral", string> = {
  good:    "text-emerald-700",
  watch:   "text-amber-700",
  warn:    "text-rose-700",
  neutral: "text-slate-900",
};

function MobileMicroStat({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number | string;
  tone?: "good" | "watch" | "warn" | "neutral";
}) {
  return (
    <div className="rounded-lg bg-[var(--color-edify-soft)]/40 px-2 py-1.5 text-center">
      <div className="text-[9.5px] font-bold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className={cn("text-[13px] font-extrabold tabular leading-tight mt-0.5", MICRO_TONE[tone])}>
        {value}
      </div>
    </div>
  );
}

// ───────────── StatTile ─────────────

type StatTone = "primary" | "good" | "warn" | "neutral";

const STAT_TONE: Record<StatTone, { bg: string; iconBg: string; iconColor: string; valueColor: string }> = {
  primary: {
    bg:         "bg-gradient-to-br from-[var(--color-edify-soft)]/50 to-white border-[var(--color-edify-border)]",
    iconBg:     "bg-[var(--color-edify-soft)]",
    iconColor:  "text-[var(--color-edify-primary)]",
    valueColor: "text-slate-900",
  },
  good: {
    bg:         "bg-gradient-to-br from-emerald-50 to-white border-emerald-200",
    iconBg:     "bg-emerald-100",
    iconColor:  "text-emerald-700",
    valueColor: "text-emerald-800",
  },
  warn: {
    bg:         "bg-gradient-to-br from-amber-50 to-white border-amber-200",
    iconBg:     "bg-amber-100",
    iconColor:  "text-amber-700",
    valueColor: "text-amber-800",
  },
  neutral: {
    bg:         "bg-gradient-to-br from-slate-50 to-white border-slate-200",
    iconBg:     "bg-slate-100",
    iconColor:  "text-slate-600",
    valueColor: "text-slate-900",
  },
};

function StatTile({
  icon: Icon,
  label,
  value,
  caption,
  tone,
  stagger,
}: {
  icon: LucideIcon;
  label: string;
  value: number | string;
  caption: string;
  tone: StatTone;
  stagger?: string;
}) {
  const p = STAT_TONE[tone];
  const glowClass =
    tone === "good"    ? "glow-emerald"
    : tone === "warn"  ? "glow-amber"
    : tone === "primary" ? "glow-slate"
    : "glow-slate";
  return (
    <div className={cn("rounded-xl border card-lift cursor-default tile-in p-2.5 flex items-start gap-2.5", stagger, p.bg)}>
      <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", p.iconBg)}>
        <Icon size={14} className={p.iconColor} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-bold uppercase tracking-wide text-slate-500">
          {label}
        </div>
        <div className={cn("text-[18px] font-extrabold tabular leading-none mt-0.5 num-hero", p.valueColor, glowClass)}>
          {value}
        </div>
        <div className="text-[10px] muted font-semibold mt-1 truncate">{caption}</div>
      </div>
    </div>
  );
}

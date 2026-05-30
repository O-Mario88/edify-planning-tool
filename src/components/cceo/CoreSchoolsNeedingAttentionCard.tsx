"use client";

import { useState } from "react";
import Link from "next/link";
import {
  AlertOctagon,
  AlertTriangle,
  ArrowUpRight,
  Building2,
  Calendar,
  ChevronRight,
  Footprints,
  GraduationCap,
  MapPin,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { coreSchoolsNeedingAttention, type CceoAttentionSchool } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

const RISK_TONE: Record<CceoAttentionSchool["riskTone"], string> = {
  rose:   "bg-rose-100   text-rose-700",
  amber:  "bg-amber-100  text-amber-700",
  violet: "bg-violet-100 text-violet-700",
};

const RISK_EDGE: Record<CceoAttentionSchool["riskTone"], string> = {
  rose:   "border-l-rose-500",
  amber:  "border-l-amber-500",
  violet: "border-l-violet-500",
};

const RISK_TEXT: Record<CceoAttentionSchool["riskTone"], string> = {
  rose:   "text-rose-600",
  amber:  "text-amber-600",
  violet: "text-violet-600",
};

// Pick a context icon for the issue based on the label keywords.
function issueIcon(label: string): LucideIcon {
  const l = label.toLowerCase();
  if (l.includes("no visit") && l.includes("no training")) return AlertOctagon;
  if (l.includes("no visit")) return Footprints;
  if (l.includes("no training")) return GraduationCap;
  if (l.includes("no ssa")) return AlertOctagon;
  return AlertTriangle;
}

// Suggest the highest-leverage next action for the row, derived from
// the risk label. Cheap heuristic; pays back the row's "what now?"
// question without forcing the user to open the school page.
function suggestedAction(s: CceoAttentionSchool): { label: string; href: string } {
  const l = s.riskLabel.toLowerCase();
  if (l.includes("no visit"))    return { label: "Schedule a visit",   href: "/plans/new" };
  if (l.includes("no training")) return { label: "Schedule training",  href: "/plans/new" };
  if (l.includes("no ssa"))      return { label: "Run SSA assessment", href: "/ssa" };
  return { label: "Plan a follow-up", href: "/plans/new" };
}

export function CoreSchoolsNeedingAttentionCard() {
  // Sort lowest-SSA first so the worst rows surface at the top.
  const sorted = [...coreSchoolsNeedingAttention].sort((a, b) => a.ssaAvg - b.ssaAvg);

  const lowest = sorted[0];
  const avgSsa = +(
    coreSchoolsNeedingAttention.reduce((a, s) => a + s.ssaAvg, 0) /
    coreSchoolsNeedingAttention.length
  ).toFixed(1);
  const roseCount  = coreSchoolsNeedingAttention.filter((s) => s.riskTone === "rose").length;
  const amberCount = coreSchoolsNeedingAttention.filter((s) => s.riskTone === "amber").length;
  const behindCount = coreSchoolsNeedingAttention.filter((s) =>
    s.riskLabel.toLowerCase().includes("behind schedule"),
  ).length;

  const headline = `${lowest.schoolName} (${lowest.ssaAvg.toFixed(1)}) is the most urgent — ${lowest.visits} visits, ${lowest.trainings} trainings. ${coreSchoolsNeedingAttention.length} schools below 6.0 (avg ${avgSsa}).`;

  const [openName, setOpenName] = useState<string | null>(null);

  return (
    <SectionCard
      icon={<AlertOctagon size={13} className="text-rose-600" />}
      title="Core Schools Needing Attention"
      subtitle={headline}
      actions={
        <Link
          href="/notifications"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* Unified responsive accordion. Replaced the earlier split (mobile
          stacked cards + desktop 7-column table) with one consistent row
          shape so a tap opens the same inline detail on every breakpoint
          — no separate navigation needed to see Visits / Trainings /
          Intervention / Risk for a row. */}
      <ul className="space-y-2">
        {sorted.map((s) => {
          const Icon = issueIcon(s.riskLabel);
          const open = openName === s.schoolName;
          const action = suggestedAction(s);
          return (
            <li
              key={s.schoolName}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] border-l-[3px] bg-white overflow-hidden transition-colors",
                RISK_EDGE[s.riskTone],
                open && "bg-[var(--color-edify-soft)]/30",
              )}
            >
              {/* Collapsed header — same row, same data on every width.
                  Tap toggles the expanded body below. */}
              <button
                type="button"
                onClick={() => setOpenName(open ? null : s.schoolName)}
                aria-expanded={open}
                aria-controls={`school-${s.schoolName.replace(/\s+/g, "-")}-detail`}
                className="w-full flex items-center gap-3 p-3 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
              >
                <div className="min-w-0 flex-1">
                  <div className="text-[13px] font-bold leading-tight truncate text-slate-900">
                    {s.schoolName}
                  </div>
                  <div className="text-caption muted leading-tight inline-flex items-center gap-1 mt-0.5">
                    <Building2 size={10} />
                    {s.district}
                    <span aria-hidden className="mx-1 opacity-50">·</span>
                    <Icon size={10} className={RISK_TEXT[s.riskTone]} />
                    <span className="truncate">{s.riskLabel}</span>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[18px] font-extrabold tabular leading-none text-rose-700">{s.ssaAvg.toFixed(1)}</div>
                  <div className="text-[9.5px] muted font-bold uppercase tracking-wide mt-0.5">SSA</div>
                </div>
                <ChevronRight
                  size={14}
                  className={cn(
                    "text-[var(--color-edify-muted)] shrink-0 transition-transform",
                    open && "rotate-90",
                  )}
                />
              </button>

              {/* Expanded body — facts grid + suggested action. Mirrors
                  the /plans accordion exactly so the pattern reads as a
                  system convention, not a one-off. */}
              {open && (
                <div
                  id={`school-${s.schoolName.replace(/\s+/g, "-")}-detail`}
                  className="px-3 pb-3 -mt-1 space-y-3"
                >
                  <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-3 rounded-xl bg-white border border-[var(--color-edify-border)] p-3.5">
                    <Fact icon={<MapPin size={11} />}      label="District" value={s.district} />
                    <Fact label="SSA Average" value={
                      <span className="inline-flex items-baseline gap-1">
                        <span className="text-rose-700">{s.ssaAvg.toFixed(1)}</span>
                        <span className="muted text-[11px] font-semibold">/ 10</span>
                      </span>
                    } />
                    <Fact icon={<Footprints size={11} />}    label="Visits"    value={s.visits} />
                    <Fact icon={<GraduationCap size={11} />} label="Trainings" value={s.trainings} />
                    <Fact label="Lowest Intervention" value={s.lowestIntervention} fullWidth />
                    <Fact label="Risk" value={
                      <span className={cn("inline-flex items-center px-1.5 py-[1.5px] rounded-md text-[10.5px] font-bold", RISK_TONE[s.riskTone])}>
                        {s.riskLabel}
                      </span>
                    } fullWidth />
                  </dl>

                  <div className="flex items-center gap-2 flex-wrap">
                    <Link
                      href={action.href}
                      className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold hover:bg-[var(--color-edify-dark)] transition-colors whitespace-nowrap"
                    >
                      <Calendar size={12} />
                      {action.label}
                    </Link>
                    <Link
                      href={`/schools?name=${encodeURIComponent(s.schoolName)}`}
                      className="inline-flex items-center gap-1.5 h-9 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60 transition-colors whitespace-nowrap"
                    >
                      Open school
                      <ArrowUpRight size={11} />
                    </Link>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11.5px] flex flex-wrap items-center gap-x-4 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <AlertOctagon size={12} className="text-rose-600" />
          <span className="font-bold">High risk:</span>
          <span className="muted">{roseCount} school{roseCount === 1 ? "" : "s"} · {amberCount} more in amber</span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-slate-700">
          <Sparkles size={12} className="text-amber-500" />
          <span className="font-bold">Schedule next:</span>
          <span className="muted">{behindCount} share &quot;behind schedule&quot; — book a cluster visit this week</span>
        </span>
      </div>
    </SectionCard>
  );
}

// ────────── Helpers ────────────────────────────────────────────────

function Fact({
  icon,
  label,
  value,
  fullWidth = false,
}: {
  icon?: React.ReactNode;
  label: string;
  value: React.ReactNode;
  fullWidth?: boolean;
}) {
  return (
    <div className={cn("min-w-0", fullWidth && "col-span-2 sm:col-span-4")}>
      <dt className="text-[10px] muted font-semibold uppercase tracking-wide flex items-center gap-1">
        {icon && <span className="text-[var(--color-edify-muted)]">{icon}</span>}
        {label}
      </dt>
      <dd className="text-[13px] font-extrabold tracking-tight mt-0.5 truncate">{value}</dd>
    </div>
  );
}

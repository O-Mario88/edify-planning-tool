// Fairness & Context — the workload / context-load view.
//
// The leaderboard ranks verified achievement; this panel measures how
// DEMANDING each person's context is so a lower raw % is read fairly.
// All scoring lives in lib/leaderboard-mock (cceoContextProfiles /
// programLeadContextProfiles). Pure renderer — no hooks.

import { ShieldCheck, Info, TrendingUp } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  cceoContextProfiles,
  programLeadContextProfiles,
  mostImprovedStaff,
  type ContextBand,
  type ContextFactor,
  type CceoContextProfile,
  type ProgramLeadContextProfile,
} from "@/lib/leaderboard-mock";
import { cn } from "@/lib/utils";

const BAND: Record<ContextBand, { chip: string; bar: string }> = {
  Light: { chip: "bg-slate-100 text-slate-700 border-slate-200", bar: "bg-slate-400" },
  Moderate: { chip: "bg-sky-100 text-sky-800 border-sky-200", bar: "bg-sky-500" },
  Heavy: { chip: "bg-amber-100 text-amber-800 border-amber-200", bar: "bg-amber-500" },
  "Very Heavy": {
    chip: "bg-violet-100 text-violet-800 border-violet-200",
    bar: "bg-violet-600",
  },
};

export function FairnessContextPanel() {
  return (
    <SectionCard
      icon={<ShieldCheck size={13} className="text-emerald-700" />}
      title="Fairness &amp; Context"
      subtitle="Verified results only. The context each person carries is measured and shown before any rank is read."
    >
      {/* CCEO context load */}
      <SubHeader
        title="CCEO context load"
        hint="Portfolio scope, partners, reach, travel, and the team support each officer carries."
      />
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {cceoContextProfiles.map((p) => (
          <CceoCard key={p.staffId} p={p} />
        ))}
      </div>

      {/* Program Lead context load */}
      <div className="mt-5">
        <SubHeader
          title="Program Lead context load"
          hint="Team span and portfolio carried, alongside team and regional outcomes."
        />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {programLeadContextProfiles.map((p) => (
            <PlCard key={p.programLeadId} p={p} />
          ))}
        </div>
      </div>

      {/* Most improved */}
      <div className="mt-5 pt-3 border-t border-[#eef2f4]">
        <div className="text-[12px] font-bold mb-2 inline-flex items-center gap-1.5">
          <TrendingUp size={12} className="text-emerald-600" />
          Most improved staff (month over month)
        </div>
        <div className="flex flex-wrap gap-2">
          {mostImprovedStaff.map((m) => (
            <span
              key={m.staffId}
              className="inline-flex items-center gap-2 rounded-lg border border-[var(--color-edify-border)] bg-white px-2.5 py-1"
            >
              <span className="w-6 h-6 rounded-full bg-emerald-100 text-emerald-700 grid place-items-center font-extrabold text-[10px]">
                +{m.improvementPoints}
              </span>
              <span className="text-[11.5px] font-semibold">{m.staffName}</span>
              <span className="text-[10px] muted">{m.category}</span>
            </span>
          ))}
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-caption muted">
        Context load is shown so achievement is read fairly — a heavier load is
        recognised, never penalised. Staff on approved leave or unrealistic
        routes are not ranked down.
      </div>
    </SectionCard>
  );
}

function SubHeader({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="mb-2">
      <div className="text-[12px] font-bold">{title}</div>
      <div className="text-caption muted">{hint}</div>
    </div>
  );
}

function BandChip({ band }: { band: ContextBand }) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-1.5 py-[2px] rounded-md text-[9.5px] font-extrabold uppercase tracking-wide border whitespace-nowrap",
        BAND[band].chip,
      )}
    >
      {band} load
    </span>
  );
}

function FactorBar({ f, band }: { f: ContextFactor; band: ContextBand }) {
  return (
    <li>
      <div className="flex items-baseline justify-between gap-1.5">
        <span className="text-[9.5px] muted font-bold uppercase tracking-wide truncate">
          {f.label}
        </span>
        <span className="text-[11px] font-extrabold tabular shrink-0">
          {f.display}
        </span>
      </div>
      <div className="mt-1 h-1 rounded-full bg-[#eef2f4] overflow-hidden">
        <div
          className={cn("h-full rounded-full", BAND[band].bar)}
          style={{ width: `${Math.max(4, Math.round(f.intensity * 100))}%` }}
        />
      </div>
      {f.sub && <div className="text-[9px] muted mt-0.5">{f.sub}</div>}
    </li>
  );
}

function Avatar({ initials }: { initials: string }) {
  return (
    <span className="h-9 w-9 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center text-[11px] font-extrabold shrink-0">
      {initials}
    </span>
  );
}

function LoadScore({ index }: { index: number }) {
  return (
    <div className="text-right shrink-0">
      <div className="text-[18px] font-extrabold tabular leading-none">{index}</div>
      <div className="text-[9px] muted uppercase tracking-wide mt-0.5">Load index</div>
    </div>
  );
}

function CceoCard({ p }: { p: CceoContextProfile }) {
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3.5 flex flex-col">
      <header className="flex items-start gap-2.5">
        <Avatar initials={p.initials} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-extrabold tracking-tight truncate">
            {p.staffName}
          </div>
          <div className="text-caption muted truncate">
            {p.region} · {p.programLeadName ?? "—"}
          </div>
        </div>
        <LoadScore index={p.loadIndex} />
      </header>

      <div className="mt-2">
        <BandChip band={p.band} />
      </div>

      <ul className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-2">
        {p.factors.map((f) => (
          <FactorBar key={f.key} f={f} band={p.band} />
        ))}
      </ul>

      {p.note && (
        <div className="mt-2.5 rounded-md bg-amber-50 border border-amber-200 px-2 py-1.5 text-[10px] text-amber-800 flex items-start gap-1.5">
          <Info size={11} className="mt-[1px] shrink-0" />
          <span>{p.note}</span>
        </div>
      )}
    </div>
  );
}

function PerfChip({ label, value }: { label: string; value: number }) {
  const tone =
    value >= 85
      ? "text-emerald-700"
      : value >= 72
        ? "text-amber-700"
        : "text-slate-600";
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 px-2.5 py-1.5">
      <div className="text-[9px] muted font-bold uppercase tracking-wide truncate">
        {label}
      </div>
      <div className={cn("text-[13px] font-extrabold tabular leading-tight", tone)}>
        {value}%
      </div>
    </div>
  );
}

function PlCard({ p }: { p: ProgramLeadContextProfile }) {
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3.5 flex flex-col">
      <header className="flex items-start gap-2.5">
        <Avatar initials={p.initials} />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-extrabold tracking-tight truncate">
            {p.programLeadName}
          </div>
          <div className="text-caption muted truncate">{p.region} region</div>
        </div>
        <LoadScore index={p.loadIndex} />
      </header>

      <div className="mt-2">
        <BandChip band={p.band} />
      </div>

      <ul className="mt-2.5 space-y-2">
        {p.factors.map((f) => (
          <FactorBar key={f.key} f={f} band={p.band} />
        ))}
      </ul>

      <div className="mt-2.5 grid grid-cols-2 gap-2">
        <PerfChip label="Team performance" value={p.teamPerformancePercent} />
        <PerfChip label="Regional perf." value={p.regionalPerformancePercent} />
      </div>
    </div>
  );
}

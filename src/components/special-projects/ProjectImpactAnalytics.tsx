"use client";

// Project impact analytics surface: Reach + Verified Delivery + linked-
// intervention Improvement + overall 8-intervention SSA + Donor-Ready, with
// inline drilldowns. Reuses the engine-backed chart vocabulary.

import { useState } from "react";
import {
  School, GraduationCap, Users, Baby, MapPin, Map as MapIcon, TrendingUp, TrendingDown, Minus,
  ShieldCheck, Handshake, AlertTriangle, ChevronDown, ChevronRight,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { PipelineFunnel, InterventionRankBar, SsaHeatmap } from "@/components/analytics/field-engine/charts";
import { cn } from "@/lib/utils";
import type { ProjectAnalyticsSnapshot } from "@/lib/projects/project-analytics";
import type { DrilldownRecord } from "@/lib/analytics/types";

function Trend({ value }: { value: number }) {
  const Icon = value > 0 ? TrendingUp : value < 0 ? TrendingDown : Minus;
  const tone = value > 0 ? "text-emerald-600" : value < 0 ? "text-rose-600" : "text-slate-400";
  return <span className={cn("inline-flex items-center gap-0.5 font-bold tabular", tone)}><Icon size={13} />{value > 0 ? "+" : ""}{value.toFixed(1)}</span>;
}

const QUALITY_TONE: Record<string, "green" | "blue" | "amber" | "red"> = {
  Excellent: "green", Good: "blue", "Needs Attention": "amber", Critical: "red",
};

/** A reach KPI whose value reveals its source rows on click. */
function ReachStat({
  label, value, caption, Icon, tone, records,
}: {
  label: string; value: string; caption?: string; Icon: typeof School;
  tone: string; records?: DrilldownRecord[];
}) {
  const [open, setOpen] = useState(false);
  const hasDrill = (records?.length ?? 0) > 0;
  return (
    <div className="card rounded-2xl p-3">
      <button type="button" disabled={!hasDrill} onClick={() => setOpen((v) => !v)} className={cn("w-full flex items-start gap-2.5 text-left", hasDrill && "cursor-pointer")}>
        <span className={`h-9 w-9 rounded-xl grid place-items-center shrink-0 ${tone}`}><Icon size={16} /></span>
        <span className="min-w-0 flex-1">
          <span className="text-[20px] font-extrabold tabular leading-none">{value}</span>
          <span className="block text-[11px] muted leading-tight mt-0.5">{label}</span>
          {caption && <span className="block text-[10.5px] muted mt-0.5">{caption}</span>}
        </span>
        {hasDrill && (open ? <ChevronDown size={13} className="muted mt-1" /> : <ChevronRight size={13} className="muted mt-1" />)}
      </button>
      {open && hasDrill && (
        <ul className="mt-2 pt-2 border-t border-[var(--color-edify-divider)] space-y-1 max-h-48 overflow-y-auto">
          {records!.map((r) => (
            <li key={r.id} className={cn("text-[11.5px] flex items-center justify-between gap-2", !r.contributesToCount && "opacity-50")}>
              <span className="truncate">{r.title}</span>
              <span className="muted shrink-0">{r.status}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ProjectImpactAnalytics({ snapshot }: { snapshot: ProjectAnalyticsSnapshot }) {
  const s = snapshot;
  const fmt = (n: number) => n.toLocaleString();

  return (
    <div className="space-y-3 md:space-y-4">
      {/* Reach KPI row */}
      <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <ReachStat label="Schools Impacted" value={fmt(s.schools.reached)} caption={`${s.schools.assigned} assigned`} Icon={School} tone="bg-blue-50 text-blue-700" records={s.schools.records} />
        <ReachStat label="Teachers Trained" value={fmt(s.teachersTrained.total)} caption={`${s.teachersTrained.verified} verified`} Icon={GraduationCap} tone="bg-violet-50 text-violet-700" />
        <ReachStat label="School Leaders" value={fmt(s.schoolLeadersTrained.total)} caption={`${s.schoolLeadersTrained.verified} verified`} Icon={Users} tone="bg-amber-50 text-amber-700" />
        <ReachStat label="Learners Impacted" value={fmt(s.learners.impacted)} caption={`${s.learners.schoolsContributing} schools`} Icon={Baby} tone="bg-emerald-50 text-emerald-700" />
        <ReachStat label="Districts Covered" value={fmt(s.districtsCovered)} caption={`${s.regionsCovered} regions`} Icon={MapPin} tone="bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]" />
        <ReachStat label="Linked Δ" value={`${s.improvement.change > 0 ? "+" : ""}${s.improvement.change.toFixed(1)}`} caption={s.intervention} Icon={MapIcon} tone="bg-rose-50 text-rose-700" />
      </section>

      {/* Assigned → Reached → Verified → Donor-ready split */}
      <SectionCard icon={<ShieldCheck size={13} />} title="Reach quality" subtitle="Planned activities never count. Each stage is a stricter, deduped subset.">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {[
            { label: "Assigned", value: s.schools.assigned, tone: "bg-slate-100 text-slate-600" },
            { label: "Reached", value: s.schools.reached, tone: "bg-blue-50 text-blue-700" },
            { label: "Verified (IA)", value: s.schools.verified, tone: "bg-amber-50 text-amber-700" },
            { label: "Donor-ready", value: s.schools.donorReady, tone: "bg-emerald-50 text-emerald-700" },
          ].map((x) => (
            <div key={x.label} className={`rounded-lg p-2.5 ${x.tone}`}>
              <div className="text-[20px] font-extrabold tabular leading-none">{x.value}</div>
              <div className="text-[11px] font-semibold mt-0.5">{x.label}</div>
            </div>
          ))}
        </div>
      </SectionCard>

      {/* Funnel + linked intervention before/after */}
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 md:col-span-7">
          <SectionCard title="Project impact funnel" subtitle="Assigned → reached → trained → followed up → assessed → improved.">
            <PipelineFunnel stages={s.funnel} />
          </SectionCard>
        </div>
        <div className="col-span-12 md:col-span-5">
          <SectionCard icon={<TrendingUp size={13} />} title={`${s.intervention} — before / after`}>
            <div className="flex items-end justify-around py-4">
              <div className="text-center">
                <div className="text-[11px] muted font-semibold">Baseline</div>
                <div className="text-[28px] font-extrabold tabular">{s.improvement.baselineAvg.toFixed(1)}</div>
              </div>
              <div className="text-center"><Trend value={s.improvement.change} /></div>
              <div className="text-center">
                <div className="text-[11px] muted font-semibold">Latest</div>
                <div className="text-[28px] font-extrabold tabular text-[var(--color-edify-primary)]">{s.improvement.latestAvg.toFixed(1)}</div>
              </div>
            </div>
            <div className="grid grid-cols-4 gap-1.5 text-center text-[11px] border-t border-[var(--color-edify-divider)] pt-2">
              <div><div className="font-extrabold tabular text-emerald-700">{s.improvement.improved}</div>Improved</div>
              <div><div className="font-extrabold tabular text-rose-700">{s.improvement.declined}</div>Declined</div>
              <div><div className="font-extrabold tabular text-slate-500">{s.improvement.noChange}</div>No change</div>
              <div><div className="font-extrabold tabular text-slate-400">{s.improvement.noComparison}</div>No data</div>
            </div>
          </SectionCard>
        </div>
      </section>

      {/* General 8-intervention SSA */}
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 md:col-span-5">
          <SectionCard title="Overall SSA across 8 interventions" subtitle={s.generalSsa.best && s.generalSsa.worst ? `Best: ${s.generalSsa.best.intervention} (${s.generalSsa.best.score}) · Worst: ${s.generalSsa.worst.intervention} (${s.generalSsa.worst.score})` : "No SSA data yet."}>
            <InterventionRankBar interventions={s.generalSsa.interventions} rows={s.generalSsa.heatmap} />
          </SectionCard>
        </div>
        <div className="col-span-12 md:col-span-7">
          <SectionCard title="SSA intervention heatmap (by district)">
            {s.generalSsa.heatmap.length > 0 ? (
              <SsaHeatmap interventions={s.generalSsa.interventions} rows={s.generalSsa.heatmap} />
            ) : (
              <p className="text-[12px] muted py-6 text-center">No SSA data for project schools yet.</p>
            )}
          </SectionCard>
        </div>
      </section>

      {/* Delivery + data quality */}
      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 md:col-span-7">
          <SectionCard icon={<Handshake size={13} />} title="Delivery">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-[11.5px]">
              {[
                { l: "Trainings", v: s.delivery.trainings },
                { l: "Follow-ups", v: s.delivery.followUps },
                { l: "Assessments", v: s.delivery.assessments },
                { l: "Evidence verified", v: s.delivery.evidenceVerified },
                { l: "Staff-delivered", v: s.delivery.staffActivities },
                { l: "Partner-delivered", v: s.delivery.partnerActivities },
                { l: "IA confirmed", v: s.delivery.iaConfirmed },
              ].map((x) => (
                <div key={x.l} className="rounded-lg border border-[var(--color-edify-border)] p-2">
                  <div className="text-[18px] font-extrabold tabular">{x.v}</div>
                  <div className="muted">{x.l}</div>
                </div>
              ))}
            </div>
          </SectionCard>
        </div>
        <div className="col-span-12 md:col-span-5">
          <SectionCard icon={<AlertTriangle size={13} />} title="Data quality" actions={<StatusBadge tone={QUALITY_TONE[s.dataQuality.score]}>{s.dataQuality.score}</StatusBadge>}>
            {s.dataQuality.warnings.length === 0 ? (
              <p className="text-[12px] muted py-2">No data-quality issues — donor-ready metrics are reliable.</p>
            ) : (
              <ul className="space-y-1.5">
                {s.dataQuality.warnings.map((w, i) => (
                  <li key={i} className="text-[11.5px] flex items-start gap-1.5 text-amber-800">
                    <AlertTriangle size={12} className="mt-0.5 shrink-0 text-amber-500" />{w}
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        </div>
      </section>
    </div>
  );
}

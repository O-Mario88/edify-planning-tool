"use client";

// Project impact analytics surface: Reach + Verified Delivery + linked-
// intervention Improvement + overall 8-intervention SSA + Donor-Ready, with
// inline drilldowns. Reuses the engine-backed chart vocabulary.

import { useState } from "react";
import {
  School, GraduationCap, Users, Baby, MapPin, Map as MapIcon, TrendingUp, TrendingDown, Minus,
  ShieldCheck, Handshake, AlertTriangle, Search,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { Modal } from "@/components/ui/Modal";
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

/** A reach KPI whose value opens a modal drilldown of its source rows. */
function ReachStat({
  label, value, caption, Icon, tone, records,
}: {
  label: string; value: string; caption?: string; Icon: typeof School;
  tone: string; records?: DrilldownRecord[];
}) {
  const [open, setOpen] = useState(false);
  const hasDrill = (records?.length ?? 0) > 0;
  const counted = records?.filter((r) => r.contributesToCount).length ?? 0;
  return (
    <>
      <button
        type="button" disabled={!hasDrill} onClick={() => setOpen(true)}
        className={cn("card rounded-2xl p-3 w-full flex items-start gap-2.5 text-left", hasDrill && "cursor-pointer hover:ring-1 hover:ring-[var(--color-edify-primary)]/30 transition-shadow")}
      >
        <span className={`h-9 w-9 rounded-xl grid place-items-center shrink-0 ${tone}`}><Icon size={16} /></span>
        <span className="min-w-0 flex-1">
          <span className="text-[20px] font-extrabold tabular leading-none">{value}</span>
          <span className="block text-[11px] muted leading-tight mt-0.5">{label}</span>
          {caption && <span className="block text-[10.5px] muted mt-0.5">{caption}</span>}
        </span>
        {hasDrill && <Search size={12} className="muted mt-1 shrink-0" />}
      </button>
      {hasDrill && (
        <Modal
          open={open}
          onClose={() => setOpen(false)}
          title={label}
          description={`${counted} of ${records!.length} school${records!.length === 1 ? "" : "s"} counted toward this metric. Dimmed rows are assigned but not yet counted.`}
          size="md"
          variant="sheet"
        >
          <ul className="divide-y divide-[var(--color-edify-divider)] max-h-[60vh] overflow-y-auto">
            {records!.map((r) => (
              <li key={r.id} className={cn("py-2 flex items-center justify-between gap-3 text-[12px]", !r.contributesToCount && "opacity-50")}>
                <span className="min-w-0">
                  <span className="font-semibold truncate">{r.title}</span>
                  {r.subtitle && <span className="block text-[11px] muted truncate">{r.subtitle}</span>}
                </span>
                <span className="muted shrink-0 text-[11px]">{r.status}</span>
              </li>
            ))}
          </ul>
        </Modal>
      )}
    </>
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
        <MetricStrip
          bare
          columns="grid-cols-2 md:grid-cols-4"
          metrics={[
            { key: "assigned", label: "Assigned", value: s.schools.assigned },
            { key: "reached", label: "Reached", value: s.schools.reached },
            { key: "verified", label: "Verified (IA)", value: s.schools.verified },
            { key: "donorReady", label: "Donor-ready", value: s.schools.donorReady, tone: "good" },
          ]}
        />
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
            <MetricStrip
              bare
              columns="grid-cols-2 sm:grid-cols-4"
              metrics={[
                { key: "trainings", label: "Trainings", value: s.delivery.trainings },
                { key: "followUps", label: "Follow-ups", value: s.delivery.followUps },
                { key: "assessments", label: "Assessments", value: s.delivery.assessments },
                { key: "evidenceVerified", label: "Evidence verified", value: s.delivery.evidenceVerified },
                { key: "staffActivities", label: "Staff-delivered", value: s.delivery.staffActivities },
                { key: "partnerActivities", label: "Partner-delivered", value: s.delivery.partnerActivities },
                { key: "iaConfirmed", label: "IA confirmed", value: s.delivery.iaConfirmed },
              ]}
            />
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

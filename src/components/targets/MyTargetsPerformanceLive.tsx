"use client";

// MyTargetsPerformanceLive — backend-driven performance cards from the central
// PerformanceService (/api/performance/my-targets). Shows every metric
// (school visits, trainings, SSA, evidence, IA, etc.) with target / achieved /
// remaining / percentage / status. No mock numbers.

import { useEffect, useState } from "react";
import { Activity, CheckCircle2, FileCheck, GraduationCap, ShieldCheck, Target, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import type { BePerfCard } from "@/lib/api/surfaces";

const STATUS_TONE: Record<string, string> = {
  completed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  exceeded: "bg-emerald-50 text-emerald-700 border-emerald-200",
  on_track: "bg-sky-50 text-sky-700 border-sky-200",
  behind: "bg-amber-50 text-amber-700 border-amber-200",
  at_risk: "bg-rose-50 text-rose-700 border-rose-200",
  no_target: "bg-slate-50 text-slate-500 border-slate-200",
};

const METRIC_META: Record<string, { label: string; icon: typeof Target }> = {
  school_visits: { label: "Schools Visited", icon: Target },
  schools_trained: { label: "Schools Trained", icon: GraduationCap },
  ssa_completed: { label: "SSA Completed", icon: CheckCircle2 },
  cluster_meetings: { label: "Cluster Meetings", icon: Users },
  group_trainings: { label: "Group Trainings", icon: GraduationCap },
  evidence_submitted: { label: "Evidence Submitted", icon: FileCheck },
  activity_codes_submitted: { label: "Activity Codes", icon: Activity },
  ia_verified_activities: { label: "IA Verified", icon: ShieldCheck },
};

const STATUS_LABEL: Record<string, string> = {
  completed: "Completed", exceeded: "Exceeded", on_track: "On Track",
  behind: "Behind", at_risk: "At Risk", no_target: "No target",
};

type PerfResponse = {
  fy: string;
  cards: Record<string, BePerfCard>;
  total_planned: number; total_completed: number; completion_rate: number;
};

export function MyTargetsPerformanceLive() {
  const [data, setData] = useState<PerfResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/performance/my-targets", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j && j.cards) setData(j); else setError("No performance data"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} onRetry={load} />;
  if (!data) return <EmptyState title="No performance data" message="Performance appears once activities are completed." />;

  const cards = Object.entries(data.cards).filter(([k]) => METRIC_META[k]);
  const pct = (n: number) => `${Math.round(n)}%`;

  return (
    <div className="space-y-3">
      {/* Completion rate summary */}
      <div className="flex items-center gap-3 rounded-xl border border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30 px-3.5 py-2.5">
        <div className="text-2xl font-extrabold text-[var(--color-edify-primary)]">{pct(data.completion_rate)}</div>
        <div className="flex-1">
          <div className="text-[12px] font-bold">Completion rate</div>
          <div className="text-[11px] muted">{data.total_completed} of {data.total_planned} activities completed (FY{data.fy})</div>
        </div>
        <div className="h-2 w-24 rounded-full bg-[var(--color-edify-divider)] overflow-hidden">
          <div className="h-full bg-[var(--color-edify-primary)] transition-all" style={{ width: `${Math.min(100, data.completion_rate)}%` }} />
        </div>
      </div>

      {/* Metric cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2.5">
        {cards.map(([key, card]) => {
          const meta = METRIC_META[key];
          const Icon = meta?.icon ?? Target;
          return (
            <div key={key} className="rounded-xl border border-[var(--color-edify-divider)] bg-white p-3">
              <div className="flex items-center justify-between mb-1.5">
                <Icon size={14} className="text-[var(--color-edify-muted)]" />
                <span className={cn("text-[9.5px] font-bold px-1.5 py-0.5 rounded-full border", STATUS_TONE[card.status] ?? STATUS_TONE.no_target)}>
                  {STATUS_LABEL[card.status] ?? card.status}
                </span>
              </div>
              <div className="text-[20px] font-extrabold leading-none">{card.achieved}</div>
              <div className="text-[10px] muted mt-0.5">{meta?.label ?? key}</div>
              {card.target > 0 && (
                <div className="text-[10px] muted mt-1">of {card.target} target · {pct(card.percentage)}</div>
              )}
              {card.target > 0 && card.remaining > 0 && (
                <div className="h-1 mt-1.5 rounded-full bg-[var(--color-edify-divider)] overflow-hidden">
                  <div className={cn("h-full transition-all",
                    card.status === "at_risk" ? "bg-rose-400" : card.status === "behind" ? "bg-amber-400" : "bg-emerald-400")}
                    style={{ width: `${Math.min(100, card.percentage)}%` }} />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

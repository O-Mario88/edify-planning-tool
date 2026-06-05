"use client";

// Core Planning Board — consumes CorePlan + CoreActivitySlot (the unified
// model, not a hardcoded array). Each plan shows package progress, the 4
// priority interventions, the 8 activity slots with real execution controls,
// the follow-up-SSA gate, and the computed impact + champion pipeline.

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Footprints, GraduationCap, Trophy, TrendingUp, Loader2, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { useDemoStore } from "@/components/demo/DemoStore";
import { advanceChampion } from "@/lib/actions/core-actions";
import { CoreSlotActions, type SlotViewer } from "./CoreSlotActions";
import { CoreFollowUpSsaButton } from "./CoreFollowUpSsaButton";
import { CoreFollowUpScheduleButton } from "./CoreFollowUpScheduleButton";
import type { CorePlanCardVM } from "@/lib/core/core-board";
import type { CoreActivitySlot } from "@/lib/core/core-types";

const PLAN_TONE: Record<string, string> = {
  "Active": "bg-sky-100 text-sky-700",
  "In Progress": "bg-amber-100 text-amber-700",
  "Completed Pending Follow-Up SSA": "bg-violet-100 text-violet-700",
  "Follow-Up SSA Scheduled": "bg-violet-100 text-violet-700",
  "Impact Measured": "bg-emerald-100 text-emerald-700",
  "Champion Candidate": "bg-emerald-100 text-emerald-700",
  "Champion Verified": "bg-emerald-100 text-emerald-700",
  "Draft": "bg-slate-100 text-slate-600",
  "Closed": "bg-slate-100 text-slate-600",
};

export function CorePlanBoard({ cards, viewer, canChampion }: { cards: CorePlanCardVM[]; viewer: SlotViewer; canChampion: boolean }) {
  if (cards.length === 0) {
    return (
      <div className="card p-8 text-center">
        <GraduationCap className="mx-auto text-[var(--color-edify-primary)]" size={26} />
        <h2 className="text-[13px] font-extrabold tracking-tight mt-2">No core plans in scope</h2>
        <p className="text-[11.5px] muted max-w-md mx-auto mt-1">Onboard a verified candidate from the Core Onboarding Queue to create a core plan here.</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {cards.map((c) => <PlanCard key={c.plan.id} c={c} viewer={viewer} canChampion={canChampion} />)}
    </div>
  );
}

function PlanCard({ c, viewer, canChampion }: { c: CorePlanCardVM; viewer: SlotViewer; canChampion: boolean }) {
  const visits = c.slots.filter((s) => s.activityType === "visit").sort((a, b) => a.sequenceNumber - b.sequenceNumber);
  const trainings = c.slots.filter((s) => s.activityType === "training").sort((a, b) => a.sequenceNumber - b.sequenceNumber);

  return (
    <section className="card p-4">
      {/* Header */}
      <header className="flex items-start justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-[14px] font-extrabold tracking-tight truncate">{c.schoolName}</h3>
            <span className="text-[10px] muted tabular">ID {c.plan.schoolId}</span>
            <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded text-[10px] font-bold", PLAN_TONE[c.plan.status])}>{c.plan.status}</span>
            {c.championStatus !== "Not Eligible" && (
              <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded text-[10px] font-bold bg-amber-100 text-amber-800"><Trophy size={10} /> {c.championStatus}</span>
            )}
          </div>
          <p className="text-[11px] muted mt-0.5">{c.district}{c.cluster ? ` · ${c.cluster}` : ""} · Owner {c.owner ?? "—"} · Baseline SSA {c.baselineAverage.toFixed(1)} · {c.plan.fy}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[9.5px] muted font-bold uppercase tracking-wide">Package</div>
          <div className="text-[18px] font-extrabold tabular leading-none">{c.progress.packageCompletionPercent}%</div>
          <div className="text-[10px] muted">{c.progress.visitsCompleted}/4 visits · {c.progress.trainingsCompleted}/4 trainings</div>
        </div>
      </header>

      <div className="h-1.5 w-full rounded-full bg-[var(--color-edify-soft)] overflow-hidden mt-2.5">
        <div className="h-full rounded-full bg-[var(--color-edify-primary)] transition-all" style={{ width: `${c.progress.packageCompletionPercent}%` }} />
      </div>

      {/* Priority interventions */}
      <div className="flex flex-wrap gap-1.5 mt-3">
        {c.interventions.map((i) => (
          <span key={i.id} className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-bold bg-[var(--color-edify-soft)]/70 text-[var(--color-edify-text)]">
            <span className="text-[var(--color-edify-primary)]">#{i.priorityRank}</span> {i.intervention} <span className="muted">({i.baselineScore})</span>
          </span>
        ))}
      </div>

      {/* Slots */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-4 gap-y-1.5 mt-3">
        <SlotColumn title="Visits" Icon={Footprints} slots={visits} viewer={viewer} />
        <SlotColumn title="Trainings" Icon={GraduationCap} slots={trainings} viewer={viewer} />
      </div>

      {/* Follow-up SSA gate: schedule (staff) → record scores (IA) */}
      {(c.plan.status === "Completed Pending Follow-Up SSA" || c.plan.status === "Follow-Up SSA Scheduled") && (
        <div className="mt-3 pt-3 border-t border-[var(--color-edify-divider)] flex flex-wrap items-center gap-2">
          {c.plan.followUpScheduledFor && (
            <span className="text-[11px] muted">Follow-Up SSA: <b className="text-[var(--color-edify-text)]">{c.plan.followUpScheduledFor}</b>{c.plan.followUpAssignee ? ` · ${c.plan.followUpAssignee}` : ""}</span>
          )}
          {c.plan.status === "Completed Pending Follow-Up SSA" && <CoreFollowUpScheduleButton planId={c.plan.id} />}
          {viewer.canIa
            ? <CoreFollowUpSsaButton planId={c.plan.id} />
            : !c.plan.followUpScheduledFor && <span className="text-[11.5px] muted">Package complete — schedule the follow-up SSA; IA records the scores.</span>}
        </div>
      )}

      {/* Impact */}
      {c.impact && (
        <div className="mt-3 pt-3 border-t border-[var(--color-edify-divider)]">
          <div className="flex items-center justify-between gap-2 flex-wrap">
            <div className="inline-flex items-center gap-2 text-[12px] font-extrabold">
              <TrendingUp size={14} className={c.impact.averageChange >= 0 ? "text-emerald-600" : "text-rose-600"} />
              Impact: baseline {c.impact.baselineAverage.toFixed(1)} → follow-up {c.impact.followUpAverage.toFixed(1)}
              <span className={cn("tabular", c.impact.averageChange >= 0 ? "text-emerald-700" : "text-rose-700")}>({c.impact.averageChange >= 0 ? "+" : ""}{c.impact.averageChange})</span>
            </div>
            {canChampion && c.championStatus !== "Not Eligible" && c.championStatus !== "Champion Mentor School" && (
              <ChampionAdvance schoolId={c.plan.schoolId} status={c.championStatus} />
            )}
          </div>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {c.impact.priorityInterventionChange.map((ic) => (
              <span key={ic.intervention} className={cn("inline-flex items-center gap-1 px-1.5 py-[2px] rounded text-[10px] font-bold",
                ic.classification === "Improved" ? "bg-emerald-50 text-emerald-700" : ic.classification === "Declined" ? "bg-rose-50 text-rose-700" : "bg-slate-100 text-slate-600")}>
                {ic.intervention} {ic.change >= 0 ? "+" : ""}{ic.change}
              </span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function SlotColumn({ title, Icon, slots, viewer }: { title: string; Icon: typeof Footprints; slots: CoreActivitySlot[]; viewer: SlotViewer }) {
  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wide muted inline-flex items-center gap-1 mb-1"><Icon size={11} /> {title}</div>
      <ul className="space-y-1">
        {slots.map((s) => (
          <li key={s.id} className="flex items-center justify-between gap-2 rounded-lg border border-[var(--color-edify-divider)] px-2.5 py-1.5">
            <span className="text-[11.5px] font-semibold min-w-0 truncate">{title.slice(0, -1)} {s.sequenceNumber} · <span className="muted">{s.intervention}</span></span>
            <CoreSlotActions slot={s} viewer={viewer} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChampionAdvance({ schoolId, status }: { schoolId: string; status: string }) {
  const [isPending, start] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();
  return (
    <button type="button" disabled={isPending}
      onClick={() => start(async () => {
        const res = await advanceChampion(schoolId);
        if (res.ok) { pushToast({ tone: "success", title: "Champion pipeline", body: `Now ${res.status}.` }); router.refresh(); }
        else pushToast({ tone: "warning", title: "Couldn't advance", body: res.reason === "FORBIDDEN" ? "Not your stage." : "Try again." });
      })}
      className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-amber-500 text-white text-[11px] font-bold hover:bg-amber-600 disabled:opacity-50">
      {isPending ? <Loader2 size={11} className="animate-spin" /> : <ArrowUpRight size={11} />} Advance ({status})
    </button>
  );
}

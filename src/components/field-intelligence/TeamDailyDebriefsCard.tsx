"use client";

// Team Daily Debriefs — Program Lead surface.
//
// Per visibility rule: daily debriefs only show on (1) CCEO My Targets and
// (2) Program Lead dashboard. This card is the PL view: submitted today /
// missing today / support requested / critical blockers + real-time
// blockers raised TODAY (from cceo-execution-store), with deep links to
// the per-CCEO debrief.

import { useEffect, useState } from "react";
import Link from "next/link";
import { Brain, AlertTriangle, CheckCircle2, MessageSquare, ChevronRight, Zap } from "lucide-react";
import { dailyDebriefs } from "@/lib/field-intelligence-mock";
import { blockersForToday, type RealtimeBlocker } from "@/lib/cceo-execution-store";
import { cn } from "@/lib/utils";

export function TeamDailyDebriefsCard({ programLeadId }: { programLeadId: string }) {
  // Scope every read to the PL's own team — this card is a PL surface and
  // must not leak debriefs from staff supervised by a different PL.
  const teamDebriefs    = dailyDebriefs.filter((d) => d.programLeadId === programLeadId);
  const today           = teamDebriefs.filter((d) => d.date === "2025-11-12");
  const expected        = 8;
  const submittedToday  = Math.min(today.length, expected);
  const missingToday    = Math.max(0, expected - submittedToday);
  const supportRequests = teamDebriefs.filter((d) => d.supportNeeded && d.supportNeeded.length > 0).slice(0, 4);
  const criticalRows    = teamDebriefs.filter((d) => d.howDayWent === "Could Not Execute Planned Work" || d.howDayWent === "Very Difficult").slice(0, 3);

  // Real-time blockers raised TODAY by any CCEO (client-side store).
  // Migrate to useSyncExternalStore during the React-19 sweep.
  const [liveBlockers, setLiveBlockers] = useState<RealtimeBlocker[]>([]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { setLiveBlockers(blockersForToday()); }, []);

  return (
    <section className="card p-3.5 space-y-3">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
          <Brain size={14} className="text-[var(--color-edify-primary)]" />
          Team Daily Debriefs
        </h3>
        <Link href="/debriefs" className="text-[11px] font-extrabold text-[var(--color-edify-primary)] inline-flex items-center gap-1 hover:underline">
          Open all <ChevronRight size={11} />
        </Link>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
        <Stat label="Submitted today"     value={submittedToday}        tone="green" />
        <Stat label="Missing today"       value={missingToday}          tone={missingToday > 0 ? "amber" : "edify"} />
        <Stat label="Support requested"   value={supportRequests.length} tone="violet" />
        <Stat label="Critical blockers"   value={criticalRows.length}    tone={criticalRows.length > 0 ? "rose" : "edify"} />
        <Stat label="Live blockers (now)" value={liveBlockers.length}    tone={liveBlockers.length > 0 ? "rose" : "edify"} />
      </div>

      {/* Real-time blockers raised today */}
      {liveBlockers.length > 0 && (
        <div className="rounded-xl border border-rose-300 bg-rose-50/80 p-3 space-y-1.5">
          <div className="text-[11px] font-extrabold text-rose-800 inline-flex items-center gap-1.5">
            <Zap size={11} />
            Raised live today (not waiting for end-of-day debrief)
          </div>
          <ul className="space-y-1">
            {liveBlockers.slice(0, 5).map((b) => (
              <li key={b.id} className="text-[11.5px] text-rose-900 leading-snug flex items-baseline justify-between gap-2 flex-wrap">
                <span className="min-w-0">
                  <span className="font-extrabold">{b.schoolName ?? "Field"}</span>
                  <span className="muted mx-1">·</span>
                  <span className="font-extrabold">{b.category}</span>
                  <span className="muted mx-1">·</span>
                  <span>{b.note}</span>
                  {b.photoTaken && <span className="muted ml-1">· photo</span>}
                </span>
                <span className="text-[10px] muted whitespace-nowrap">{b.raisedAt.slice(11, 16)}</span>
              </li>
            ))}
            {liveBlockers.length > 5 && (
              <li className="text-caption muted text-center">+{liveBlockers.length - 5} more raised today</li>
            )}
          </ul>
        </div>
      )}

      {criticalRows.length > 0 && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/70 p-3 space-y-1.5">
          <div className="text-[11px] font-extrabold text-rose-800 inline-flex items-center gap-1.5">
            <AlertTriangle size={11} />
            Field reality — open today
          </div>
          <ul className="space-y-1">
            {criticalRows.map((d) => (
              <li key={d.id} className="text-[11.5px] text-rose-900 leading-snug">
                <span className="font-extrabold">{d.staffName}</span> · {d.howDayWent} · {d.completedActivities}/{d.plannedActivities} completed
                {d.barrierCategories.length > 0 && (
                  <span className="text-rose-700"> · {d.barrierCategories.slice(0, 2).join(", ")}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {supportRequests.length > 0 && (
        <ul className="space-y-1.5">
          {supportRequests.map((d) => (
            <li key={d.id} className="rounded-lg border border-[var(--color-edify-border)] bg-white p-2.5 flex items-start gap-2">
              <span className="h-7 w-7 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <MessageSquare size={13} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-extrabold tracking-tight truncate">{d.staffName}</div>
                <div className="text-caption muted truncate">
                  Support: <span className="font-extrabold text-[var(--color-edify-text)]">{d.supportNeeded.slice(0, 2).join(", ")}</span>
                </div>
              </div>
              <Link href={`/debriefs/${d.id}`} className="text-caption font-extrabold text-[var(--color-edify-primary)] hover:underline whitespace-nowrap">
                Review →
              </Link>
            </li>
          ))}
        </ul>
      )}

      {missingToday === 0 && criticalRows.length === 0 && supportRequests.length === 0 && (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-3 flex items-start gap-2">
          <CheckCircle2 size={12} className="text-emerald-600 mt-0.5" />
          <div className="text-[11.5px] text-emerald-800 leading-snug">
            <span className="font-extrabold">All clear for today.</span> Every CCEO submitted on time, no blockers raised.
          </div>
        </div>
      )}

      <div className="text-caption muted leading-snug pt-1 border-t border-[var(--color-edify-border)]">
        Daily debriefs stay close to the field. Your weekly compiled report goes to the Country Director on Friday.
      </div>
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone: "edify" | "green" | "amber" | "rose" | "violet" }) {
  const tones = {
    edify:  "bg-[var(--color-edify-soft)]/40 border-[var(--color-edify-border)]",
    green:  "bg-emerald-50 border-emerald-200",
    amber:  "bg-amber-50   border-amber-200",
    rose:   "bg-rose-50    border-rose-200",
    violet: "bg-violet-50  border-violet-200",
  } as const;
  return (
    <div className={cn("rounded-xl border px-3 py-2", tones[tone])}>
      <div className="text-[10px] muted font-bold uppercase tracking-wide truncate">{label}</div>
      <div className="text-[18px] font-extrabold tabular leading-tight">{value}</div>
    </div>
  );
}

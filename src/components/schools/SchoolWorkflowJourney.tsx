import { Check, Circle, AlertTriangle, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { BeSchoolWorkflow } from "@/lib/api/surfaces";

// The main workflow made visible: Directory → Owner → Cluster → SSA → Plan →
// Execute → Verify → Pay → Improve. Each step's status comes from the backend.
export function SchoolWorkflowJourney({ wf }: { wf: BeSchoolWorkflow }) {
  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5">
        <h2 className="text-[12px] font-extrabold uppercase tracking-wide muted">School improvement journey</h2>
        <span className="text-[10.5px] font-bold text-[var(--color-edify-primary)] capitalize">Stage · {wf.stage.replace(/_/g, " ")}</span>
      </header>

      {/* Stepper — wraps on mobile, no horizontal scroll. */}
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
        {wf.steps.map((s, i) => (
          <li key={s.key} className="flex items-center gap-1">
            <span
              title={s.label}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-full pl-1 pr-2.5 py-1 text-[10.5px] font-bold border",
                s.status === "done" ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                  : s.status === "current" ? "bg-[var(--color-edify-primary)] text-white border-transparent"
                  : "bg-slate-50 text-slate-400 border-slate-200",
              )}
            >
              <span className={cn("grid place-items-center h-4 w-4 rounded-full shrink-0", s.status === "done" ? "bg-emerald-500 text-white" : s.status === "current" ? "bg-white/25" : "bg-slate-200 text-slate-400")}>
                {s.status === "done" ? <Check size={10} /> : <Circle size={7} />}
              </span>
              <span className="whitespace-nowrap">{s.label}</span>
            </span>
            {i < wf.steps.length - 1 && <ArrowRight size={11} className="text-slate-300 shrink-0" />}
          </li>
        ))}
      </ol>

      {wf.nextAction && (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-[var(--color-edify-primary)]/20 bg-[var(--color-edify-soft)]/30 p-2.5">
          <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-primary)] text-white shrink-0"><ArrowRight size={14} /></span>
          <div className="min-w-0">
            <div className="text-[12px] font-extrabold">Next · {wf.nextAction.label}</div>
            <div className="text-[11px] muted leading-snug">{wf.nextAction.reason}</div>
          </div>
        </div>
      )}

      {wf.blockers.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {wf.blockers.map((b) => (
            <span key={b} className="inline-flex items-center gap-1 rounded-full bg-amber-50 text-amber-700 px-2 py-0.5 text-[10.5px] font-bold border border-amber-200">
              <AlertTriangle size={10} /> {b}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

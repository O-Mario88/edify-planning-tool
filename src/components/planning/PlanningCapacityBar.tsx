import { Ban } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PlanningCapacity } from "@/lib/planning/planning-capacity";
import { ScheduleActivityButton } from "./ScheduleActivityButton";
import type { ActivityKind } from "@/lib/actions/store";

// Per-school planning capacity (the gray-out rule made visible). Client schools
// get one visit; core schools get 4 visits + 4 trainings. When a quota is full
// the matching "Schedule" button is disabled with the reason — never a dead link.

function Quota({ label, used, allowed, full }: { label: string; used: number; allowed: number; full: boolean }) {
  if (allowed === 0) return null;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-bold border", full ? "bg-slate-100 text-slate-500 border-slate-200" : "bg-emerald-50 text-emerald-700 border-emerald-200")}>
      {label} <span className="tabular">{used}/{allowed}</span>{full ? " · full" : ""}
    </span>
  );
}

function DisabledButton({ label, reason }: { label: string; reason: string | null }) {
  return (
    <span
      title={reason ?? "Not available"}
      aria-disabled="true"
      className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 text-slate-400 px-3 py-1.5 text-[11.5px] font-extrabold cursor-not-allowed border border-slate-200"
    >
      <Ban size={13} /> {label}
    </span>
  );
}

export function PlanningCapacityBar({ schoolId, schoolName, capacity }: { schoolId: string; schoolName?: string; capacity: PlanningCapacity }) {
  const VISIT: ActivityKind = "SCHOOL_VISIT";
  const TRAINING: ActivityKind = "TRAINING_FOLLOW_UP";
  return (
    <div className="card p-3 flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[11px] font-extrabold uppercase tracking-wide muted">Planning capacity</span>
        <Quota label="Visits" used={capacity.visitsUsed} allowed={capacity.visitsAllowed} full={!capacity.canPlanVisit} />
        <Quota label="Trainings" used={capacity.trainingsUsed} allowed={capacity.trainingsAllowed} full={!capacity.canPlanTraining} />
        {capacity.fullyPlanned && (
          <span className="text-[11px] font-bold text-slate-500">· Fully planned for this FY</span>
        )}
      </div>
      <div className="flex items-center gap-2">
        {capacity.canPlanVisit
          ? <ScheduleActivityButton schoolId={schoolId} schoolName={schoolName} kind={VISIT} label="Schedule Visit" />
          : <DisabledButton label="Schedule Visit" reason={capacity.visitDisabledReason} />}
        {capacity.schoolType === "core" && (
          capacity.canPlanTraining
            ? <ScheduleActivityButton schoolId={schoolId} schoolName={schoolName} kind={TRAINING} label="Schedule Training" />
            : <DisabledButton label="Schedule Training" reason={capacity.trainingDisabledReason} />
        )}
      </div>
    </div>
  );
}

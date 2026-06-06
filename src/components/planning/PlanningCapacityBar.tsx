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

// Assignment view-model (role rules + staff support capacity) from the policy engine.
export type AssignmentVM = {
  staffUsed: number;
  staffMax: number;
  staffAtLimit: boolean;
  staffNearLimit: boolean;
  showSelf: boolean;
  selfEnabled: boolean;
  selfReason?: string;
  partnerEnabled: boolean;
  partnerReason?: string;
  team: { name: string; staffId: string }[];
};

export function PlanningCapacityBar({ schoolId, schoolName, capacity, assignment }: { schoolId: string; schoolName?: string; capacity: PlanningCapacity; assignment?: AssignmentVM }) {
  const VISIT: ActivityKind = "SCHOOL_VISIT";
  return (
    <div className="card p-3 space-y-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-extrabold uppercase tracking-wide muted">Planning capacity</span>
        <Quota label="Visits" used={capacity.visitsUsed} allowed={capacity.visitsAllowed} full={!capacity.canPlanVisit} />
        <Quota label="Trainings" used={capacity.trainingsUsed} allowed={capacity.trainingsAllowed} full={!capacity.canPlanTraining} />
        {assignment && (
          <span className={cn("inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-bold border",
            assignment.staffAtLimit ? "bg-rose-50 text-rose-700 border-rose-200" : assignment.staffNearLimit ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-slate-50 text-slate-600 border-slate-200")}>
            Direct support <span className="tabular">{assignment.staffUsed}/{assignment.staffMax}</span>{assignment.staffAtLimit ? " · at limit" : ""}
          </span>
        )}
      </div>

      {assignment?.staffAtLimit && (
        <p className="text-[11px] text-rose-700">You've reached your direct support limit ({assignment.staffMax} schools). New school support should be assigned to a partner.</p>
      )}

      {/* Assignment actions — role + capacity aware (spec §10). */}
      <div className="flex items-center gap-2 flex-wrap">
        {assignment?.showSelf && (
          assignment.selfEnabled
            ? <ScheduleActivityButton schoolId={schoolId} schoolName={schoolName} kind={VISIT} label="Assign to Myself" deliveryType="staff" />
            : <DisabledButton label="Assign to Myself" reason={assignment.selfReason ?? null} />
        )}
        {assignment
          ? (assignment.partnerEnabled
              ? <ScheduleActivityButton schoolId={schoolId} schoolName={schoolName} kind={VISIT} label="Assign to Partner" deliveryType="partner" tone="outline" />
              : <DisabledButton label="Assign to Partner" reason={assignment.partnerReason ?? null} />)
          : (capacity.canPlanVisit
              ? <ScheduleActivityButton schoolId={schoolId} schoolName={schoolName} kind={VISIT} label="Schedule Visit" />
              : <DisabledButton label="Schedule Visit" reason={capacity.visitDisabledReason} />)}
        {assignment?.team.map((t) => (
          <span key={t.staffId} className="inline-flex items-center gap-1 rounded-lg border border-[var(--color-edify-border)] muted px-3 py-1.5 text-[11.5px] font-bold" title="Assign to a supervised CCEO">
            Assign to {t.name}
          </span>
        ))}
      </div>
    </div>
  );
}

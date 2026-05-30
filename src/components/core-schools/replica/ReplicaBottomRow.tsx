"use client";

import {
  AlertOctagon,
  ArrowUpRight,
  CalendarClock,
  Calendar,
  FileText,
  Footprints,
  GraduationCap,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import {
  replicaFollowUpAlerts,
  replicaPackageTaskTotal,
  replicaPackageTasks,
  type ReplicaAlert,
  type ReplicaPackageTask,
} from "@/lib/core-school-replica-mock";
import { cn } from "@/lib/utils";
import { InteractiveTile } from "@/components/tile-filter";

const ALERT_FILTER_ID: Record<string, string> = {
  overdue:   "trainings-overdue",
  due_month: "trainings-due-month",
  behind:    "behind-schedule",
};

const TASK_FILTER_ID: Record<string, string> = {
  visits:        "remaining-visits",
  trainings:     "remaining-trainings",
  verifications: "verifications-pending",
  ssa:           "ssa-not-done",
};

export function ReplicaBottomRow({
  activeFilterId,
  onTileClick,
}: {
  activeFilterId?: string | null;
  onTileClick?: (filterId: string) => void;
}) {
  return (
    <section className="grid grid-cols-12 gap-3 lg:gap-4 items-stretch">
      <div className="col-span-12 lg:col-span-7">
        <FollowUpAlertsCard activeFilterId={activeFilterId} onTileClick={onTileClick} />
      </div>
      <div className="col-span-12 lg:col-span-5">
        <RemainingTasksCard activeFilterId={activeFilterId} onTileClick={onTileClick} />
      </div>
    </section>
  );
}

// ───────────── Follow-Up Alerts ─────────────

const ALERT_ICON: Record<ReplicaAlert["icon"], LucideIcon> = {
  calendarClock: CalendarClock,
  calendar:      Calendar,
  alertOctagon:  AlertOctagon,
};

const ALERT_TONE: Record<ReplicaAlert["tone"], { bg: string; iconBg: string; iconColor: string; border: string }> = {
  rose:   { bg: "bg-rose-50",   iconBg: "bg-rose-100",   iconColor: "text-rose-600",   border: "border-rose-200"   },
  amber:  { bg: "bg-amber-50",  iconBg: "bg-amber-100",  iconColor: "text-amber-600",  border: "border-amber-200"  },
  orange: { bg: "bg-orange-50", iconBg: "bg-orange-100", iconColor: "text-orange-600", border: "border-orange-200" },
};

function FollowUpAlertsCard({
  activeFilterId,
  onTileClick,
}: {
  activeFilterId?: string | null;
  onTileClick?: (filterId: string) => void;
}) {
  return (
    <article className="card p-3.5 flex flex-col">
      <header className="mb-2">
        <h3 className="text-[13.5px] font-extrabold tracking-tight">Follow-Up Alerts</h3>
      </header>

      <ul className="flex flex-col gap-2">
        {replicaFollowUpAlerts.map((a) => {
          const Icon = ALERT_ICON[a.icon];
          const tone = ALERT_TONE[a.tone];
          const filterId = ALERT_FILTER_ID[a.key];
          const active = filterId === activeFilterId;
          return (
            <li key={a.key}>
              <InteractiveTile
                onClick={onTileClick && filterId ? () => onTileClick(filterId) : undefined}
                active={active}
                asStatic={!onTileClick || !filterId}
                className={cn(
                  "w-full rounded-xl border px-3 py-2 flex items-center gap-3",
                  tone.bg,
                  tone.border,
                )}
              >
                <span className={cn("w-8 h-8 rounded-lg grid place-items-center shrink-0", tone.iconBg)}>
                  <Icon size={14} className={tone.iconColor} />
                </span>
                <div className="min-w-0 flex-1 text-left">
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-body-lg font-extrabold tabular text-slate-900">{a.count}</span>
                    <span className="text-[11.5px] font-extrabold text-slate-800 truncate">{a.title}</span>
                  </div>
                  <p className="text-caption muted leading-tight mt-0.5 truncate">{a.body}</p>
                </div>
                <span className="text-caption font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-0.5 shrink-0">
                  View <ArrowUpRight size={10} />
                </span>
              </InteractiveTile>
            </li>
          );
        })}
      </ul>
    </article>
  );
}

// ───────────── Core Package Remaining Tasks ─────────────

const TASK_ICON: Record<ReplicaPackageTask["icon"], LucideIcon> = {
  footprints:    Footprints,
  graduationCap: GraduationCap,
  shieldCheck:   ShieldCheck,
  fileText:      FileText,
};

function RemainingTasksCard({
  activeFilterId,
  onTileClick,
}: {
  activeFilterId?: string | null;
  onTileClick?: (filterId: string) => void;
}) {
  return (
    <article className="card p-3.5 flex flex-col">
      <header className="mb-2">
        <h3 className="text-[13.5px] font-extrabold tracking-tight">Core Package Remaining Tasks</h3>
      </header>

      <ul className="flex flex-col gap-1">
        {replicaPackageTasks.map((t) => {
          const Icon = TASK_ICON[t.icon];
          const filterId = TASK_FILTER_ID[t.key];
          const active = filterId === activeFilterId;
          return (
            <li key={t.key}>
              <InteractiveTile
                onClick={onTileClick && filterId ? () => onTileClick(filterId) : undefined}
                active={active}
                asStatic={!onTileClick || !filterId}
                className={cn(
                  "w-full flex items-center gap-2 py-1.5 px-2 rounded-md border-b border-slate-100 last:border-b-0",
                )}
              >
                <Icon size={13} className="text-slate-400 shrink-0" />
                <span className="text-[11.5px] font-semibold text-slate-700 flex-1 min-w-0 truncate text-left">{t.label}</span>
                <span className="text-[12px] font-extrabold tabular text-slate-900">{t.count}</span>
              </InteractiveTile>
            </li>
          );
        })}
        <li className="flex items-center gap-2 pt-2 mt-1 border-t-2 border-slate-200">
          <span className="text-[12px] font-extrabold text-slate-900 flex-1">Total Tasks Remaining</span>
          <span className="text-body-lg font-extrabold tabular text-emerald-700">{replicaPackageTaskTotal}</span>
        </li>
      </ul>
    </article>
  );
}

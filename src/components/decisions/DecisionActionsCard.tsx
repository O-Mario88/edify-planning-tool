// Decision Actions — Country Director / Program Lead / Assignee surface.
//
// Visibility:
//   • CountryDirector: sees decisions THEY created (any assignee). They
//     get a single queue of open actions to chase.
//   • Assignees (PL / IA / Accountant / SPC / HR / CD): see decisions
//     assigned TO them.
//   • RVP: sees decisions they created (routed to HR or CD only).

import Link from "next/link";
import {
  ClipboardCheck,
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
  Clock,
  type LucideIcon,
} from "lucide-react";
import type { DecisionAction, DecisionStatus } from "@/lib/field-intelligence-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<DecisionStatus, string> = {
  Pending:       "bg-amber-100   text-amber-800",
  "In Progress": "bg-sky-100     text-sky-800",
  Approved:      "bg-emerald-100 text-emerald-700",
  Returned:      "bg-rose-100    text-rose-700",
  Closed:        "bg-slate-100   text-slate-500",
};

const PRIORITY_TONE: Record<DecisionAction["priority"], string> = {
  Critical: "text-rose-700",
  High:     "text-amber-700",
  Medium:   "text-sky-700",
  Low:      "text-slate-600",
};

export function DecisionActionsCard({
  actions, title, subtitle, emptyMessage,
}: {
  actions:      DecisionAction[];
  title:        string;
  subtitle:     string;
  emptyMessage: string;
}) {
  const open     = actions.filter((a) => a.status === "Pending" || a.status === "In Progress" || a.status === "Returned");
  const overdue  = open.filter((a) => new Date(a.deadline) < new Date("2025-05-12"));
  const critical = open.filter((a) => a.priority === "Critical");

  return (
    <section className="card p-3.5 space-y-3">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <ClipboardCheck size={14} className="text-[var(--color-edify-primary)]" />
            {title}
          </h3>
          <p className="text-caption muted mt-0.5">{subtitle}</p>
        </div>
        <Link
          href="/decisions"
          className="text-[11px] font-extrabold text-[var(--color-edify-primary)] inline-flex items-center gap-1 hover:underline"
        >
          Open Queue <ChevronRight size={11} />
        </Link>
      </header>

      <div className="grid grid-cols-3 gap-2">
        <Mini Icon={Clock}          label="Open"     value={open.length}     tone="amber" />
        <Mini Icon={AlertTriangle}  label="Overdue"  value={overdue.length}  tone={overdue.length > 0 ? "rose" : "slate"} />
        <Mini Icon={AlertTriangle}  label="Critical" value={critical.length} tone={critical.length > 0 ? "rose" : "slate"} />
      </div>

      {actions.length === 0 ? (
        <div className="rounded-xl border border-emerald-200 bg-emerald-50/60 p-3 flex items-start gap-2">
          <CheckCircle2 size={12} className="text-emerald-600 mt-0.5" />
          <div className="text-[11.5px] text-emerald-800 leading-snug">{emptyMessage}</div>
        </div>
      ) : (
        <ul className="space-y-1.5">
          {actions.slice(0, 5).map((a) => (
            <li key={a.id} className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 space-y-1">
              <div className="flex items-baseline justify-between gap-2 flex-wrap">
                <div className="min-w-0 flex-1">
                  <div className="text-body font-extrabold tracking-tight">{a.title}</div>
                  <div className="text-caption muted truncate">
                    From <Link href={`/dashboards/director/weekly-debrief-reports/${a.sourceReportId}`} className="font-extrabold text-[var(--color-edify-text)] hover:underline">{a.sourceReportId}</Link> · {a.assigneeName} ({prettyRole(a.assigneeRole)}) · due {a.deadline}
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <span className={cn("text-[10px] font-extrabold uppercase tracking-wide", PRIORITY_TONE[a.priority])}>{a.priority}</span>
                  <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", STATUS_TONE[a.status])}>
                    {a.status}
                  </span>
                </div>
              </div>
            </li>
          ))}
          {actions.length > 5 && (
            <li className="text-caption muted text-center pt-1">+{actions.length - 5} more in the queue</li>
          )}
        </ul>
      )}
    </section>
  );
}

function Mini({ Icon, label, value, tone }: { Icon: LucideIcon; label: string; value: number; tone: "amber" | "rose" | "slate" }) {
  const tones = {
    amber: "bg-amber-50 border-amber-200 text-amber-800",
    rose:  "bg-rose-50  border-rose-200  text-rose-800",
    slate: "bg-slate-50 border-slate-200 text-slate-700",
  } as const;
  return (
    <div className={cn("rounded-xl border px-3 py-2 flex items-center gap-2", tones[tone])}>
      <Icon size={14} className="shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="text-[10px] font-bold uppercase tracking-wide truncate">{label}</div>
        <div className="text-[16px] font-extrabold tabular leading-tight">{value}</div>
      </div>
    </div>
  );
}

export function prettyRole(role: DecisionAction["assigneeRole"]): string {
  return ({
    ProgramLead:               "Program Lead",
    ImpactAssessment:          "Impact Assessment",
    ProgramAccountant:         "Program Accountant",
    SpecialProjectCoordinator: "Special Project Coordinator",
    CountryDirector:           "Country Director",
    HumanResource:             "Human Resource",
    RVP:                       "RVP",
  } as const)[role];
}

"use client";

// PartnerUnscheduledList — every assignment staff has given the
// partner that the partner has not yet placed in a delivery week.
// Action-first: each row's "Schedule" button opens the schedule
// drawer; once scheduled, the row leaves this list and shows up on
// /partner/assignments (My Plan).

import { useMemo, useState } from "react";
import {
  AlertTriangle, Building2, MapPin, FileText, ClipboardList, ArrowRight, Calendar,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { PartnerScheduleDrawer, type ScheduleOutcome } from "@/components/partner/PartnerScheduleDrawer";

type Urgency = "Critical" | "High" | "Medium" | "Low";

type UnscheduledAssignment = {
  id: string;
  schoolName: string;
  district: "Mukono" | "Kayunga";
  subCounty: string;
  parish?: string;
  activityType: string;       // e.g. "Follow-Up Visit"
  activitySub?: string;       // e.g. "Reading fluency check"
  urgency: Urgency;
  ssaArea: string;
  reason: string;             // short why
  expectedOutcome?: string;
  preferredPeriod: string;    // e.g. "This Week", "June Wk 2"
  requiredEvidence: string[]; // short list
  staffMonitor: string;       // CCEO who assigned
  daysSinceAssignment: number;
  paymentEstimateUgx?: number;
};

const ASSIGNMENTS: UnscheduledAssignment[] = [
  {
    id: "ASG-1",
    schoolName: "Maple Grove Primary",
    district: "Kayunga",
    subCounty: "Bbaale",
    parish: "Bbaale",
    activityType: "Coaching Visit",
    activitySub: "Literacy follow-up",
    urgency: "Critical",
    ssaArea: "Teaching & Learning",
    reason: "Critical SSA score (3.6/10) — no follow-up after April training.",
    expectedOutcome: "Teachers apply phonics blocks 2× per week.",
    preferredPeriod: "This Week",
    requiredEvidence: ["Coaching report", "Teacher coached", "Observation notes", "Action agreed"],
    staffMonitor: "Sarah Nanyongo (CCEO)",
    daysSinceAssignment: 5,
    paymentEstimateUgx: 350_000,
  },
  {
    id: "ASG-2",
    schoolName: "Eden Foundation School",
    district: "Mukono",
    subCounty: "Nakifuma",
    parish: "Nakifuma",
    activityType: "Classroom Observation",
    activitySub: "Numeracy lesson observation",
    urgency: "Medium",
    ssaArea: "Numeracy",
    reason: "Mid-quarter check on numeracy teaching strategies.",
    preferredPeriod: "Next week",
    requiredEvidence: ["Observation form", "Lesson focus", "Coaching feedback", "Next action"],
    staffMonitor: "Sarah Nanyongo (CCEO)",
    daysSinceAssignment: 3,
    paymentEstimateUgx: 220_000,
  },
  {
    id: "ASG-3",
    schoolName: "Clover Primary School",
    district: "Kayunga",
    subCounty: "Galiraaya",
    parish: "Galiraaya",
    activityType: "Follow-Up Visit",
    activitySub: "Leadership support",
    urgency: "Medium",
    ssaArea: "Leadership",
    reason: "Verify head-teacher coaching applied after May training.",
    preferredPeriod: "Next week",
    requiredEvidence: ["Visit report", "Staff met", "Next action", "Follow-Up date"],
    staffMonitor: "Sarah Nanyongo (CCEO)",
    daysSinceAssignment: 2,
    paymentEstimateUgx: 270_000,
  },
  {
    id: "ASG-4",
    schoolName: "Galiraaya Primary",
    district: "Kayunga",
    subCounty: "Galiraaya",
    parish: "Galiraaya",
    activityType: "SSA Support Visit",
    activitySub: "Critical · multi-area support",
    urgency: "Critical",
    ssaArea: "Critical · multiple",
    reason: "Lowest-scoring school in the cluster (3.2/10). Diagnostic + recovery plan needed.",
    expectedOutcome: "Recovery plan signed by head-teacher and Edify CCEO.",
    preferredPeriod: "This Week",
    requiredEvidence: ["SSA support report", "Recovery plan", "Headteacher sign-off", "Follow-Up timeline"],
    staffMonitor: "Sarah Nanyongo (CCEO)",
    daysSinceAssignment: 7,
    paymentEstimateUgx: 480_000,
  },
  {
    id: "ASG-5",
    schoolName: "Sunrise Junior School",
    district: "Mukono",
    subCounty: "Mukono Central",
    parish: "Mukono Central",
    activityType: "Follow-Up Visit",
    activitySub: "Reading fluency review",
    urgency: "High",
    ssaArea: "Reading Fluency",
    reason: "Check P3 reading fluency targets set in April.",
    preferredPeriod: "This Week",
    requiredEvidence: ["Visit report", "Reading sample", "Teacher feedback", "Next action"],
    staffMonitor: "Sarah Nanyongo (CCEO)",
    daysSinceAssignment: 4,
    paymentEstimateUgx: 290_000,
  },
  {
    id: "ASG-6",
    schoolName: "Hilltop Basic School",
    district: "Mukono",
    subCounty: "Kireka",
    parish: "Kireka",
    activityType: "In-School Training",
    activitySub: "Phonics for P1-P2",
    urgency: "High",
    ssaArea: "Phonics",
    reason: "SSA score 3.9/10 in Teaching & Learning. First training of the term.",
    preferredPeriod: "Next week",
    requiredEvidence: ["Training report", "Attendance sheet", "Teachers trained", "Partner debrief"],
    staffMonitor: "Sarah Nanyongo (CCEO)",
    daysSinceAssignment: 1,
    paymentEstimateUgx: 410_000,
  },
  {
    id: "ASG-7",
    schoolName: "Kayunga Hill School",
    district: "Kayunga",
    subCounty: "Bbaale",
    parish: "Bbaale",
    activityType: "Coaching Visit",
    activitySub: "Reading comprehension coaching",
    urgency: "Medium",
    ssaArea: "Reading Comprehension",
    reason: "Targeted coaching after low comprehension scores in April assessment.",
    preferredPeriod: "Wk of June 8",
    requiredEvidence: ["Coaching report", "Teacher coached", "Coaching topic", "Action agreed"],
    staffMonitor: "Sarah Nanyongo (CCEO)",
    daysSinceAssignment: 1,
    paymentEstimateUgx: 230_000,
  },
  {
    id: "ASG-8",
    schoolName: "Nsumba Primary",
    district: "Mukono",
    subCounty: "Nsumba",
    parish: "Nsumba",
    activityType: "In-School Training",
    activitySub: "Early numeracy",
    urgency: "Low",
    ssaArea: "Early Numeracy",
    reason: "Routine term-start training — slot when capacity allows.",
    preferredPeriod: "Wk of June 15",
    requiredEvidence: ["Training report", "Attendance sheet", "Topic covered"],
    staffMonitor: "Sarah Nanyongo (CCEO)",
    daysSinceAssignment: 0,
    paymentEstimateUgx: 340_000,
  },
];

const URGENCY_TONE: Record<Urgency, { chip: string; ring: string; dot: string }> = {
  Critical: { chip: "bg-rose-100 text-rose-800",     ring: "ring-rose-300",    dot: "bg-rose-500"    },
  High:     { chip: "bg-rose-50 text-rose-700",      ring: "ring-rose-200",    dot: "bg-rose-500"    },
  Medium:   { chip: "bg-amber-50 text-amber-700",    ring: "ring-amber-200",   dot: "bg-amber-500"   },
  Low:      { chip: "bg-emerald-50 text-emerald-700",ring: "ring-emerald-200", dot: "bg-emerald-500" },
};

const URGENCY_ORDER: Record<Urgency, number> = { Critical: 0, High: 1, Medium: 2, Low: 3 };

function fmtUgx(n: number): string {
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `UGX ${(n / 1_000).toFixed(0)}K`;
  return `UGX ${n}`;
}

export function PartnerUnscheduledList() {
  const [filter, setFilter] = useState<"all" | Urgency>("all");
  const [scheduling, setScheduling] = useState<UnscheduledAssignment | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const rows = useMemo(() => {
    const filtered = filter === "all" ? ASSIGNMENTS : ASSIGNMENTS.filter((a) => a.urgency === filter);
    return [...filtered].sort((a, b) => {
      if (URGENCY_ORDER[a.urgency] !== URGENCY_ORDER[b.urgency]) {
        return URGENCY_ORDER[a.urgency] - URGENCY_ORDER[b.urgency];
      }
      return b.daysSinceAssignment - a.daysSinceAssignment;
    });
  }, [filter]);

  function handleScheduleSubmit(outcome: ScheduleOutcome) {
    if (outcome.kind === "scheduled") {
      setToast(`Scheduled — moved to My Plan. Your CCEO now sees this in their monitoring queue.`);
    } else if (outcome.kind === "request_change") {
      setToast(`Date-change request sent to your CCEO.`);
    } else {
      setToast(`Returned to CCEO for reassignment.`);
    }
    setTimeout(() => setToast(null), 4000);
  }

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2">
            <span className="grid place-items-center h-7 w-7 rounded-md bg-amber-100 text-amber-700">
              <AlertTriangle size={14} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Needs scheduling</h3>
          </div>
          <p className="text-[12px] muted mt-1">
            Assignments your Edify CCEO has given you that don't have a delivery week yet. Schedule them so they appear on your CCEO's monitoring dashboard.
          </p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wide font-bold muted">Pending</div>
          <div className="text-[18px] font-extrabold tabular num-hero text-amber-700 leading-none mt-1">
            {ASSIGNMENTS.length}
          </div>
        </div>
      </header>

      {/* Urgency filter chips */}
      <div className="flex items-center gap-1 flex-wrap mb-3">
        {(["all", "Critical", "High", "Medium", "Low"] as const).map((f) => {
          const isActive = filter === f;
          const count = f === "all" ? ASSIGNMENTS.length : ASSIGNMENTS.filter((a) => a.urgency === f).length;
          return (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f as "all" | Urgency)}
              className={cn(
                "inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold transition-colors",
                isActive
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
              )}
            >
              {f === "all" ? "All" : f}
              <span className={cn(
                "inline-flex items-center justify-center min-w-[16px] h-[14px] px-1 rounded-md text-[9px] font-extrabold",
                isActive ? "bg-[var(--color-edify-primary)] text-white" : "bg-slate-100 text-slate-700",
              )}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      {/* Assignment list */}
      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {rows.map((a) => <AssignmentRow key={a.id} a={a} onSchedule={() => setScheduling(a)} />)}
      </ul>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[12px] muted">
        Showing <span className="font-semibold text-[var(--color-edify-text)]">{rows.length}</span>{" "}
        of <span className="font-semibold text-[var(--color-edify-text)]">{ASSIGNMENTS.length}</span> unscheduled assignments
      </div>

      <PartnerScheduleDrawer
        open={!!scheduling}
        activityLabel={scheduling ? `${scheduling.activityType}${scheduling.activitySub ? ` — ${scheduling.activitySub}` : ""}` : ""}
        schoolName={scheduling?.schoolName ?? ""}
        urgency={scheduling?.urgency ?? "Medium"}
        onClose={() => setScheduling(null)}
        onSubmit={handleScheduleSubmit}
      />

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-body font-semibold px-4 py-3 max-w-[400px]">
          {toast}
        </div>
      )}
    </section>
  );
}

function AssignmentRow({
  a, onSchedule,
}: {
  a: UnscheduledAssignment;
  onSchedule: () => void;
}) {
  const tone = URGENCY_TONE[a.urgency];
  const isOverdue = a.daysSinceAssignment >= 5;

  return (
    <li className="py-3 grid grid-cols-12 gap-3 items-start">
      {/* Urgency indicator */}
      <div className="col-span-1 flex justify-center pt-1">
        <span className={cn("grid place-items-center h-8 w-8 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] ring-2", tone.ring)}>
          <Building2 size={13} />
        </span>
      </div>

      {/* Main column — school + activity + details */}
      <div className="col-span-12 md:col-span-7 min-w-0 -mt-0.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={cn("inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide", tone.chip)}>
            <span className={cn("w-1.5 h-1.5 rounded-full", tone.dot)} />
            {a.urgency}
          </span>
          <span className="text-caption uppercase tracking-wide font-bold muted">
            {a.activityType}
          </span>
          {a.activitySub && (
            <span className="text-caption muted">· {a.activitySub}</span>
          )}
        </div>
        <h4 className="text-[13.5px] font-extrabold tracking-tight mt-1">{a.schoolName}</h4>
        <p className="text-caption muted leading-tight mt-0.5 inline-flex items-center gap-1.5 flex-wrap">
          <MapPin size={10} className="text-[var(--color-edify-primary)]" />
          {a.district} District · {a.subCounty}
          {a.parish && <> · {a.parish}</>}
        </p>
        <p className="text-[12px] text-[var(--color-edify-text)] leading-snug mt-2">
          <span className="font-extrabold">Reason:</span> {a.reason}
        </p>
        {a.expectedOutcome && (
          <p className="text-[11.5px] muted leading-snug mt-1">
            <span className="font-extrabold text-[var(--color-edify-text)]">Expected outcome:</span> {a.expectedOutcome}
          </p>
        )}
        <div className="flex items-center gap-3 mt-2 flex-wrap text-caption muted">
          <span className="inline-flex items-center gap-1">
            <ClipboardList size={10} />
            <span className="font-bold text-[var(--color-edify-text)]">SSA area:</span> {a.ssaArea}
          </span>
          <span className="inline-flex items-center gap-1">
            <Calendar size={10} />
            <span className="font-bold text-[var(--color-edify-text)]">Preferred:</span> {a.preferredPeriod}
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="font-bold text-[var(--color-edify-text)]">Monitor:</span> {a.staffMonitor}
          </span>
        </div>
      </div>

      {/* Right column — required evidence + Schedule CTA + meta */}
      <div className="col-span-12 md:col-span-4 flex flex-col items-stretch gap-2">
        <div className="rounded-lg border border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/30 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider font-bold muted inline-flex items-center gap-1">
            <FileText size={10} /> Evidence you'll need
          </div>
          <ul className="mt-1 flex flex-wrap gap-1">
            {a.requiredEvidence.map((e) => (
              <li
                key={e}
                className="inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-semibold bg-white border border-[var(--color-edify-border)] text-[var(--color-edify-text)]"
              >
                {e}
              </li>
            ))}
          </ul>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className={cn(
            "text-caption font-bold",
            isOverdue ? "text-rose-700" : "muted",
          )}>
            {a.daysSinceAssignment === 0
              ? "Assigned today"
              : `Assigned ${a.daysSinceAssignment} day${a.daysSinceAssignment === 1 ? "" : "s"} ago`}
            {isOverdue ? " · CCEO will be notified" : ""}
          </span>
          {a.paymentEstimateUgx != null && (
            <span className="text-caption font-bold text-[var(--color-edify-text)] tabular">
              {fmtUgx(a.paymentEstimateUgx)}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={onSchedule}
          className="inline-flex items-center justify-center gap-1.5 h-9 px-3 rounded-md bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold hover:bg-[var(--color-edify-dark)]"
        >
          Schedule activity <ArrowRight size={11} />
        </button>
      </div>
    </li>
  );
}

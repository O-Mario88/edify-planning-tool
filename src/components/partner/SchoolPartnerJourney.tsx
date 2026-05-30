// SchoolPartnerJourney — the school-side timeline of a partner
// support thread. Closes the workflow loop from the spec: every
// partner activity must update the school journey so the work is
// understood as school improvement, not just partner payment.
//
// Renders as a vertical timeline with one node per workflow step,
// each showing what happened, when, and who acted. Future steps are
// shown muted so the reader sees the full arc from need to closure.

import {
  AlertOctagon, Handshake, Calendar, ClipboardCheck, Upload,
  ShieldCheck, Wallet, CheckCircle2, RefreshCcw, type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type JourneyStepStatus = "done" | "active" | "future";

export type JourneyStep = {
  key: string;
  Icon: LucideIcon;
  title: string;
  detail: string;
  whenLabel?: string;
  byLabel?: string;
  status: JourneyStepStatus;
};

export type SchoolJourneyProps = {
  schoolName: string;
  ssaArea: string;
  ssaScore: number;
  partner: string;
  steps: JourneyStep[];
  /// Where the journey resumes — typically a reassessment date.
  nextActionLabel: string;
  nextActionDate: string;
};

export function SchoolPartnerJourney({
  schoolName,
  ssaArea,
  ssaScore,
  partner,
  steps,
  nextActionLabel,
  nextActionDate,
}: SchoolJourneyProps) {
  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-4">
        <div>
          <div className="text-caption uppercase tracking-wider font-bold muted">School Support Journey</div>
          <h3 className="text-[16px] font-extrabold tracking-tight mt-1">{schoolName}</h3>
          <p className="text-[12px] muted mt-1">
            <span className="font-bold text-[var(--color-edify-text)]">{ssaArea}</span>{" "}
            · current SSA score{" "}
            <span className="font-bold text-rose-700">{ssaScore}/10</span>{" "}
            · partner{" "}
            <span className="font-bold text-[var(--color-edify-text)]">{partner}</span>
          </p>
        </div>
      </header>

      <ol className="relative">
        {/* Vertical rail */}
        <div
          aria-hidden
          className="absolute left-[15px] top-2 bottom-2 w-px bg-[var(--color-edify-divider)]"
        />
        {steps.map((step) => (
          <Step key={step.key} step={step} />
        ))}
      </ol>

      {/* Next action — closes the loop back into the planning cycle. */}
      <footer className="mt-4 rounded-xl border border-[var(--color-edify-primary)]/30 bg-[var(--color-edify-soft)]/40 px-3.5 py-3 flex items-center gap-3">
        <span className="grid place-items-center h-9 w-9 rounded-xl bg-[var(--color-edify-primary)] text-white shrink-0">
          <RefreshCcw size={14} />
        </span>
        <div className="flex-1 min-w-0">
          <div className="text-[11px] uppercase tracking-wider font-bold text-[var(--color-edify-primary)]">
            Next school action
          </div>
          <div className="text-[13px] font-extrabold tracking-tight">{nextActionLabel}</div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wide font-bold muted">Due</div>
          <div className="text-body font-extrabold tabular text-[var(--color-edify-text)]">{nextActionDate}</div>
        </div>
      </footer>
    </section>
  );
}

function Step({ step }: { step: JourneyStep }) {
  const Icon = step.Icon;
  const colors =
    step.status === "done"
      ? { node: "bg-emerald-500 text-white border-emerald-500", title: "text-[var(--color-edify-text)]", detail: "text-[var(--color-edify-muted)]" }
      : step.status === "active"
        ? { node: "bg-white text-[var(--color-edify-primary)] border-[var(--color-edify-primary)] ring-4 ring-[var(--color-edify-primary)]/20", title: "text-[var(--color-edify-text)]", detail: "text-[var(--color-edify-muted)]" }
        : { node: "bg-white text-[var(--color-edify-muted)] border-[var(--color-edify-divider)]", title: "muted", detail: "muted" };

  return (
    <li className="relative pl-10 pb-4 last:pb-0">
      <span className={cn(
        "absolute left-0 top-0 grid place-items-center h-8 w-8 rounded-full border-2 z-10",
        colors.node,
      )}>
        <Icon size={13} />
      </span>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className={cn("text-body font-extrabold tracking-tight leading-tight", colors.title)}>
            {step.title}
          </div>
          <div className={cn("text-[11.5px] mt-0.5 leading-snug", colors.detail)}>
            {step.detail}
          </div>
          {step.byLabel && (
            <div className="text-caption muted mt-1">By {step.byLabel}</div>
          )}
        </div>
        {step.whenLabel && (
          <span className="text-caption muted font-semibold whitespace-nowrap shrink-0 mt-0.5">
            {step.whenLabel}
          </span>
        )}
      </div>
    </li>
  );
}

// ────────── Sample data + factory ──────────
//
// In production the steps are projected server-side from the
// partner_activities + partner_evidence + payment_requests tables.
// This factory keeps the demo deterministic.

export function sampleJourneyForHope(): SchoolJourneyProps {
  return {
    schoolName: "Hope Primary School",
    ssaArea: "Teaching & Learning",
    ssaScore: 4,
    partner: "Bright Future Education Partners",
    steps: [
      {
        key: "need",
        Icon: AlertOctagon,
        title: "School need identified",
        detail: "Teaching & Learning score 4/10 — flagged in last SSA round.",
        whenLabel: "Apr 8, 2026",
        byLabel: "Paul Chinyama (CCEO)",
        status: "done",
      },
      {
        key: "assigned",
        Icon: Handshake,
        title: "Partner assigned",
        detail: "Bright Future Education Partners — Follow-Up coaching visit.",
        whenLabel: "Apr 22, 2026",
        byLabel: "Paul Chinyama (CCEO)",
        status: "done",
      },
      {
        key: "scheduled",
        Icon: Calendar,
        title: "Scheduled by partner",
        detail: "Week 3 · May 13, 2026 · Facilitator: Daniel Mwangi (BFEP).",
        whenLabel: "May 4, 2026",
        byLabel: "Daniel Mwangi (BFEP)",
        status: "done",
      },
      {
        key: "delivered",
        Icon: ClipboardCheck,
        title: "Activity delivered",
        detail: "Visited Hope Primary · met 2 P3 teachers · 90 minutes coaching.",
        whenLabel: "May 13, 2026",
        byLabel: "Daniel Mwangi (BFEP)",
        status: "done",
      },
      {
        key: "evidence",
        Icon: Upload,
        title: "Evidence submitted",
        detail: "Visit report, attendance, teacher feedback uploaded.",
        whenLabel: "May 13, 2026",
        byLabel: "Daniel Mwangi (BFEP)",
        status: "done",
      },
      {
        key: "confirmed",
        Icon: ShieldCheck,
        title: "Awaiting CCEO confirmation",
        detail: "CCEO must review the evidence and confirm work was completed properly.",
        whenLabel: "Today",
        byLabel: "Paul Chinyama (CCEO)",
        status: "active",
      },
      {
        key: "pl",
        Icon: ShieldCheck,
        title: "PL approval",
        detail: "After CCEO confirms, payment routes to Program Lead for approval.",
        status: "future",
      },
      {
        key: "paid",
        Icon: Wallet,
        title: "Paid by accountant",
        detail: "Payment cleared once PL approves the partner request.",
        status: "future",
      },
      {
        key: "closed",
        Icon: CheckCircle2,
        title: "Activity closed",
        detail: "School journey updates with the improvement signal.",
        status: "future",
      },
    ],
    nextActionLabel: "Reassess Teaching & Learning score after partner support window closes.",
    nextActionDate: "Jul 12, 2026",
  };
}

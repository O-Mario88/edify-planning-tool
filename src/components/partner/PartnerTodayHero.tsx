// PartnerTodayHero — calm, single-question header.
//
// Answers the partner's first question in 3 seconds:
//   "What must my team do today?"
//
// Below the headline a natural-language body summarises the day,
// then a 5-card summary strip turns the numbers into clear glances.

import { ClipboardCheck, Upload, RotateCcw, ShieldCheck, AlertOctagon, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type TodaySummary = {
  activitiesToday: number;
  evidenceRequired: number;
  correctionsDue: number;
  awaitingConfirmation: number;
  overdue: number;
};

export function PartnerTodayHero({
  partnerName,
  edifyFocal,
  dateLabel,
  summary,
}: {
  partnerName: string;
  edifyFocal: string;
  dateLabel: string;
  summary: TodaySummary;
}) {
  const schoolsCount = 3; // mock — derived from partner-today-mock distinct school count
  const evidenceNote = summary.evidenceRequired > 0
    ? `${summary.evidenceRequired} ${summary.evidenceRequired === 1 ? "activity" : "activities"} need evidence before payment can move forward.`
    : "Evidence is up to date — nothing blocking payment today.";
  const correctionNote = summary.correctionsDue > 0
    ? ` ${summary.correctionsDue} ${summary.correctionsDue === 1 ? "correction is" : "corrections are"} due today.`
    : "";

  return (
    <>
      {/* Headline + people line */}
      <section className="card p-3.5 sm:p-6">
        <p className="text-caption uppercase tracking-[0.12em] font-extrabold text-[var(--color-edify-muted)]">
          Today
        </p>
        <h1
          className="font-extrabold tracking-tight leading-tight mt-1 text-[var(--color-edify-text)]"
          style={{ fontSize: "clamp(22px, 2.6vw, 28px)" }}
        >
          Today's Partner Work
        </h1>
        <p className="text-body sm:text-[13px] muted mt-1.5">{dateLabel}</p>
        <p className="text-[13px] sm:text-body-lg text-[var(--color-edify-text)] leading-relaxed mt-3 max-w-[68ch]">
          You have <span className="font-extrabold">{summary.activitiesToday} {summary.activitiesToday === 1 ? "activity" : "activities"}</span>{" "}
          scheduled today across <span className="font-extrabold">{schoolsCount} schools</span>.{" "}
          {evidenceNote}{correctionNote}
        </p>
        <div className="mt-4 flex items-center gap-4 flex-wrap text-[11.5px]">
          <span className="muted">
            Partner: <span className="font-extrabold text-[var(--color-edify-text)]">{partnerName}</span>
          </span>
          <span className="text-[var(--color-edify-divider)]">·</span>
          <span className="muted">
            Edify focal: <span className="font-extrabold text-[var(--color-edify-text)]">{edifyFocal}</span>
          </span>
        </div>
      </section>

      {/* 5-card summary strip */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <SummaryCard stagger="stagger-1" label="Activities Today"        value={summary.activitiesToday}      Icon={ClipboardCheck} tone="primary" />
        <SummaryCard stagger="stagger-2" label="Evidence Required"      value={summary.evidenceRequired}     Icon={Upload}         tone={summary.evidenceRequired > 0 ? "danger" : "good"} />
        <SummaryCard stagger="stagger-3" label="Corrections Due"        value={summary.correctionsDue}       Icon={RotateCcw}      tone={summary.correctionsDue > 0 ? "warn" : "good"} />
        <SummaryCard stagger="stagger-4" label="Awaiting Confirmation"  value={summary.awaitingConfirmation} Icon={ShieldCheck}    tone="info" />
        <SummaryCard stagger="stagger-5" label="Overdue"                value={summary.overdue}              Icon={AlertOctagon}   tone={summary.overdue > 0 ? "danger" : "good"} />
      </div>
    </>
  );
}

const TONE: Record<"primary" | "good" | "warn" | "danger" | "info", { bg: string; text: string; ring: string }> = {
  primary: { bg: "bg-[var(--color-edify-soft)]", text: "text-[var(--color-edify-primary)]", ring: "ring-[var(--color-edify-divider)]" },
  good:    { bg: "bg-emerald-50",                text: "text-emerald-700",                  ring: "ring-emerald-100" },
  warn:    { bg: "bg-amber-50",                  text: "text-amber-700",                    ring: "ring-amber-100"   },
  danger:  { bg: "bg-rose-50",                   text: "text-rose-700",                     ring: "ring-rose-100"    },
  info:    { bg: "bg-blue-50",                   text: "text-blue-700",                     ring: "ring-blue-100"    },
};

// Tone → glow class so the hero number on each tile picks up a
// subtle coloured halo that matches its semantic.
const TONE_GLOW: Record<keyof typeof TONE, string> = {
  primary: "glow-slate",
  warn:    "glow-amber",
  good:    "glow-emerald",
  danger:  "glow-rose",
  info:    "glow-slate",
};

function SummaryCard({
  label, value, Icon, tone, stagger,
}: {
  label: string;
  value: number;
  Icon: LucideIcon;
  tone: keyof typeof TONE;
  stagger?: string;
}) {
  const t = TONE[tone];
  return (
    <div className={cn(
      "card-elevated card-lift pressable rounded-2xl p-3.5 md:p-4 tile-in",
      stagger,
    )}>
      <div className="flex items-start justify-between gap-2">
        {/* line-clamp-2 (not truncate) so "Awaiting confirmation"
            and "Evidence required" don't lose characters on phones. */}
        <span className="text-[10px] uppercase tracking-[0.08em] font-extrabold text-[var(--color-edify-muted)] leading-tight line-clamp-2 min-h-[24px]">
          {label}
        </span>
        <span className={cn("grid place-items-center h-7 w-7 rounded-md ring-1 shrink-0", t.bg, t.text, t.ring)}>
          <Icon size={13} />
        </span>
      </div>
      <div className={cn(
        "text-[26px] md:text-[28px] font-extrabold num-hero leading-none mt-2",
        TONE_GLOW[tone],
        value === 0 ? "text-[var(--color-edify-muted)]" : "text-[var(--color-edify-text)]",
      )}>
        {value}
      </div>
    </div>
  );
}

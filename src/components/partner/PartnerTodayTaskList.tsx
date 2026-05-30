"use client";

// PartnerTodayTaskList — the heart of the Today page, list-style.
//
// Each task is a single compact row showing the essentials —
// urgency, activity type, school, time, status, evidence %, primary
// action. Click anywhere on the row to expand inline and see the
// full detail (purpose, SSA area, facilitator, evidence checklist,
// next step, secondary CTA). One row open at a time.

import { useState } from "react";
import Link from "next/link";
import {
  Building2, Clock, MapPin, CheckCircle2, AlertTriangle, ArrowRight, RotateCcw, ChevronDown, ChevronUp,
  GraduationCap, Footprints, Truck, ClipboardCheck, BookOpen, Heart, Users, Upload, type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  partnerTodayTasks,
  sortTodayTasks,
  TASK_TYPE_LABEL,
  STATUS_LABEL,
  type PartnerTodayTask,
} from "@/lib/partner/partner-today-mock";

const URGENCY_TONE: Record<PartnerTodayTask["urgency"], { chip: string; ring: string; dot: string; text: string }> = {
  critical: { chip: "bg-rose-50 text-rose-700",       ring: "ring-rose-200",    dot: "bg-rose-500",    text: "text-rose-700"    },
  high:     { chip: "bg-rose-50 text-rose-700",       ring: "ring-rose-100",    dot: "bg-rose-500",    text: "text-rose-700"    },
  medium:   { chip: "bg-amber-50 text-amber-700",     ring: "ring-amber-100",   dot: "bg-amber-500",   text: "text-amber-700"   },
  low:      { chip: "bg-emerald-50 text-emerald-700", ring: "ring-emerald-100", dot: "bg-emerald-500", text: "text-emerald-700" },
};

// Maps each status to a canonical .pill-* tone so every status pill
// across the partner pages reads from the same colour table. Edits to
// the system pill in globals.css now propagate here automatically.
const STATUS_TONE: Record<PartnerTodayTask["status"], string> = {
  scheduled:                  "pill pill-slate",
  ready_to_start:             "pill pill-info",
  in_progress:                "pill pill-info",
  report_needed:              "pill pill-warn",
  evidence_needed:            "pill pill-warn",
  submitted:                  "pill pill-info",
  awaiting_cceo_confirmation: "pill pill-info",
  returned_for_correction:    "pill pill-warn",
  completed_today:            "pill pill-success",
  overdue:                    "pill pill-danger",
};

const TASK_ICON: Record<PartnerTodayTask["taskType"], LucideIcon> = {
  training:              GraduationCap,
  in_school_training:    GraduationCap,
  follow_up_visit:       Footprints,
  coaching_visit:        Heart,
  classroom_observation: ClipboardCheck,
  ssa_support_visit:     ClipboardCheck,
  resource_delivery:     Truck,
  joint_visit:           Users,
  reflection_debrief:    BookOpen,
  evidence_upload:       Upload,
  correction:            RotateCcw,
};

export function PartnerTodayTaskList() {
  const [tasks, setTasks] = useState<PartnerTodayTask[]>(sortTodayTasks(partnerTodayTasks));
  const [openId, setOpenId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  function handlePrimary(task: PartnerTodayTask) {
    setTasks((prev) =>
      prev.map((t) => {
        if (t.id !== task.id) return t;
        if (task.status === "ready_to_start" || task.status === "scheduled") {
          return { ...t, status: "in_progress" };
        }
        if (task.status === "in_progress") return { ...t, status: "submitted" };
        return t;
      }),
    );
    setToast(`${task.schoolName ?? "Activity"}: ${task.primaryActionLabel.toLowerCase()} recorded.`);
    setTimeout(() => setToast(null), 3000);
  }

  return (
    <section className="card rounded-2xl p-0 overflow-hidden">
      <header className="flex items-center justify-between gap-3 px-4 pt-4 pb-3 border-b border-[var(--color-edify-divider)]">
        <div>
          <h2 className="text-[15px] font-extrabold tracking-tight">Priority to-do list</h2>
          <p className="text-[12px] muted mt-0.5">
            Sorted by urgency, time, and what's blocking payment. Click any row for the full detail.
          </p>
        </div>
        <span className="text-caption uppercase tracking-wide font-bold text-[var(--color-edify-muted)] whitespace-nowrap">
          {tasks.length} task{tasks.length === 1 ? "" : "s"}
        </span>
      </header>

      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {tasks.map((t, i) => (
          <TaskRow
            key={t.id}
            task={t}
            index={i + 1}
            open={openId === t.id}
            onToggle={() => setOpenId((cur) => (cur === t.id ? null : t.id))}
            onPrimary={handlePrimary}
          />
        ))}
      </ul>

      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-body font-semibold px-4 py-3 max-w-[400px]">
          {toast}
        </div>
      )}
    </section>
  );
}

function TaskRow({
  task: t, index, open, onToggle, onPrimary,
}: {
  task: PartnerTodayTask;
  index: number;
  open: boolean;
  onToggle: () => void;
  onPrimary: (task: PartnerTodayTask) => void;
}) {
  const tone = URGENCY_TONE[t.urgency];
  const Icon = TASK_ICON[t.taskType];
  const isCorrection = t.taskType === "correction";
  const uploaded = t.evidenceChecklist.filter((it) => it.status === "uploaded" || it.status === "accepted").length;
  const total = t.evidenceChecklist.length;
  const pct = total === 0 ? 0 : Math.round((uploaded / total) * 100);

  return (
    <li className={cn(isCorrection && "bg-amber-50/30")}>
      {/* Collapsed row — clickable wrapper, NOT a <button>, so the
          inline CTA <button> below is valid HTML. Keyboard-accessible
          via role + onKeyDown. */}
      {/* Phone (<md): two-row layout — top row has identity + chevron,
          bottom row has the status pill + CTA. The original single-row
          design crushes the school name on 375px viewports (340+ px of
          fixed-width elements leaves ~35px for content). Splitting the
          row keeps every tap target full-size. */}
      <div
        role="button"
        tabIndex={0}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(); }
        }}
        className="w-full cursor-pointer text-left px-4 py-3 hover:bg-[var(--color-edify-soft)]/30 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-edify-primary)]/30"
      >
        {/* Top row — identity */}
        <div className="flex items-start gap-3">
          {/* Step index */}
          <span className="text-[10px] font-extrabold uppercase tracking-wide text-[var(--color-edify-muted)] w-6 shrink-0 text-center pt-2">
            #{index}
          </span>

          {/* Urgency dot + activity icon */}
          <div className="flex items-center gap-2 shrink-0 pt-1">
            <span className={cn("w-2 h-2 rounded-full", tone.dot)} aria-label={`${t.urgency} priority`} />
            <span className={cn("grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] ring-1", tone.ring)}>
              <Icon size={13} />
            </span>
          </div>

          {/* School + activity type (primary) */}
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-body font-extrabold tracking-tight truncate text-[var(--color-edify-text)]">
                {t.schoolName ?? TASK_TYPE_LABEL[t.taskType]}
              </span>
              <span className="text-caption uppercase tracking-wide font-bold muted whitespace-nowrap">
                · {TASK_TYPE_LABEL[t.taskType]}
              </span>
            </div>
            <div className="text-caption muted leading-tight mt-0.5 inline-flex items-center gap-1.5 flex-wrap">
              {t.district && (
                <span className="inline-flex items-center gap-1">
                  <MapPin size={9} className="text-[var(--color-edify-primary)]" />
                  {t.district}
                </span>
              )}
              {t.subCounty && <><span>·</span><span>{t.subCounty}</span></>}
              {t.scheduledTimeLabel && (
                <>
                  <span>·</span>
                  <span className="inline-flex items-center gap-1">
                    <Clock size={9} />
                    {t.scheduledTimeLabel}
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Evidence % — tablet+ only */}
          <div className="hidden md:flex flex-col items-end gap-0.5 shrink-0 w-[60px]">
            <span className={cn(
              "text-[12px] font-extrabold tabular",
              pct >= 80 ? "text-emerald-700" : pct >= 50 ? "text-amber-700" : pct === 0 ? "muted" : "text-rose-700",
            )}>
              {total === 0 ? "—" : `${pct}%`}
            </span>
            <span className="text-[9px] uppercase tracking-wide muted">Evidence</span>
          </div>

          {/* Status pill — desktop-only here; on phone it moves to the
              action row below so it isn't squeezed. */}
          <span className={cn(
            STATUS_TONE[t.status],
            "!hidden md:!inline-flex shrink-0",
          )}>
            {STATUS_LABEL[t.status]}
          </span>

          {/* Primary CTA — desktop-only here; on phone it moves to the
              action row below. */}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onPrimary(t); }}
            className={cn(
              "hidden md:inline-flex items-center justify-center gap-1 h-8 px-3 rounded-md text-[11.5px] font-extrabold transition-colors whitespace-nowrap shrink-0",
              isCorrection
                ? "bg-amber-500 text-white hover:bg-amber-600"
                : "bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]",
            )}
          >
            {t.primaryActionLabel}
            <ArrowRight size={11} />
          </button>

          {/* Expand chevron */}
          <span className="text-[var(--color-edify-muted)] shrink-0 pt-1">
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
        </div>

        {/* Phone action row — status pill on the left, full-width CTA
            on the right. Sized for thumbs (h-9 button, comfortable
            tap target). */}
        <div className="md:hidden flex items-center gap-2 mt-3 pl-[36px]">
          <span className={cn("inline-flex shrink-0", STATUS_TONE[t.status])}>
            {STATUS_LABEL[t.status]}
          </span>
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onPrimary(t); }}
            className={cn(
              "inline-flex items-center justify-center gap-1 h-9 px-3.5 rounded-lg text-[12px] font-extrabold whitespace-nowrap shrink-0 ml-auto pressable shadow-[0_4px_12px_-4px_rgba(15,23,32,0.25)]",
              isCorrection
                ? "bg-gradient-to-b from-amber-500 to-amber-600 text-white"
                : "bg-gradient-to-b from-[var(--color-edify-primary)] to-[var(--color-edify-dark)] text-white",
            )}
          >
            {t.primaryActionLabel}
            <ArrowRight size={12} strokeWidth={2.5} />
          </button>
        </div>
      </div>

      {/* Expanded detail */}
      {open && (
        <div className="px-4 pb-4 -mt-1 grid grid-cols-1 md:grid-cols-12 gap-3 bg-[var(--color-edify-soft)]/40 border-t border-[var(--color-edify-divider)]/60">
          <div className="md:col-span-7 space-y-2 pt-3">
            <Detail Icon={AlertTriangle} primary={<><span className="font-extrabold">Purpose:</span> {t.purpose}</>} tone="warn" />
            {t.ssaAreaAddressed && (
              <Detail Icon={Building2} primary={<><span className="font-extrabold">SSA area:</span> {t.ssaAreaAddressed}</>} />
            )}
            {t.parish && (
              <Detail Icon={MapPin} primary={<><span className="font-extrabold">Parish:</span> {t.parish}</>} tone="muted" />
            )}
            {t.facilitator && (
              <Detail Icon={CheckCircle2} primary={<><span className="font-extrabold">Facilitator:</span> {t.facilitator}</>} />
            )}
            {t.staffMonitorName && (
              <Detail Icon={CheckCircle2} primary={<><span className="font-extrabold">CCEO monitor:</span> {t.staffMonitorName}</>} tone="muted" />
            )}
            {isCorrection && t.reviewerComment && (
              <Detail Icon={RotateCcw} primary={<><span className="font-extrabold">What to fix:</span> {t.reviewerComment}</>} tone="warn" />
            )}
            {isCorrection && t.returnedBy && (
              <Detail Icon={CheckCircle2} primary={<><span className="font-extrabold">Returned by:</span> {t.returnedBy}</>} tone="muted" />
            )}

            {/* Next-step prompt */}
            <div className="mt-3 rounded-lg bg-white border border-[var(--color-edify-divider)] px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider font-bold muted">Next step</div>
              <p className="text-[12px] font-extrabold text-[var(--color-edify-text)] mt-0.5">
                {nextStepFor(t)}
              </p>
            </div>

            {t.secondaryActionLabel && (
              <div className="pt-1">
                <Link
                  href={t.href}
                  className="inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
                >
                  {t.secondaryActionLabel}
                </Link>
              </div>
            )}
          </div>

          {/* Evidence checklist panel */}
          <div className="md:col-span-5 pt-3">
            <EvidencePanel task={t} pct={pct} />
          </div>
        </div>
      )}
    </li>
  );
}

function Detail({
  Icon, primary, tone,
}: {
  Icon: LucideIcon;
  primary: React.ReactNode;
  tone?: "warn" | "muted";
}) {
  const iconCls = tone === "warn" ? "text-rose-500" : tone === "muted" ? "text-[var(--color-edify-muted)]" : "text-[var(--color-edify-primary)]";
  const textCls = tone === "warn" ? "text-rose-700" : tone === "muted" ? "muted" : "text-[var(--color-edify-text)]";
  return (
    <div className="flex items-start gap-2">
      <span className={cn("mt-0.5 shrink-0", iconCls)}>
        <Icon size={12} />
      </span>
      <div className={cn("text-[12px] leading-snug", textCls)}>{primary}</div>
    </div>
  );
}

function EvidencePanel({ task: t, pct }: { task: PartnerTodayTask; pct: number }) {
  return (
    <div className="rounded-lg border border-[var(--color-edify-divider)] bg-white p-3">
      <div className="flex items-center justify-between gap-2 mb-1.5">
        <span className="text-caption uppercase tracking-wider font-bold muted">Evidence checklist</span>
        <span className={cn(
          "text-[11px] font-extrabold tabular",
          pct >= 80 ? "text-emerald-700" : pct >= 50 ? "text-amber-700" : "text-rose-700",
        )}>
          {pct}%
        </span>
      </div>
      <ul className="space-y-1">
        {t.evidenceChecklist.map((it, i) => {
          const present = it.status === "uploaded" || it.status === "accepted";
          return (
            <li key={i} className="flex items-center gap-2">
              {present ? (
                <CheckCircle2 size={12} className="text-emerald-600 shrink-0" />
              ) : (
                <span className={cn(
                  "h-3 w-3 rounded-full border-2 shrink-0",
                  it.critical ? "border-rose-400" : "border-[var(--color-edify-border)]",
                )} />
              )}
              <span className={cn(
                "text-[11px] truncate",
                present ? "text-[var(--color-edify-text)]" : "muted",
              )}>
                {it.label}
              </span>
              {it.critical && !present && (
                <span className="ml-auto text-[9px] font-extrabold text-rose-700 uppercase tracking-wide shrink-0">Crit</span>
              )}
            </li>
          );
        })}
      </ul>
      {t.missingEvidenceCount > 0 && (
        <button
          type="button"
          className="mt-2 w-full inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
        >
          Upload missing evidence <ArrowRight size={11} />
        </button>
      )}
    </div>
  );
}

function nextStepFor(t: PartnerTodayTask): string {
  if (t.taskType === "correction") return "Correct the submission before end of day.";
  switch (t.status) {
    case "ready_to_start":
    case "scheduled":              return "Start activity when you arrive at the school.";
    case "in_progress":            return "Complete the activity and submit your report.";
    case "report_needed":          return "Submit the activity report.";
    case "evidence_needed":        return "Upload the missing evidence before this can move to CCEO confirmation.";
    case "submitted":
    case "awaiting_cceo_confirmation": return "Edify staff will review and confirm. No partner action needed.";
    case "returned_for_correction":return "See the comment and correct the submission.";
    case "completed_today":        return "Done — nothing else needed from you today.";
    case "overdue":                return "Deliver as soon as possible or flag delayed with a reason.";
    default:                       return "Open the activity to see what's needed.";
  }
}

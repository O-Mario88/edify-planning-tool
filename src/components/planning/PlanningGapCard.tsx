// Planning Gap Card — the visual atom of the SSA-gated, gap-based
// Planning Tool. One card per PlanningGap; SSA gate decides what
// actions render. Once an action fires and the gap is resolved
// upstream, the card disappears from the planning list (handled by
// the parent page).

"use client";

import type {
  PlanningGap,
  PlanningActionKind,
  ActionState,
} from "@/lib/planning/gap-types";
import { actionStateFor } from "@/lib/planning/gap-types";
import { cn } from "@/lib/utils";
import {
  Lock,
  AlertOctagon,
  Sparkles,
  CheckCircle2,
  Calendar,
  Users,
  Building2,
  ExternalLink,
  ChevronRight,
} from "lucide-react";

// ─── Types ─────────────────────────────────────────────────────────

export type PlanningGapCardProps = {
  gap: PlanningGap;
  onAction?: (kind: PlanningActionKind, gap: PlanningGap) => void;
};

// ─── Action label / icon table ─────────────────────────────────────
//
// Single source-of-truth for the user-facing string + leading icon
// for every PlanningActionKind. Kept colocated with the card so the
// label and the rendered button can't drift apart.

const ACTION_LABEL: Record<PlanningActionKind, string> = {
  COMPLETE_SSA: "Complete SSA",
  SCHEDULE_SIT: "Schedule SIT (with SSA)",
  SCHEDULE_VISIT: "Schedule visit",
  SCHEDULE_FOLLOW_UP_VISIT: "Schedule follow-up",
  SCHEDULE_COACHING_VISIT: "Schedule coaching visit",
  SCHEDULE_IN_SCHOOL_TRAINING: "Schedule in-school training",
  SCHEDULE_CLUSTER_TRAINING: "Schedule cluster training",
  SCHEDULE_CLUSTER_MEETING: "Schedule cluster meeting",
  SCHEDULE_GROUP_TRAINING: "Schedule group training",
  ASSIGN_TO_SELF: "Assign to me",
  ASSIGN_TO_CCEO: "Assign to CCEO",
  ASSIGN_TO_PARTNER: "Assign to partner",
  ADD_TO_CLUSTER: "Add to a cluster",
  VIEW_SSA: "View SSA",
  VIEW_SCHOOL: "View school",
  VIEW_CLUSTER: "View cluster",
};

const SCHEDULE_KINDS: ReadonlySet<PlanningActionKind> = new Set<PlanningActionKind>([
  "SCHEDULE_SIT",
  "SCHEDULE_VISIT",
  "SCHEDULE_FOLLOW_UP_VISIT",
  "SCHEDULE_COACHING_VISIT",
  "SCHEDULE_IN_SCHOOL_TRAINING",
  "SCHEDULE_CLUSTER_TRAINING",
  "SCHEDULE_CLUSTER_MEETING",
  "SCHEDULE_GROUP_TRAINING",
]);

const ASSIGN_KINDS: ReadonlySet<PlanningActionKind> = new Set<PlanningActionKind>([
  "ASSIGN_TO_SELF",
  "ASSIGN_TO_CCEO",
  "ASSIGN_TO_PARTNER",
]);

const VIEW_KINDS: ReadonlySet<PlanningActionKind> = new Set<PlanningActionKind>([
  "VIEW_SSA",
  "VIEW_SCHOOL",
  "VIEW_CLUSTER",
]);

function iconFor(kind: PlanningActionKind) {
  if (kind === "COMPLETE_SSA") return CheckCircle2;
  if (SCHEDULE_KINDS.has(kind)) return Calendar;
  if (kind === "ASSIGN_TO_PARTNER" || kind === "ASSIGN_TO_CCEO") return Users;
  if (kind === "ASSIGN_TO_SELF") return Users;
  if (kind === "ADD_TO_CLUSTER") return Users;
  if (VIEW_KINDS.has(kind)) return ExternalLink;
  return ChevronRight;
}

// ─── Priority chip ─────────────────────────────────────────────────
//
// Maps the gap's priority to the right .status-indicator tone. Keeps
// the visual language consistent with the rest of the app — the same
// six-dot + tone treatment used on Workflow / Funds / Schools.

type PlanningPriority = "CRITICAL" | "HIGH" | "NORMAL" | "LOW";

function priorityClass(p: PlanningPriority): string {
  switch (p) {
    case "CRITICAL":
      return "status-returned";
    case "HIGH":
      return "status-pending";
    case "NORMAL":
      return "status-info";
    case "LOW":
    default:
      return "status-neutral";
  }
}

// ─── Helpers ───────────────────────────────────────────────────────

function safeActionState(
  gap: PlanningGap,
  kind: PlanningActionKind,
): ActionState {
  // Defensive: if the engine doesn't recognize a kind for this gap,
  // treat as unavailable rather than throw — the card stays renderable.
  try {
    return actionStateFor(gap, kind);
  } catch {
    return "UNAVAILABLE" as ActionState;
  }
}

// ─── Component ─────────────────────────────────────────────────────

export function PlanningGapCard({
  gap,
  onAction,
}: PlanningGapCardProps): JSX.Element {
  const locked = gap.ssaGate === "SIT_DONE_SSA_MISSING";

  // Locked render: SSA-missing-after-SIT. Hard gate — only Complete
  // SSA is reachable. No secondaries, no SSA snapshot.
  if (locked) {
    return (
      <article
        className={cn(
          "card rounded-xl p-5",
          "border-l-4 border-l-rose-500",
          "relative",
        )}
        aria-label={`Planning locked — ${gap.schoolName}`}
      >
        <header className="flex items-start justify-between gap-3 mb-3">
          <div className="status-indicator status-returned">
            <Lock size={13} aria-hidden /> PLANNING LOCKED
          </div>
          <span className="status-indicator status-returned">CRITICAL</span>
        </header>

        <h3 className="text-[15px] font-bold leading-tight text-[var(--color-edify-text)]">
          {gap.schoolName}
        </h3>

        <div className="mt-1 text-[12px] muted flex items-center gap-1.5 flex-wrap">
          {gap.district ? <span>{gap.district}</span> : null}
          {gap.clusterName ? (
            <>
              <span aria-hidden>·</span>
              <span>{gap.clusterName}</span>
            </>
          ) : null}
        </div>

        <div
          className={cn(
            "mt-3 rounded-lg p-3",
            "bg-rose-50/70 dark:bg-rose-500/10",
            "border border-rose-200/70 dark:border-rose-400/20",
            "border-l-4 border-l-rose-500",
          )}
        >
          <div className="flex items-start gap-2">
            <AlertOctagon
              size={14}
              className="text-rose-600 dark:text-rose-300 mt-[1px] shrink-0"
              aria-hidden
            />
            <div className="text-[12.5px] leading-snug">
              <span className="font-semibold">Reason: </span>
              <span className="text-[var(--color-edify-text)]">
                SSA not completed during the recent SIT.
              </span>
            </div>
          </div>
        </div>

        <div className="mt-4">
          <PrimaryActionButton
            kind="COMPLETE_SSA"
            state="AVAILABLE"
            onClick={() => onAction?.("COMPLETE_SSA", gap)}
          />
        </div>
      </article>
    );
  }

  // ─── Standard render ─────────────────────────────────────────────

  const priority = (gap.priority ?? "NORMAL") as PlanningPriority;
  const priorityClassName = priorityClass(priority);
  const primaryKind = gap.primaryActionKind as PlanningActionKind;
  const primaryState = safeActionState(gap, primaryKind);
  const secondaries: PlanningActionKind[] =
    (gap.secondaryActionKinds as PlanningActionKind[] | undefined) ?? [];

  const ssaComplete = gap.ssaCompleted !== false;
  const cceoName = gap.assignedCceo ?? gap.cceoName;

  return (
    <article
      className={cn(
        "card rounded-xl p-5",
        "border-l-4",
        ssaComplete ? "border-l-emerald-500/70" : "border-l-rose-500/70",
        "transition-shadow duration-200 hover:shadow-[0_8px_28px_-12px_rgba(15,23,42,0.18)]",
      )}
      aria-label={`Planning gap — ${gap.schoolName}`}
    >
      {/* ── Header: priority + status ── */}
      <header className="flex items-start justify-between gap-3 mb-2">
        <span className={cn("status-indicator", priorityClassName)}>
          {priority}
        </span>
        <span
          className={cn(
            "status-indicator",
            ssaComplete ? "status-approved" : "status-returned",
          )}
        >
          {ssaComplete ? "SSA Complete" : "SSA Missing"}
        </span>
      </header>

      {/* ── Title + locality line ── */}
      <h3 className="text-[15px] font-bold leading-tight text-[var(--color-edify-text)]">
        {gap.schoolName}
      </h3>

      <div className="mt-1 text-[12px] muted flex items-center gap-1.5 flex-wrap">
        {gap.district ? (
          <span className="inline-flex items-center gap-1">
            <Building2 size={11} aria-hidden /> {gap.district}
          </span>
        ) : null}
        {gap.clusterName ? (
          <>
            <span aria-hidden>·</span>
            <span>{gap.clusterName}</span>
          </>
        ) : null}
        {cceoName ? (
          <>
            <span aria-hidden>·</span>
            <span>CCEO: {cceoName}</span>
          </>
        ) : null}
      </div>

      {/* ── SSA "Why" snapshot ── */}
      <section
        className={cn(
          "mt-3 rounded-lg p-3",
          "bg-slate-50 dark:bg-slate-800/40",
          "border border-[var(--color-edify-border)]",
          "border-l-4",
          ssaComplete ? "border-l-emerald-500" : "border-l-rose-500",
        )}
        aria-label="SSA snapshot"
      >
        <div className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[0.06em] muted">
          <Sparkles size={11} aria-hidden /> Why
        </div>

        {gap.weakestArea ? (
          <div className="mt-1.5 text-[12.5px] leading-snug">
            <span className="muted">Weakest area: </span>
            <span className="font-semibold text-[var(--color-edify-text)]">
              {gap.weakestArea.area}
            </span>
            {typeof gap.weakestArea.score === "number" ? (
              <span className="muted"> ({gap.weakestArea.score}/10)</span>
            ) : null}
          </div>
        ) : null}

        {gap.recommendedSentence ? (
          <div className="mt-1 text-[12.5px] leading-snug">
            <span className="muted">Recommended: </span>
            <span className="text-[var(--color-edify-text)]">
              {gap.recommendedSentence}
            </span>
          </div>
        ) : null}
      </section>

      {/* ── Primary action ── */}
      <div className="mt-4">
        <PrimaryActionButton
          kind={primaryKind}
          state={primaryState}
          onClick={() => onAction?.(primaryKind, gap)}
        />
      </div>

      {/* ── Secondary action chips ── */}
      {secondaries.length > 0 ? (
        <div className="mt-2.5 flex items-center gap-1.5 flex-wrap">
          {secondaries.map((kind) => {
            const state = safeActionState(gap, kind);
            return (
              <SecondaryActionChip
                key={kind}
                kind={kind}
                state={state}
                onClick={() => onAction?.(kind, gap)}
              />
            );
          })}
        </div>
      ) : null}
    </article>
  );
}

// ─── Primary action button ─────────────────────────────────────────

function PrimaryActionButton({
  kind,
  state,
  onClick,
}: {
  kind: PlanningActionKind;
  state: ActionState;
  onClick: () => void;
}) {
  const Icon = iconFor(kind);
  const label = ACTION_LABEL[kind];
  const disabled = state !== "AVAILABLE";

  return (
    <button
      type="button"
      className={cn(
        "btn btn-primary",
        "w-full sm:w-auto",
        "inline-flex items-center gap-2",
      )}
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={disabled ? "Action locked" : label}
    >
      {disabled ? (
        <Lock size={14} aria-hidden />
      ) : (
        <Icon size={14} aria-hidden />
      )}
      <span>{label}</span>
    </button>
  );
}

// ─── Secondary action chip ─────────────────────────────────────────

function SecondaryActionChip({
  kind,
  state,
  onClick,
}: {
  kind: PlanningActionKind;
  state: ActionState;
  onClick: () => void;
}) {
  const Icon = iconFor(kind);
  const label = ACTION_LABEL[kind];
  const disabled = state !== "AVAILABLE";

  return (
    <button
      type="button"
      className={cn(
        "btn btn-sm",
        "rounded-full",
        "bg-transparent",
        "border-[var(--color-edify-border)]",
        "text-[var(--color-edify-text)]",
        "hover:bg-[var(--color-edify-soft)]/60",
      )}
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={disabled ? "Action locked" : label}
    >
      {disabled ? (
        <Lock size={12} aria-hidden />
      ) : (
        <Icon size={12} aria-hidden />
      )}
      <span>{label}</span>
    </button>
  );
}

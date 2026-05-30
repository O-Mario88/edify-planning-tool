"use client";

// CoreSchoolCard — per-school card for the Core School Planning Console.
//
// Renders the SSA-driven 4×4 support cycle:
//   1.  Identity strip (school name + district + assigned CCEO/partner)
//   2.  SSA status pill + Core Progress (Visits N/4 · Trainings M/4 · %)
//   3.  Priority interventions list (weakest → strongest, from latest SSA)
//   4.  Visit row (4 chips) + Training row (4 chips) — colour-coded by status
//   5.  Current-gap callout with primary CTA derived from nextCoreGap()
//   6.  Always-available assign actions
//
// Two variants share one shell:
//   • No-SSA / SSA-in-progress  → only "Schedule SSA" is enabled. The
//     SSA assessment itself can be owned by EITHER a CCEO/staff member
//     OR a certified partner — Myself / Staff / Partner all appear on
//     the assign drawer for schedule_ssa and schedule_followup_ssa.
//     ("SSA Verification" is a separate, M&E-controlled purpose that
//     stays staff-only — see STAFF_ONLY_PURPOSES in plan-cost-calculator.)
//   • SSA complete              → the next gap's primary CTA is prominent,
//     and Myself / Staff / Partner / Partner-Facilitator actions appear.
//
// The card itself is dumb — assignment is routed through
// PlanningAssignDrawer so the page-level toast logic stays in one place.

import { useState } from "react";
import {
  Building2, MapPin, Lock, ArrowRight, AlertOctagon, CheckCircle2, Clock,
  Circle, Footprints, GraduationCap, Sparkles, ChevronDown, ChevronRight, ChevronUp,
  User, Phone,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fullAddressOf, primaryContactOf } from "@/lib/planning/school-address";
import { ssaCycleBadge } from "@/lib/operational-cycle";
import {
  nextCoreGap,
  progressOf,
  planningReadiness,
  INTERVENTION_LABEL,
  type CoreSchoolPlan,
  type CoreActivity,
  type CoreActivityStatus,
  type CoreRecommendation,
  type PlanningReadinessStatus,
} from "@/lib/planning/core-school-plan-mock";
import {
  toPlanningStatus,
  PLANNING_STATUS_LABEL,
  PLANNING_STATUS_TONE,
} from "@/lib/planning/status-tokens";

// ────────── Status meta — sourced from the shared taxonomy ──────────
//
// One vocabulary, one colour map. Activity-status icons are kept here
// because the icon choice (Lock / Clock / Check) is a property of the
// *card's* presentation, not the canonical status itself.

const STATUS_ICON: Record<CoreActivityStatus, LucideIcon> = {
  blocked:     Lock,
  not_started: AlertOctagon,
  scheduled:   Clock,
  delivered:   CheckCircle2,
  verified:    CheckCircle2,
  completed:   CheckCircle2,
};

function statusMeta(s: CoreActivityStatus) {
  const canonical = toPlanningStatus(s);
  const tone      = PLANNING_STATUS_TONE[canonical];
  return {
    label: PLANNING_STATUS_LABEL[canonical],
    bg:    tone.bg,
    text:  tone.text,
    edge:  tone.edge,
    Icon:  STATUS_ICON[s],
  };
}

// ────────── Planning Readiness — pill tone map ──────────
//
// The single source of truth for "can this school be planned for?".
// Replaces the old SSA-only pill — the rule is now strict: SIT + SSA
// must both be complete for the current cycle. The pill renders the
// canonical readiness label from lib/planning/core-school-plan-mock.

const READINESS_TONE: Record<PlanningReadinessStatus, { bg: string; text: string; ring: string }> = {
  locked_sit: { bg: "bg-rose-50",    text: "text-rose-700",    ring: "ring-rose-100"    },
  locked_ssa: { bg: "bg-amber-50",   text: "text-amber-700",   ring: "ring-amber-100"   },
  ready:      { bg: "bg-emerald-50", text: "text-emerald-700", ring: "ring-emerald-100" },
  expired:    { bg: "bg-amber-50",   text: "text-amber-800",   ring: "ring-amber-200"   },
  blocked:    { bg: "bg-slate-100",  text: "text-slate-700",   ring: "ring-slate-200"   },
};

// ────────── Component ──────────

export type CoreAssignRequest = {
  plan: CoreSchoolPlan;
  rec: CoreRecommendation;
  label: string;
  purpose: string;
  // Whether the activity allows partner-as-facilitator (trainings yes, visits no).
  allowFacilitator: boolean;
  // Whether the activity allows partner ownership (visits yes, SSA no).
  allowPartner: boolean;
};

export function CoreSchoolCard({
  plan,
  onAssign,
}: {
  plan: CoreSchoolPlan;
  onAssign: (req: CoreAssignRequest) => void;
}) {
  const rec       = nextCoreGap(plan);
  const readiness = planningReadiness(plan);
  // `planningLocked` is the canonical UI gate now — true whenever
  // SIT or SSA hasn't completed for the current cycle. Every
  // disable / tooltip / progress-bar tint reads this single boolean
  // so the card's lock state never drifts out of sync with the rule.
  const planningLocked = !readiness.planningEnabled;
  const progress       = progressOf(plan);
  const cycleComplete  = rec.gap === "cycle_complete";
  const readinessTone  = READINESS_TONE[readiness.status];
  const [interventionsOpen, setInterventionsOpen] = useState(false);
  // Outer expand/collapse — keeps the bucket scannable. Locked / urgent
  // schools open by default so the planner sees the blocked reason
  // without having to tap; healthy in-cycle ones stay collapsed.
  const [open, setOpen] = useState<boolean>(planningLocked);

  // Primary action availability + payload.
  // SSA assessment (initial OR follow-up) can be assigned to either a
  // CCEO or a partner — the cost calculator already supports partner
  // SSA Support; the card just needs to surface the Partner option in
  // the assign drawer. SSA Verification is a separate purpose that
  // remains staff-only (enforced in plan-cost-calculator's
  // STAFF_ONLY_PURPOSES list).
  const primaryAllowFacilitator = rec.primaryAction === "schedule_training";
  const primaryAllowPartner = rec.primaryAction !== "view";

  function triggerPrimary() {
    onAssign({
      plan,
      rec,
      label: rec.primaryLabel,
      purpose: rec.purpose,
      allowFacilitator: primaryAllowFacilitator,
      allowPartner: primaryAllowPartner,
    });
  }

  return (
    <li className={cn(
      "rounded-2xl border border-[var(--color-edify-divider)] bg-white overflow-hidden transition-colors",
      open && "bg-[var(--color-edify-soft)]/30",
    )}>
      {/* Collapsed header — always visible. Shows school identity, the
          readiness pill, and a compact progress sliver so a planner can
          scan the bucket without expanding every row. Tap anywhere on
          the header to expand the full detail body below. */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={`core-school-${plan.id}-detail`}
        className="w-full p-4 flex items-start gap-3 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
      >
        <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
          <Building2 size={15} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2 flex-wrap">
            <h3 className="text-body-lg font-extrabold tracking-tight truncate">{plan.schoolName}</h3>
            <span
              className={cn(
                "inline-flex items-center px-2 py-[3px] rounded-md text-[10px] font-extrabold uppercase tracking-wide ring-1 shrink-0",
                readinessTone.bg, readinessTone.text, readinessTone.ring,
              )}
              title={readiness.reason}
            >
              {readiness.label}
            </span>
          </div>
          <p className="text-[11px] muted leading-tight inline-flex items-center gap-1 mt-0.5">
            <MapPin size={9} className="text-[var(--color-edify-primary)]" />
            {plan.district} · CCEO {plan.assignedCceo}
            <span aria-hidden className="mx-1 opacity-50">·</span>
            <span className="tabular font-semibold text-[var(--color-edify-text)]">
              {progress.visits}/4 V · {progress.trainings}/4 T
            </span>
            <span aria-hidden className="mx-1 opacity-50">·</span>
            <span className="tabular font-semibold">{progress.pct}%</span>
          </p>
          <div className="relative h-1 mt-1.5 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
            <div
              className={cn(
                "absolute inset-y-0 left-0 rounded-full transition-all",
                planningLocked ? "bg-slate-300" : "bg-[var(--color-edify-primary)]",
              )}
              style={{ width: `${progress.pct}%` }}
            />
          </div>
        </div>
        <ChevronRight
          size={14}
          className={cn(
            "text-[var(--color-edify-muted)] shrink-0 mt-1 transition-transform",
            open && "rotate-90",
          )}
        />
      </button>

      {open && (
      <div
        id={`core-school-${plan.id}-detail`}
        className="px-4 pb-4 -mt-1 grid grid-cols-12 gap-4 items-start"
      >
      {/* ───── Left column — school identity + cycle state ─────
          Tablet (md) keeps the column at full width so the 4-chip rows
          + intervention list don't get squeezed; splits 7/5 at lg. */}
      <div className="col-span-12 lg:col-span-7 min-w-0">
        <header className="flex items-start gap-2.5 flex-wrap">
          <div className="min-w-0 flex-1">
            {/* Full postal address — District, Subcounty, Parish, Village.
                Staff and partners plug this straight into a GPS app. */}
            <p className="text-[11px] muted leading-tight inline-flex items-center gap-1 mt-0.5">
              <MapPin size={9} className="text-[var(--color-edify-primary)]" />
              {fullAddressOf(plan)}
            </p>
            {/* Head-teacher contact — name + phone, in calling format. */}
            {(() => {
              const c = primaryContactOf(plan);
              return (
                <p className="text-[11px] muted leading-tight inline-flex items-center gap-1.5 mt-0.5 flex-wrap">
                  <User  size={9} className="text-[var(--color-edify-primary)]" />
                  <span className="font-semibold text-[var(--color-edify-text)]">{c.name}</span>
                  <span className="opacity-50">·</span>
                  <Phone size={9} className="text-[var(--color-edify-primary)]" />
                  <a href={`tel:${c.phone.replace(/\s+/g, "")}`} className="tabular hover:underline">{c.phone}</a>
                </p>
              );
            })()}
            <p className="text-[11px] muted leading-tight mt-0.5">
              CCEO {plan.assignedCceo}
              {plan.assignedPartner ? <> · Partner {plan.assignedPartner}</> : null}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1 shrink-0">
            {/* SIT + SSA dates — audit trail behind the readiness pill
                (the pill itself now sits in the collapsed header above).
                Planners read these for "why is this school Ready /
                Locked?". */}
            <span className="text-[10px] muted normal-case font-semibold leading-tight text-right">
              SIT {plan.sitDate ?? "—"}
              <span className="opacity-60"> · </span>
              SSA {plan.ssaDate ?? "—"}
            </span>
            {/* Cycle-aware label — surfaces "Historical Only · Last cycle · Jul 22, 2025"
                when the school's most-recent SSA is from a previous operational cycle.
                Prevents planners from being confused on Oct 1 when a school that
                completed SSA last cycle shows up needing one again. */}
            {(() => {
              const lastIso = plan.lastSsaIso ?? (plan.ssaStatus === "complete" ? plan.ssaDate : undefined);
              const badge   = ssaCycleBadge(lastIso);
              if (!badge.needsCurrentCycleAction && badge.status !== "current_cycle") return null;
              if (badge.status === "current_cycle") return null;  // already covered by the green pill above
              const tone =
                badge.tone === "danger" ? "bg-rose-50    text-rose-700    ring-rose-100" :
                badge.tone === "warn"   ? "bg-amber-50   text-amber-700   ring-amber-100" :
                badge.tone === "info"   ? "bg-sky-50     text-sky-700     ring-sky-100" :
                                          "bg-emerald-50 text-emerald-700 ring-emerald-100";
              return (
                <span
                  className={cn(
                    "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-semibold whitespace-nowrap ring-1",
                    tone,
                  )}
                  title="The operational cycle resets every October 1. Historical records remain on the school profile."
                >
                  {badge.label}
                  {badge.sub && <span className="ml-1 opacity-80 font-normal">· {badge.sub}</span>}
                </span>
              );
            })()}
          </div>
        </header>

        {/* Progress strip — bordered, no fill (unified callout surface) */}
        <div className="mt-3 rounded-xl border border-[var(--color-edify-divider)] px-3 py-2.5">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[10px] uppercase tracking-wider font-bold muted">Core support cycle</div>
            <div className="text-[11px] font-extrabold tabular text-[var(--color-edify-text)]">
              {progress.pct}%
            </div>
          </div>
          <div className="flex items-center gap-3 mt-1.5 text-[12px] font-semibold">
            <span className="inline-flex items-center gap-1.5">
              <Footprints size={11} className="text-[var(--color-edify-primary)]" />
              Visits <span className="font-extrabold tabular">{progress.visits}/4</span>
            </span>
            <span className="inline-flex items-center gap-1.5">
              <GraduationCap size={11} className="text-[var(--color-edify-primary)]" />
              Trainings <span className="font-extrabold tabular">{progress.trainings}/4</span>
            </span>
            {cycleComplete && (
              <span className="ml-auto inline-flex items-center gap-1 text-emerald-700 font-extrabold uppercase text-[10px] tracking-wide">
                <CheckCircle2 size={11} /> Cycle complete
              </span>
            )}
          </div>
          <div className="relative h-1.5 mt-2 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
            <div
              className={cn(
                "absolute inset-y-0 left-0 rounded-full transition-all",
                planningLocked ? "bg-slate-300" : "bg-[var(--color-edify-primary)]",
              )}
              style={{ width: `${progress.pct}%` }}
            />
          </div>
        </div>

        {/* Priority interventions — collapsed by default so the 4×4
            chip rows + recommendation are the visual headline. Click
            to expand; the toggle echoes the top 2 areas inline so the
            card stays scannable when closed. */}
        {plan.priorityInterventions.length > 0 ? (
          <div className="mt-3">
            <button
              type="button"
              onClick={() => setInterventionsOpen((v) => !v)}
              aria-expanded={interventionsOpen}
              className="w-full flex items-center gap-2 rounded-md border border-[var(--color-edify-divider)] px-3 py-2 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
            >
              <div className="flex-1 min-w-0">
                <div className="text-[10px] uppercase tracking-wider font-bold muted">
                  Priority interventions
                </div>
                {!interventionsOpen && (
                  <div className="text-[11px] text-[var(--color-edify-text)] truncate mt-0.5">
                    {plan.priorityInterventions.slice(0, 2).map((p, i) => (
                      <span key={p.area}>
                        {i > 0 && <span className="muted"> · </span>}
                        <span className="font-extrabold">{INTERVENTION_LABEL[p.area]}</span>
                        <span className="muted"> {p.score}/10</span>
                      </span>
                    ))}
                    <span className="muted"> + {plan.priorityInterventions.length - 2} more</span>
                  </div>
                )}
              </div>
              {interventionsOpen
                ? <ChevronUp size={13} className="text-[var(--color-edify-muted)] shrink-0" />
                : <ChevronDown size={13} className="text-[var(--color-edify-muted)] shrink-0" />
              }
            </button>
            {interventionsOpen && (
              <ol className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 mt-1.5">
                {plan.priorityInterventions.map((p, i) => (
                  <li
                    key={p.area}
                    className="flex items-center gap-2 rounded-md border border-[var(--color-edify-divider)] px-2 py-1.5"
                  >
                    <span className="grid place-items-center h-5 w-5 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] text-[10px] font-extrabold tabular shrink-0">
                      {i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="text-[11px] font-extrabold text-[var(--color-edify-text)] truncate">
                        {INTERVENTION_LABEL[p.area]}
                      </div>
                    </div>
                    <span className={cn(
                      "text-[10px] font-extrabold tabular px-1.5 py-[1px] rounded-sm",
                      p.score <= 5 ? "bg-rose-50 text-rose-700"
                        : p.score <= 6 ? "bg-amber-50 text-amber-700"
                        : "bg-emerald-50 text-emerald-700",
                    )}>
                      {p.score}/10
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        ) : (
          <div className="mt-3 rounded-md border border-dashed border-rose-200 px-3 py-2 text-[11px] text-rose-700 leading-snug">
            Priority interventions are generated from the SSA. Complete SSA to unlock the 4 weakest areas.
          </div>
        )}

        {/* 4-visit + 4-training rows */}
        <div className="mt-3 space-y-2">
          <ActivityRow
            title="Visits"
            Icon={Footprints}
            items={plan.visits}
            recActivity={rec.primaryAction === "schedule_visit" ? rec.activityNumber : undefined}
          />
          <ActivityRow
            title="Trainings"
            Icon={GraduationCap}
            items={plan.trainings}
            recActivity={rec.primaryAction === "schedule_training" ? rec.activityNumber : undefined}
          />
        </div>
      </div>

      {/* ───── Right column — recommendation + actions ───── */}
      <div className="col-span-12 lg:col-span-5 flex flex-col gap-2.5">
        {/* Gap callout — unified bordered, no-fill surface. Status
            colour lives on the icon chip only, not the panel itself. */}
        <div className="rounded-xl border border-[var(--color-edify-divider)] px-3 py-2.5">
          <div className="flex items-center gap-1.5">
            <span className={cn(
              "grid place-items-center h-5 w-5 rounded-md shrink-0",
              planningLocked     ? "bg-rose-100 text-rose-700"
              : cycleComplete? "bg-emerald-100 text-emerald-700"
              :                "bg-amber-100 text-amber-700",
            )}>
              {planningLocked ? <Lock size={11} /> : cycleComplete ? <CheckCircle2 size={11} /> : <Sparkles size={11} />}
            </span>
            <div className="text-[10px] uppercase tracking-wider font-bold text-[var(--color-edify-muted)]">
              Recommended next action
            </div>
          </div>
          <p className="text-[12px] font-extrabold text-[var(--color-edify-text)] leading-snug mt-1">
            {rec.headline}
          </p>
          <p className="text-[11px] muted leading-snug mt-1">{rec.purpose}</p>
        </div>

        {/* Primary CTA */}
        <button
          type="button"
          onClick={triggerPrimary}
          className={cn(
            "inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md text-[12px] font-extrabold transition-colors whitespace-nowrap",
            "bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]",
          )}
        >
          {rec.primaryLabel}
          <ArrowRight size={12} />
        </button>

        {/* Secondary actions — disabled wholesale when SSA is blocked. */}
        <div className="grid grid-cols-2 gap-1.5">
          <SecondaryButton
            label="Assign to Staff"
            disabled={planningLocked}
            disabledHint={rec.blockedReason}
            onClick={() => onAssign({
              plan, rec,
              label: rec.primaryLabel,
              purpose: rec.purpose,
              allowFacilitator: primaryAllowFacilitator,
              allowPartner: primaryAllowPartner,
            })}
          />
          <SecondaryButton
            label="Assign to Partner"
            disabled={planningLocked || !primaryAllowPartner}
            disabledHint={
              planningLocked
                ? rec.blockedReason
                : "SSA scheduling stays with Edify staff — partners can't own SSAs."
            }
            onClick={() => onAssign({
              plan, rec,
              label: rec.primaryLabel,
              purpose: rec.purpose,
              allowFacilitator: primaryAllowFacilitator,
              allowPartner: true,
            })}
          />
          {/* Partner-as-Facilitator surfaces only when training is the next gap. */}
          {primaryAllowFacilitator && !planningLocked && (
            <button
              type="button"
              onClick={() => onAssign({
                plan, rec,
                label: rec.primaryLabel,
                purpose: rec.purpose,
                allowFacilitator: true,
                allowPartner: true,
              })}
              className="col-span-2 inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold hover:bg-[var(--color-edify-soft)]/60 whitespace-nowrap"
            >
              Assign Partner as Facilitator
            </button>
          )}
        </div>

        {planningLocked && (
          <div className="text-[11px] muted leading-snug flex items-start gap-1.5 px-0.5">
            <Lock size={10} className="mt-0.5 text-rose-500 shrink-0" />
            <span>{rec.blockedReason}</span>
          </div>
        )}
      </div>
      </div>
      )}
    </li>
  );
}

// ────────── Internal — 4-item activity row ──────────

function ActivityRow({
  title, Icon, items, recActivity,
}: {
  title: string;
  Icon: LucideIcon;
  items: readonly [CoreActivity, CoreActivity, CoreActivity, CoreActivity];
  recActivity?: 1 | 2 | 3 | 4;
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider font-bold muted mb-1">
        <Icon size={10} className="text-[var(--color-edify-primary)]" />
        {title}
      </div>
      <div className="grid grid-cols-4 gap-1.5">
        {items.map((a) => (
          <ActivityChip key={a.number} activity={a} isNext={recActivity === a.number} />
        ))}
      </div>
    </div>
  );
}

function ActivityChip({ activity: a, isNext }: { activity: CoreActivity; isNext: boolean }) {
  const meta = statusMeta(a.status);
  const Pill = meta.Icon;
  return (
    <div
      className={cn(
        "rounded-md px-1.5 py-1.5 border flex flex-col gap-0.5 min-w-0",
        meta.bg,
        isNext ? "border-[var(--color-edify-primary)] ring-2 ring-[var(--color-edify-primary)]/25"
               : "border-transparent",
      )}
      title={`${a.intervention} — ${meta.label}${a.scheduledFor ? ` · ${a.scheduledFor}` : ""}`}
    >
      <div className="flex items-center gap-1">
        <span className={cn("text-[10px] font-extrabold tabular", meta.text)}>#{a.number}</span>
        <Pill size={9} className={meta.text} />
        {a.status === "blocked" || a.status === "not_started" ? (
          <Circle size={6} className="ml-auto text-slate-300" />
        ) : null}
      </div>
      <div className={cn("text-[10px] font-extrabold uppercase tracking-wide", meta.text)}>
        {meta.label}
      </div>
      <div className="text-[10px] font-semibold text-[var(--color-edify-text)] leading-tight truncate">
        {INTERVENTION_LABEL[a.intervention]}
      </div>
      {a.scheduledFor && (
        <div className="text-[10px] muted leading-tight truncate">{a.scheduledFor}</div>
      )}
    </div>
  );
}

function SecondaryButton({
  label, disabled, disabledHint, onClick,
}: {
  label: string;
  disabled?: boolean;
  disabledHint?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={() => !disabled && onClick()}
      disabled={disabled}
      title={disabled ? disabledHint : undefined}
      className={cn(
        "inline-flex items-center justify-center gap-1 h-9 px-3 rounded-md text-[11px] font-semibold transition-colors whitespace-nowrap",
        disabled
          ? "bg-slate-100 text-slate-400 cursor-not-allowed"
          : "border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
      )}
    >
      {label}
    </button>
  );
}

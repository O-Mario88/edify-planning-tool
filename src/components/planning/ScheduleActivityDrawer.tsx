"use client";

// ScheduleActivityDrawer — unified calendar-driven scheduling drawer.
// Replaces ScheduleClusterMeetingDrawer + ScheduleSchoolTrainingDrawer.
//
// Both flows shared ~90 % of their code (calendar, quick picks, cost
// preview, venue/notes). This drawer takes a generic
//
//   target:       { kind: "cluster" | "school"; id; name }
//   activityType: string                    // "1st Cluster Meeting", etc.
//   isTraining:   boolean                   // 4-rate cost + partner field
//
// and renders the right chrome for either side. Callers stay tiny — they
// translate their domain object into the target/activity shape and the
// drawer handles the rest. Subsequent moves on a scheduled activity go
// through the existing RescheduleClusterMeetingDrawer (cluster side) or
// a future RescheduleActivityDrawer (school side).

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { formatUgxShort as formatUgx } from "@/lib/format-utils";
import {
  CalendarPlus, ChevronLeft, ChevronRight, Users, GraduationCap, MapPin,
  CalendarCheck, AlertTriangle, Wallet, Sparkles,
} from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Select } from "@/components/ui/Select";
import { Button } from "@/components/ui/Button";
import { DEFAULT_GROUP_RATES } from "@/lib/cost-engine/cost-rates-default";
import {
  computeClusterMeetingCost,
  computeTrainingCost,
} from "@/lib/cost-engine/cost-engine";
import { cn } from "@/lib/utils";

// Partner pool — same demo set used elsewhere in the planning flow.
const PARTNER_POOL = [
  "Bright Future Education Partners",
  "Literacy Training Uganda",
  "Numeracy First",
];

export type ScheduleActivityTarget = {
  kind: "cluster" | "school";
  id:   string;
  name: string;
};

export type ScheduleActivityContext = {
  target:       ScheduleActivityTarget;
  /** Human-readable activity type: e.g. "1st Cluster Meeting",
   *  "School Improvement Training", "Teaching & Learning Improvement Training". */
  activityType: string;
  /** Trainings carry the 4-rate cost (Session + Venue + Meals +
   *  Mobilisation) and surface the partner-facilitator selector;
   *  meetings carry the single-rate cluster-meeting cost (UGX 10K
   *  × participants) and hide the facilitator field. */
  isTraining:   boolean;
  /** Default participant count seed. The drawer uses this as the
   *  initial value of the participants input. Required when
   *  isTraining so the cost preview can compute on first paint. */
  defaultParticipants?: number;
  /** Default "Proposed by" value, typically "<CCEO name> (CCEO)". */
  defaultProposedBy:    string;
  /** Optional location/subtitle for the header, e.g. "Kitgum" or
   *  "Hope Primary · Kitgum". Defaults to nothing. */
  locationLine?:        string;
  /** Optional SSA focus line shown in the activity info card. Used
   *  by school-level trainings to surface the weakest SSA area. */
  ssaFocus?:            { area: string; score: number };
  /** Optional cluster summary line shown in the activity info card,
   *  e.g. "5 schools · 4 with SSA · CCEO Acan". */
  clusterSummary?:      string;
  /** Optional SSA-shortfall warning for cluster SIT — n of total
   *  schools missing SSA. Surfaces an explicit eligibility warning
   *  so the CCEO sees the exclusion list up front. */
  ssaShortfall?:        { missing: number; total: number };
  /** Optional "school has no current SSA" warning for school trainings. */
  noCurrentSsa?:        boolean;
  /** Submit-button label override. Defaults to "Schedule training"
   *  or "Schedule meeting" depending on isTraining. */
  submitLabel?:         string;
};

export type ScheduleActivityOutcome = {
  target:           ScheduleActivityTarget;
  activityType:     string;
  isTraining:       boolean;
  date:             string;      // "Jun 20, 2026" or "Week 2 · June 2026"
  isoDate:          string;      // ISO "2026-06-20" (first day of chosen week for visits)
  proposedBy:       string;
  /** Set for visit-type activities (month+week, no exact date). */
  weekOfMonth?:     number;
  /** Required when isTraining. Optional for meetings. */
  participants?:    number;
  venue?:           string;
  notes?:           string;
  /** Only set when isTraining — meetings don't surface this field. */
  partnerFacilitator?: string;
  /** Projected total cost in UGX based on participants + CD rates. */
  projectedCostUgx?: number;
};

const MONTHS = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
] as const;

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function ScheduleActivityDrawer({
  open, context, onClose, onSubmit,
}: {
  open: boolean;
  context: ScheduleActivityContext | null;
  onClose: () => void;
  onSubmit: (outcome: ScheduleActivityOutcome) => void;
}) {
  const today = useMemo(() => new Date(), []);
  const [viewYear, setViewYear]         = useState(today.getFullYear());
  const [viewMonth, setViewMonth]       = useState(today.getMonth());
  const [selected, setSelected]         = useState<Date | null>(null);
  // Visit-mode (school visits, non-training): month + week instead of calendar.
  const [visitMonth, setVisitMonth]     = useState(today.getMonth());
  const [visitWeek, setVisitWeek]       = useState(Math.min(4, Math.ceil(today.getDate() / 7)));
  const [proposedBy, setProposedBy]     = useState("");
  const [participants, setParticipants] = useState<string>("");
  const [venue, setVenue]               = useState<string>("");
  const [notes, setNotes]               = useState<string>("");
  const [partnerFacilitator, setPartnerFacilitator] = useState<string>("");
  const [error, setError]               = useState<string | null>(null);
  // The school's poorly-performing SSA interventions (name + score), fetched
  // live so a support visit is planned against the real gaps, not a single
  // hard-coded "weakest area".
  const [weakInterventions, setWeakInterventions] = useState<Array<{ area: string; score: number }> | null>(null);

  // Re-seed each time the drawer opens for a new context. Encoded as
  // a single effect rather than a key-reset so the chrome doesn't
  // flicker when the same drawer reopens with a different target.
  useEffect(() => {
    if (open && context) {
      setViewYear(today.getFullYear());
      setViewMonth(today.getMonth());
      setSelected(null);
      setVisitMonth(today.getMonth());
      setVisitWeek(Math.min(4, Math.ceil(today.getDate() / 7)));
      setProposedBy(context.defaultProposedBy);
      setParticipants(
        context.defaultParticipants != null
          ? String(context.defaultParticipants)
          : "",
      );
      setVenue("");
      setNotes("");
      setPartnerFacilitator("");
      setError(null);
    }
  }, [open, context, today]);

  const cycle = useMemo(() => cycleBoundsFor(today), [today]);

  // Pull the school's SSA interventions when the drawer opens for a school, so
  // the activity card lists every intervention the school is weak in (name +
  // score), sorted worst-first. Cluster targets keep their summary instead.
  const schoolTargetId = context && context.target.kind === "school" ? context.target.id : null;
  useEffect(() => {
    if (!open || !schoolTargetId) { setWeakInterventions(null); return; }
    let cancelled = false;
    fetch(`/api/ssa/school/${encodeURIComponent(schoolTargetId)}`, { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (cancelled) return;
        const recs: Array<{ scores?: Array<{ intervention: string; score: number }> }> = j?.records ?? [];
        const scores = recs[0]?.scores ?? [];
        if (!scores.length) { setWeakInterventions(null); return; }
        // "Poorly performing" = below 6/10; if none, fall back to the lowest two.
        const ranked = [...scores].sort((a, b) => a.score - b.score);
        const weak = ranked.filter((s) => s.score < 6);
        const chosen = (weak.length ? weak : ranked.slice(0, 2)).slice(0, 4);
        setWeakInterventions(chosen.map((s) => ({ area: humanizeIntervention(s.intervention), score: s.score })));
      })
      .catch(() => { if (!cancelled) setWeakInterventions(null); });
    return () => { cancelled = true; };
  }, [open, schoolTargetId]);

  if (!context) return null;

  const isTraining        = context.isTraining;
  // School visits (not training, not cluster) use a month+week picker instead of
  // the full calendar — visits don't happen on a specific date.
  const isVisitMode       = !isTraining && context.target.kind === "school";
  const Icon              = isTraining ? GraduationCap : Users;
  const participantCount  = Number.parseInt(participants, 10);
  const validParticipants = Number.isFinite(participantCount) && participantCount > 0;
  // Training → 4-rate cost; meeting → single-rate cost. Visits: no cost preview.
  const costPreview = validParticipants && !isVisitMode
    ? (isTraining
        ? computeTrainingCost({ participants: participantCount, rates: DEFAULT_GROUP_RATES })
        : computeClusterMeetingCost({ participants: participantCount, rates: DEFAULT_GROUP_RATES })
      )
    : null;
  const outsideCycle = selected !== null && (selected < cycle.start || selected > cycle.end);
  const submitLabel  = context.submitLabel ?? (isVisitMode ? "Schedule visit" : isTraining ? "Schedule training" : "Schedule meeting");

  function handlePrevMonth() {
    setViewMonth((m) => {
      if (m === 0) { setViewYear((y) => y - 1); return 11; }
      return m - 1;
    });
  }
  function handleNextMonth() {
    setViewMonth((m) => {
      if (m === 11) { setViewYear((y) => y + 1); return 0; }
      return m + 1;
    });
  }
  function pickRelative(daysAhead: number) {
    const target = new Date(today);
    target.setHours(0, 0, 0, 0);
    target.setDate(target.getDate() + daysAhead);
    setSelected(target);
    setViewYear(target.getFullYear());
    setViewMonth(target.getMonth());
  }
  function pickNextMonth() {
    const target = new Date(today.getFullYear(), today.getMonth() + 1, 1);
    setSelected(target);
    setViewYear(target.getFullYear());
    setViewMonth(target.getMonth());
  }

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!context) return;
    if (!proposedBy.trim()) {
      setError("Name the person proposing the date.");
      return;
    }
    if (isTraining && !validParticipants) {
      setError("Expected participants is required for trainings so the projected cost can be generated.");
      return;
    }
    if (!isVisitMode && !selected) {
      setError("Pick a date on the calendar.");
      return;
    }

    if (isVisitMode) {
      // Visit mode: derive a representative ISO date (first day of the chosen
      // week in the chosen month). The outcome carries weekOfMonth so My Plan
      // can bucket it correctly without depending on the exact date.
      const WEEK_START_DAY = [1, 8, 15, 22][visitWeek - 1] ?? 1;
      const visitDate = new Date(today.getFullYear(), visitMonth, WEEK_START_DAY);
      const weekLabels = ["Week 1", "Week 2", "Week 3", "Week 4"];
      onSubmit({
        target:       context.target,
        activityType: context.activityType,
        isTraining:   false,
        date:         `${weekLabels[visitWeek - 1] ?? "Week 1"} · ${MONTHS[visitMonth]} ${visitDate.getFullYear()}`,
        isoDate:      formatIso(visitDate),
        weekOfMonth:  visitWeek,
        proposedBy:   proposedBy.trim(),
        venue:        venue.trim() || undefined,
        notes:        notes.trim() || undefined,
      });
      return;
    }

    onSubmit({
      target:             context.target,
      activityType:       context.activityType,
      isTraining,
      date:               formatHumanDate(selected!),
      isoDate:            formatIso(selected!),
      proposedBy:         proposedBy.trim(),
      participants:       validParticipants ? participantCount : undefined,
      venue:              venue.trim() || undefined,
      notes:              notes.trim() || undefined,
      partnerFacilitator: isTraining ? (partnerFacilitator || undefined) : undefined,
      projectedCostUgx:   costPreview?.totalUgx,
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Schedule ${context.activityType}`}
      description={`${context.target.name}${context.locationLine ? ` · ${context.locationLine}` : ""}`}
      size="md"
      variant="sheet"
      footer={
        <div className="flex items-center justify-end gap-2 w-full">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            size="sm"
            Icon={CalendarPlus}
            onClick={() => {
              const form = document.getElementById("schedule-activity-form") as HTMLFormElement | null;
              form?.requestSubmit();
            }}
          >
            {submitLabel}
          </Button>
        </div>
      }
    >
      <form id="schedule-activity-form" onSubmit={handleSubmit} className="space-y-4">

        {/* Activity info card */}
        <section className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 p-3 flex items-start gap-2.5">
          <span className="grid place-items-center h-8 w-8 rounded-md bg-white text-[var(--color-edify-primary)] shrink-0 border border-[var(--color-edify-border)]">
            <Icon size={14} />
          </span>
          <div className="min-w-0">
            <div className="text-[13px] font-extrabold tracking-tight">{context.activityType}</div>
            <div className="text-[11.5px] muted leading-tight">{context.target.name}</div>
            {context.locationLine && (
              <div className="text-[11.5px] muted inline-flex items-center gap-1 mt-0.5">
                <MapPin size={10} /> {context.locationLine}
              </div>
            )}
            {context.clusterSummary && (
              <div className="text-[11px] muted leading-tight mt-0.5">{context.clusterSummary}</div>
            )}
            {/* Live SSA weak-intervention list (school targets). Shows every
                intervention the school is performing poorly in, worst-first. */}
            {weakInterventions && weakInterventions.length > 0 ? (
              <div className="mt-1.5">
                <div className="text-[10px] uppercase tracking-wider font-bold text-rose-600">Performing poorly in</div>
                <div className="flex flex-wrap items-center gap-1 mt-1">
                  {weakInterventions.map((w) => (
                    <span key={w.area} className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md bg-rose-50 border border-rose-200 text-rose-700 text-[10.5px] font-extrabold">
                      {w.area} · {w.score}/10
                    </span>
                  ))}
                </div>
              </div>
            ) : context.ssaFocus ? (
              <div className="text-[11px] muted leading-tight mt-1">
                SSA focus:{" "}
                <span className="font-extrabold text-[var(--color-edify-text)]">
                  {context.ssaFocus.area} ({context.ssaFocus.score}/10)
                </span>
              </div>
            ) : null}
            {/* Explicit SIP eligibility warning — cluster SIT only.
                Spells out how many schools will be excluded so the
                CCEO doesn't have to do the math against schoolsWithSsa. */}
            {context.ssaShortfall && context.ssaShortfall.missing > 0 && (
              <div className="mt-1.5 inline-flex items-start gap-1 text-[11px] text-amber-700">
                <AlertTriangle size={10} className="mt-0.5 shrink-0" />
                {context.ssaShortfall.missing} of {context.ssaShortfall.total} schools missing SSA — they will not be included in this training. Schedule the missing SSAs first if you want full coverage.
              </div>
            )}
            {context.noCurrentSsa && (
              <div className="mt-1.5 inline-flex items-start gap-1 text-[11px] text-amber-700">
                <AlertTriangle size={10} className="mt-0.5 shrink-0" />
                School has no current-cycle SSA. Training will run, but recommendations may be generic until SSA completes.
              </div>
            )}
          </div>
        </section>

        {isVisitMode ? (
          /* ── Visit mode: Month + Week picker (no specific date) ── */
          <section className="rounded-lg border border-[var(--color-edify-border)] bg-white p-3 space-y-3">
            <div className="text-[11px] muted leading-snug">
              School visits are scheduled by <strong>month and week</strong> — no specific date needed.
              The system will show this visit in your plan for the chosen week.
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">Month</label>
                <select
                  value={visitMonth}
                  onChange={(e) => setVisitMonth(Number(e.target.value))}
                  className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px]"
                >
                  {MONTHS.map((name, idx) => (
                    <option key={idx} value={idx}>{name}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-[10.5px] font-bold uppercase tracking-wide muted mb-1">Week</label>
                <select
                  value={visitWeek}
                  onChange={(e) => setVisitWeek(Number(e.target.value))}
                  className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[12px]"
                >
                  <option value={1}>Week 1 (1st – 7th)</option>
                  <option value={2}>Week 2 (8th – 14th)</option>
                  <option value={3}>Week 3 (15th – 21st)</option>
                  <option value={4}>Week 4 (22nd – end)</option>
                </select>
              </div>
            </div>
            <div className="pt-2 border-t border-[var(--color-edify-divider)] flex items-center justify-between text-[11.5px]">
              <span className="muted inline-flex items-center gap-1">
                <CalendarCheck size={11} className="text-[var(--color-edify-primary)]" />
                Scheduled for
              </span>
              <span className="font-extrabold tabular">
                Week {visitWeek} · {MONTHS[visitMonth]} {today.getFullYear()}
              </span>
            </div>
          </section>
        ) : (
          <>
            {/* Quick picks */}
            <section className="flex flex-wrap items-center gap-1.5">
              <span className="text-caption uppercase tracking-wider font-bold muted mr-1">Quick picks</span>
              <QuickPick label="This Week"  onClick={() => pickRelative(7 - today.getDay())} />
              <QuickPick label="Next Week"  onClick={() => pickRelative(14 - today.getDay())} />
              <QuickPick label="Next Month" onClick={pickNextMonth} />
            </section>

            {/* Calendar */}
            <section className="rounded-lg border border-[var(--color-edify-border)] bg-white p-3">
              <header className="flex items-center justify-between mb-2.5">
                <button
                  type="button"
                  onClick={handlePrevMonth}
                  aria-label="Previous month"
                  className="h-7 w-7 grid place-items-center rounded-md hover:bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)] transition-colors"
                >
                  <ChevronLeft size={14} />
                </button>
                <div className="text-[13px] font-extrabold tracking-tight">
                  {MONTHS[viewMonth]} {viewYear}
                </div>
                <button
                  type="button"
                  onClick={handleNextMonth}
                  aria-label="Next month"
                  className="h-7 w-7 grid place-items-center rounded-md hover:bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)] transition-colors"
                >
                  <ChevronRight size={14} />
                </button>
              </header>

              <div className="grid grid-cols-7 gap-0.5 mb-1">
                {DAY_LABELS.map((d) => (
                  <div
                    key={d}
                    className="h-6 text-center text-[10px] uppercase tracking-wider font-bold text-[var(--color-edify-muted)] flex items-center justify-center"
                  >
                    {d}
                  </div>
                ))}
              </div>

              <div className="grid grid-cols-7 gap-0.5">
                {buildCalendarCells(viewYear, viewMonth).map((cell, i) => {
                  const isToday    = sameDate(cell.date, today);
                  const isSelected = !!selected && sameDate(cell.date, selected);
                  const isPast     = cell.date < startOfDay(today);
                  return (
                    <button
                      key={i}
                      type="button"
                      onClick={() => {
                        setSelected(cell.date);
                        if (!cell.inMonth) {
                          setViewMonth(cell.date.getMonth());
                          setViewYear(cell.date.getFullYear());
                        }
                      }}
                      disabled={isPast}
                      className={cn(
                        "h-9 rounded-md text-[12px] font-semibold tabular transition-colors",
                        "focus:outline-2 focus:outline-offset-1 focus:outline-[var(--color-edify-primary)]",
                        isSelected
                          ? "bg-[var(--color-edify-primary)] text-white shadow-sm font-extrabold"
                          : isPast
                            ? "text-[var(--color-edify-muted)] opacity-40 cursor-not-allowed"
                            : !cell.inMonth
                              ? "text-[var(--color-edify-muted)] opacity-60 hover:bg-[var(--color-edify-soft)]/40"
                              : isToday
                                ? "text-[var(--color-edify-primary)] ring-1 ring-[var(--color-edify-primary)]/40 hover:bg-[var(--color-edify-soft)]"
                                : "text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
                      )}
                    >
                      {cell.date.getDate()}
                    </button>
                  );
                })}
              </div>

              <div className="mt-3 pt-3 border-t border-[var(--color-edify-divider)] flex items-center justify-between text-[11.5px]">
                <span className="muted inline-flex items-center gap-1">
                  <CalendarCheck size={11} className="text-[var(--color-edify-primary)]" />
                  {selected ? "Selected" : "Pick a date"}
                </span>
                <span className="font-extrabold tabular">
                  {selected ? formatHumanDate(selected) : "—"}
                </span>
              </div>
            </section>
          </>
        )}

        {outsideCycle && !isVisitMode && (
          <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-[11.5px] text-amber-800 inline-flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span>
              Selected date is outside the current operational cycle
              ({formatHumanDate(cycle.start)} → {formatHumanDate(cycle.end)}).
              You can still save, but the activity won&apos;t count toward this cycle&apos;s gap closure.
            </span>
          </div>
        )}

        <Input
          label="Proposed by"
          required
          value={proposedBy}
          onChange={(e) => setProposedBy(e.target.value)}
          helper={
            context.target.kind === "cluster"
              ? "Typically the cluster leader. Override if a CCEO or partner facilitator is setting the date."
              : "Typically the CCEO. Override if a partner facilitator is setting the date."
          }
        />

        {!isVisitMode && (
          <Input
            label={isTraining ? "Expected participants" : "Expected participants (optional)"}
            type="number"
            min={1}
            required={isTraining}
            value={participants}
            onChange={(e) => setParticipants(e.target.value)}
            helper={isTraining
              ? "Required. Drives the projected training cost (Session + Venue + Meals + Mobilisation)."
              : "Optional. When set, projects the cluster meeting cost at UGX 10K × participants."}
          />
        )}

        {/* Partner facilitator (training only). Routine cluster
            meetings stay CCEO-led, so the field stays hidden. */}
        {isTraining && (
          <Select
            label="Partner facilitator (optional)"
            value={partnerFacilitator}
            onChange={(e) => setPartnerFacilitator(e.target.value)}
            options={[
              { value: "", label: "— No partner facilitator (Edify-led) —" },
              ...PARTNER_POOL.map((p) => ({ value: p, label: p })),
            ]}
            helper="When set, the partner sees this on their calendar; Edify staff remain the owner."
          />
        )}

        {!isVisitMode && (costPreview ? (
          <section className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3 space-y-1.5">
            <header className="inline-flex items-center gap-1.5">
              <Wallet size={12} className="text-emerald-700" />
              <span className="text-[11px] uppercase tracking-wider font-extrabold text-emerald-700">
                Projected cost
              </span>
            </header>
            <ul className="text-[11.5px] space-y-0.5">
              {costPreview.lines.map((l) => (
                <li key={l.label} className="flex items-baseline justify-between gap-2">
                  <span className="muted">{l.label}</span>
                  <span className="font-semibold tabular text-[var(--color-edify-text)]">{formatUgx(l.amountUgx)}</span>
                </li>
              ))}
            </ul>
            <div className="pt-1.5 mt-1 border-t border-emerald-200 flex items-baseline justify-between">
              <span className="text-caption uppercase tracking-wider font-bold text-emerald-700">Total</span>
              <span className="text-body-lg font-extrabold tabular text-emerald-700">{formatUgx(costPreview.totalUgx)}</span>
            </div>
            <p className="text-caption muted leading-snug pt-1">
              <Sparkles size={9} className="inline -mt-0.5 mr-1" />
              Rates set by the Country Director. Staff and partners cannot edit.
            </p>
          </section>
        ) : (
          <p className="text-[11px] muted">Cost will be calculated after participant count is added.</p>
        ))}

        {/* Venue only matters for trainings + cluster meetings (a gathering at a
            chosen location). School visits happen AT the school — its address is
            already on record — so the field is hidden in visit mode. */}
        {!isVisitMode && (
          <Input
            label="Venue / Location (optional)"
            value={venue}
            onChange={(e) => setVenue(e.target.value)}
            placeholder={context.target.kind === "cluster"
              ? "e.g. Kitgum Central Community Hall"
              : "e.g. School assembly hall"}
          />
        )}
        <Textarea
          label="Notes (optional)"
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Anything the facilitator should prep — materials, prerequisites, logistics"
        />

        {error && (
          <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            {error}
          </div>
        )}
      </form>
    </Modal>
  );
}

// ────────── Helpers ──────────

// Backend intervention key → readable label, e.g. "teaching_and_learning" →
// "Teaching & Learning".
function humanizeIntervention(key: string): string {
  return key
    .split("_")
    .map((w) => (w === "and" ? "&" : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

type Cell = { date: Date; inMonth: boolean };

function buildCalendarCells(year: number, month0: number): Cell[] {
  const first        = new Date(year, month0, 1);
  const startWeekday = first.getDay();
  const daysInMonth  = new Date(year, month0 + 1, 0).getDate();
  const daysInPrev   = new Date(year, month0, 0).getDate();
  const cells: Cell[] = [];
  for (let i = startWeekday - 1; i >= 0; i--) {
    cells.push({ date: new Date(year, month0 - 1, daysInPrev - i), inMonth: false });
  }
  for (let d = 1; d <= daysInMonth; d++) {
    cells.push({ date: new Date(year, month0, d), inMonth: true });
  }
  let nextDay = 1;
  while (cells.length < 42) {
    cells.push({ date: new Date(year, month0 + 1, nextDay++), inMonth: false });
  }
  return cells;
}

function sameDate(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear()
      && a.getMonth() === b.getMonth()
      && a.getDate() === b.getDate();
}
function startOfDay(d: Date): Date {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}
function formatIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
function formatHumanDate(d: Date): string {
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}
function cycleBoundsFor(today: Date): { start: Date; end: Date } {
  const m = today.getMonth();
  const y = today.getFullYear();
  const startYear = m >= 9 ? y : y - 1;
  return {
    start: new Date(startYear,     9,  1),
    end:   new Date(startYear + 1, 8, 30),
  };
}

function QuickPick({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="h-7 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-semibold text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60 transition-colors"
    >
      {label}
    </button>
  );
}

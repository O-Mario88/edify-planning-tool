"use client";

// Dialog the Program Lead opens when assigning a Training Follow-Up
// row to a CCEO. Captures:
//   • Which CCEO on the team receives the work
//   • The deadline by which the work should be done
//   • An optional one-line note
//
// On submit the parent component writes to the assignment store. The
// dialog is purely UI state — it doesn't know about the store.
//
// Implemented with AccessibleDialog (focus trap, ESC, body-scroll
// lock, return-focus) so keyboard + screen-reader users get the
// expected modal behavior for free.

import { useEffect, useMemo, useRef, useState } from "react";
import { CalendarClock, ChevronDown, MapPin, UserCheck } from "lucide-react";
import { AccessibleDialog } from "@/components/ui/AccessibleDialog";
import { cn } from "@/lib/utils";

export type TeamCceo = {
  staffId: string;
  name: string;
  initials: string;
  region: string;
  status?: "On Track" | "At Risk" | "Behind";
  // When true, the demo viewer can sign in as this CCEO to see the
  // assignment land on their plan. The picker surfaces this so the
  // demo path is unambiguous.
  isDemoLoggable?: boolean;
};

export type AssignmentSubmit = {
  cceo: TeamCceo;
  dueDate: string; // YYYY-MM-DD
  note?: string;
};

// Suggest a sensible default deadline. We pick "7 working days from
// today" (skipping weekends) since most follow-up visits are scheduled
// within a working week.
function defaultDeadline(): string {
  const d = new Date();
  let added = 0;
  while (added < 7) {
    d.setDate(d.getDate() + 1);
    const day = d.getDay();
    if (day !== 0 && day !== 6) added += 1; // skip Sun/Sat
  }
  return d.toISOString().slice(0, 10);
}

export function AssignFollowUpDialog({
  open,
  onClose,
  onSubmit,
  team,
  schoolName,
  schoolDistrict,
  recommendedAction,
  defaultCceoStaffId,
}: {
  open: boolean;
  onClose: () => void;
  onSubmit: (s: AssignmentSubmit) => void;
  team: TeamCceo[];
  schoolName: string;
  schoolDistrict: string;
  recommendedAction: string;
  defaultCceoStaffId?: string;
}) {
  // Pre-select either the row's nominal CCEO (if they're loggable) or
  // the first demo-loggable team member so the demo path is one click.
  const initialPick = useMemo(() => {
    if (defaultCceoStaffId) {
      const match = team.find((t) => t.staffId === defaultCceoStaffId);
      if (match) return match.staffId;
    }
    return team.find((t) => t.isDemoLoggable)?.staffId ?? team[0]?.staffId ?? "";
  }, [team, defaultCceoStaffId]);

  const [pickedStaffId, setPickedStaffId] = useState(initialPick);
  const [dueDate, setDueDate] = useState(defaultDeadline());
  const [note, setNote] = useState("");

  // Re-sync default selection when the dialog re-opens for a new row.
  // Migrate to a `key`-prop remount on the parent during the React-19
  // sweep so this becomes structural rather than effect-driven.
  useEffect(() => {
    if (open) {
      /* eslint-disable react-hooks/set-state-in-effect */
      setPickedStaffId(initialPick);
      setDueDate(defaultDeadline());
      setNote("");
      /* eslint-enable react-hooks/set-state-in-effect */
    }
  }, [open, initialPick]);

  const confirmRef = useRef<HTMLButtonElement>(null);
  const todayIso = new Date().toISOString().slice(0, 10);
  const picked = team.find((t) => t.staffId === pickedStaffId);

  function handleSubmit() {
    if (!picked) return;
    onSubmit({ cceo: picked, dueDate, note: note.trim() || undefined });
  }

  return (
    <AccessibleDialog
      open={open}
      onClose={onClose}
      title="Assign follow-up"
      description={`${schoolName} · ${schoolDistrict}`}
      size="md"
      initialFocusRef={confirmRef}
      footer={
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="btn btn-sm"
          >
            Cancel
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={handleSubmit}
            disabled={!picked}
            className="btn btn-sm btn-primary inline-flex items-center gap-1.5"
          >
            <UserCheck size={12} />
            Send to {picked?.name.split(" ")[0] ?? "team"}
          </button>
        </div>
      }
    >
      <div className="space-y-4">
        {/* Recommended action — read-only context block so the PL can
            decide the right CCEO without scrolling back to the row. */}
        <div className="rounded-lg bg-[var(--color-edify-soft)]/50 border border-[var(--color-edify-border)] px-3 py-2">
          <div className="text-[var(--text-tiny)] font-bold uppercase tracking-wide muted">
            Recommended action
          </div>
          <div className="text-[var(--text-body)] mt-0.5">{recommendedAction}</div>
        </div>

        {/* CCEO picker */}
        <fieldset>
          <legend className="text-[var(--text-caption)] font-bold uppercase tracking-wide muted mb-2 inline-flex items-center gap-1.5">
            <UserCheck size={11} />
            Assign to
          </legend>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {team.map((m) => {
              const isPicked = m.staffId === pickedStaffId;
              return (
                <label
                  key={m.staffId}
                  className={cn(
                    "flex items-center gap-2.5 px-3 py-2 rounded-lg border cursor-pointer transition-colors",
                    isPicked
                      ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)]/40 ring-1 ring-[var(--color-edify-primary)]/40"
                      : "border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/30",
                  )}
                >
                  <input
                    type="radio"
                    name="cceo-pick"
                    value={m.staffId}
                    checked={isPicked}
                    onChange={() => setPickedStaffId(m.staffId)}
                    className="sr-only"
                  />
                  <span
                    className={cn(
                      "h-7 w-7 rounded-full grid place-items-center text-[var(--text-tiny)] font-bold shrink-0",
                      isPicked
                        ? "bg-[var(--color-edify-primary)] text-white"
                        : "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
                    )}
                  >
                    {m.initials}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[var(--text-body)] font-semibold truncate leading-tight">
                      {m.name}
                    </span>
                    <span className="block text-[var(--text-tiny)] muted leading-tight inline-flex items-center gap-1">
                      <MapPin size={9} />
                      {m.region}
                      {m.isDemoLoggable && (
                        <span className="ml-1 text-[var(--color-edify-primary)] font-semibold">
                          · demo login
                        </span>
                      )}
                    </span>
                  </span>
                  {isPicked && (
                    <span className="text-[var(--color-edify-primary)] shrink-0">
                      <ChevronDown size={14} className="rotate-[-90deg]" />
                    </span>
                  )}
                </label>
              );
            })}
          </div>
        </fieldset>

        {/* Deadline */}
        <div>
          <label
            htmlFor="assign-deadline"
            className="text-[var(--text-caption)] font-bold uppercase tracking-wide muted mb-1.5 inline-flex items-center gap-1.5"
          >
            <CalendarClock size={11} />
            Deadline
          </label>
          <input
            id="assign-deadline"
            type="date"
            min={todayIso}
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
            className="block w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[var(--text-body)] font-semibold focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
          <p className="text-[var(--text-tiny)] muted mt-1">
            Default: 7 working days from today. The CCEO sees a red chip when overdue.
          </p>
        </div>

        {/* Optional note */}
        <div>
          <label
            htmlFor="assign-note"
            className="text-[var(--text-caption)] font-bold uppercase tracking-wide muted mb-1.5 block"
          >
            Note <span className="font-normal muted">(optional)</span>
          </label>
          <input
            id="assign-note"
            type="text"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="e.g. Partner visit next week — front-load this one"
            maxLength={120}
            className="block w-full h-10 px-3 rounded-lg border border-[var(--color-edify-border)] bg-white text-[var(--text-body)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
        </div>
      </div>
    </AccessibleDialog>
  );
}

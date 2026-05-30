"use client";

import { useEffect, useId, useRef, useState } from "react";
import { AlertTriangle, Camera, Send, X } from "lucide-react";
import type { DebriefBarrier } from "@/lib/field-intelligence-mock";
import type { RealtimeBlocker } from "@/lib/cceo-execution-store";
import { cn } from "@/lib/utils";
import { useDialogA11y } from "@/components/ui/useDialogA11y";

// RealtimeBlockerModal — quick, four-tap flag the CCEO raises during the
// day (not at end-of-day debrief). Goes straight to the PL's Team Daily
// Debriefs card with a "raised live" badge.

const BLOCKER_OPTIONS: { value: DebriefBarrier | "Other"; label: string }[] = [
  { value: "School Unavailable",       label: "School unavailable" },
  { value: "School Closed",            label: "School closed" },
  { value: "Headteacher Unavailable",  label: "Headteacher unavailable" },
  { value: "Weather / Road Problem",   label: "Weather / road problem" },
  { value: "Transport Issue",          label: "Transport issue" },
  { value: "Route Difficulty",         label: "Route difficulty" },
  { value: "Funding Delay",            label: "Funding delay" },
  { value: "Partner Unavailable",      label: "Partner unavailable" },
  { value: "Salesforce Issue",         label: "Salesforce issue" },
  { value: "Evidence Upload Issue",    label: "Evidence upload issue" },
  { value: "Staff Sickness",           label: "Staff sickness" },
  { value: "Public Holiday / Blocked Day", label: "Public holiday / blocked day" },
  { value: "Other",                    label: "Other" },
];

export function RealtimeBlockerModal({
  open,
  defaultSchoolId,
  defaultSchoolName,
  onClose,
  onSubmit,
}: {
  open:               boolean;
  defaultSchoolId?:   string;
  defaultSchoolName?: string;
  onClose:            () => void;
  onSubmit:           (b: RealtimeBlocker) => void;
}) {
  const [category, setCategory]     = useState<DebriefBarrier | "Other">("School Unavailable");
  const [note, setNote]             = useState("");
  const [photoTaken, setPhotoTaken] = useState(false);

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  useDialogA11y({ open, onClose, containerRef: dialogRef });

  useEffect(() => {
    if (!open) return;
    // Reset form state every time the modal re-opens. Migrate to a
    // `key`-prop remount on the parent during the React-19 sweep so
    // this reset becomes structural rather than effect-driven.
    /* eslint-disable react-hooks/set-state-in-effect */
    setCategory("School Unavailable");
    setNote("");
    setPhotoTaken(false);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [open]);

  if (!open) return null;
  const canSubmit = note.trim().length >= 5;

  function submit() {
    if (!canSubmit) return;
    const blocker: RealtimeBlocker = {
      id:         `BLK-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      raisedAt:   new Date().toISOString().replace("T", " ").slice(0, 16),
      schoolId:   defaultSchoolId,
      schoolName: defaultSchoolName,
      category,
      note:       note.trim(),
      photoTaken,
      status:     "Open",
    };
    onSubmit(blocker);
    onClose();
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-2 sm:p-4"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
        className="bg-white rounded-2xl w-full max-w-md shadow-2xl shadow-black/20 focus:outline-none"
      >
        <header className="border-b border-[var(--color-edify-border)] px-4 py-3 flex items-center gap-3">
          <span className="h-9 w-9 rounded-md bg-amber-100 text-amber-700 grid place-items-center shrink-0">
            <AlertTriangle size={16} />
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-caption muted font-bold uppercase tracking-wide">Flag a blocker</div>
            <h2 id={titleId} className="text-[15px] font-extrabold tracking-tight">
              {defaultSchoolName ?? "Right-now field reality"}
            </h2>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="h-9 w-9 rounded-md hover:bg-[var(--color-edify-soft)]/40 grid place-items-center">
            <X size={16} />
          </button>
        </header>

        <div className="p-4 space-y-3">
          <label className="block">
            <span className="text-caption muted font-bold uppercase tracking-wide">Category</span>
            <select
              aria-label="Blocker category"
              value={category}
              onChange={(e) => setCategory(e.target.value as DebriefBarrier | "Other")}
              className="mt-1 w-full h-10 rounded-xl border border-[var(--color-edify-border)] bg-white px-2 text-body font-semibold focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            >
              {BLOCKER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          </label>

          <label className="block">
            <span className="text-caption muted font-bold uppercase tracking-wide">One-line note (voice-to-text supported)</span>
            <textarea
              aria-label="Blocker note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              rows={3}
              placeholder="e.g. School locked, no contact reachable. Heading back."
              className="mt-1 w-full rounded-xl border border-[var(--color-edify-border)] bg-white p-3 text-body leading-snug focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
            <div className="text-[10px] muted mt-1">{note.trim().length} / 5 chars minimum</div>
          </label>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPhotoTaken((v) => !v)}
              className={cn(
                "h-10 px-3 rounded-xl text-[12px] font-extrabold inline-flex items-center gap-1.5",
                photoTaken
                  ? "bg-emerald-100 text-emerald-700"
                  : "border border-[var(--color-edify-border)] bg-white",
              )}
            >
              <Camera size={13} />
              {photoTaken ? "Photo attached" : "Attach photo (optional)"}
            </button>
          </div>
        </div>

        <footer className="border-t border-[var(--color-edify-border)] px-4 py-3 flex items-center gap-2 flex-wrap">
          <div className="text-caption muted flex-1 min-w-0">
            Sent to your Program Lead immediately. Auto-fills tonight&apos;s daily debrief.
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-extrabold"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={!canSubmit}
            onClick={submit}
            className={cn(
              "h-10 px-4 rounded-xl text-body font-extrabold inline-flex items-center gap-1.5",
              canSubmit
                ? "bg-amber-500 hover:bg-amber-600 text-white shadow-sm shadow-amber-500/25"
                : "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed",
            )}
          >
            <Send size={13} />
            Flag now
          </button>
        </footer>
      </div>
    </div>
  );
}

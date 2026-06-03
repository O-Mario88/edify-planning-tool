"use client";

import { useEffect, useState, type FormEvent } from "react";
import { CalendarPlus, History, User, AlertTriangle, ChevronRight } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { GlassDatePicker } from "@/components/ui/GlassDatePicker";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { Button } from "@/components/ui/Button";
import {
  ACTIVITY_RESCHEDULE_REASONS,
  type PlanItem,
  type PlanItemReschedule,
} from "@/lib/mobile-mock";

// Reschedule a single planned activity (visit, follow-up, in-school
// coaching, or cluster training).
//
// Same audit-trail pattern as cluster meetings: the modal shows what's
// currently scheduled, who proposed it, every prior move, and a form
// to confirm a new date + reason + proposer. Submit fires the parent
// `onSubmit` callback (the parent shows a toast and, in production,
// pushes the change to the activity timeline + notifies the school
// contact and the assigned partner/staff).

export type ActivityRescheduleOutcome = {
  item:       PlanItem;
  newDate:    string;
  reason:     string;
  proposedBy: string;
};

export function RescheduleActivityDrawer({
  open, item, onClose, onSubmit,
}: {
  open: boolean;
  item: PlanItem | null;
  onClose: () => void;
  onSubmit: (outcome: ActivityRescheduleOutcome) => void;
}) {
  const [newDate,    setNewDate]    = useState("");
  const [reason,     setReason]     = useState<string>(ACTIVITY_RESCHEDULE_REASONS[0]);
  const [otherText,  setOtherText]  = useState("");
  const [proposedBy, setProposedBy] = useState("");
  const [error,      setError]      = useState<string | null>(null);

  // Re-seed form when the modal opens on a new item. useEffect so the
  // reset actually runs after state updates settle.
  useEffect(() => {
    if (open && item) {
      setProposedBy(item.proposedBy ?? "Field staff");
      setNewDate("");
      setReason(ACTIVITY_RESCHEDULE_REASONS[0]);
      setOtherText("");
      setError(null);
    }
  }, [open, item]);

  if (!item) return null;

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!newDate) {
      setError("Pick a new date for the activity.");
      return;
    }
    if (!proposedBy.trim()) {
      setError("Name the person proposing the new date.");
      return;
    }
    const resolvedReason = reason === "Other" ? otherText.trim() : reason;
    if (!resolvedReason) {
      setError("Add a short reason so the audit trail has context.");
      return;
    }
    if (!item) return;
    onSubmit({
      item,
      newDate:    formatHumanDate(newDate),
      reason:     resolvedReason,
      proposedBy: proposedBy.trim(),
    });
  }

  const history       = item.reschedules ?? [];
  const reasonOptions = ACTIVITY_RESCHEDULE_REASONS.map((r) => ({ value: r, label: r }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Reschedule · ${item.title}`}
      description={`${item.context} · ${item.weekLabel}`}
      size="lg"
      variant="sheet"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            size="sm"
            Icon={CalendarPlus}
            onClick={() => {
              const form = document.getElementById("activity-reschedule-form") as HTMLFormElement | null;
              form?.requestSubmit();
            }}
          >
            Confirm new date
          </Button>
        </div>
      }
    >
      <form id="activity-reschedule-form" onSubmit={handleSubmit} className="space-y-4">

        {/* Current schedule */}
        <section className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 p-3">
          <div className="text-[10px] uppercase tracking-wider font-extrabold text-[var(--color-edify-muted)]">
            Currently scheduled
          </div>
          <div className="text-[13.5px] font-extrabold mt-0.5">{item.date}</div>
          {item.proposedBy && (
            <div className="text-[11.5px] muted inline-flex items-center gap-1 mt-0.5">
              <User size={10} />
              Set by {item.proposedBy}
            </div>
          )}
        </section>

        {/* Reschedule history */}
        {history.length > 0 && (
          <section>
            <div className="text-[11px] uppercase tracking-wider font-extrabold text-[var(--color-edify-muted)] inline-flex items-center gap-1.5 mb-1.5">
              <History size={11} />
              Already moved {history.length} time{history.length === 1 ? "" : "s"}
            </div>
            <ul className="divide-y divide-[var(--color-edify-divider)] rounded-lg border border-[var(--color-edify-border)] bg-white">
              {history.map((h, i) => <HistoryRow key={i} entry={h} />)}
            </ul>
            {history.length >= 2 && (
              <div className="mt-2 text-[11.5px] text-amber-700 inline-flex items-start gap-1.5">
                <AlertTriangle size={11} className="mt-0.5 shrink-0" />
                <span>This activity has been moved more than once. Consider escalating to your CCEO before booking a third date — or convert it to a different activity type.</span>
              </div>
            )}
          </section>
        )}

        {/* New date form */}
        <section className="space-y-3">
          <div className="flex flex-col gap-1">
            <label className="text-[11.5px] font-semibold text-[var(--color-edify-text)]">
              New date
              <span className="text-rose-600 ml-0.5">*</span>
            </label>
            <GlassDatePicker value={newDate} onChange={setNewDate} placeholder="dd/mm/yyyy" />
            <p className="text-[11px] text-[var(--color-edify-muted)]">
              Pick the date the school + field team have agreed on.
            </p>
          </div>

          <Select
            label="Reason"
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            options={reasonOptions}
            helper="Why is the original date no longer working?"
          />

          {reason === "Other" && (
            <Textarea
              label="Describe the reason"
              required
              rows={2}
              value={otherText}
              onChange={(e) => setOtherText(e.target.value)}
              placeholder="Short, audit-trail-friendly line."
            />
          )}

          <Input
            label="Proposed by"
            required
            value={proposedBy}
            onChange={(e) => setProposedBy(e.target.value)}
            helper="The field officer or supervisor making this call."
          />

          {error && (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              {error}
            </div>
          )}
        </section>
      </form>
    </Modal>
  );
}

function HistoryRow({ entry }: { entry: PlanItemReschedule }) {
  return (
    <li className="px-3 py-2 text-[12px] flex items-start gap-2">
      <ChevronRight size={11} className="mt-0.5 text-[var(--color-edify-muted)] shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="font-semibold">
          <span className="opacity-70 line-through">{entry.from}</span>
          {" → "}
          <span>{entry.to}</span>
        </div>
        <div className="text-[11px] muted leading-snug mt-0.5">
          {entry.reason} · by {entry.movedBy}
          <span className="opacity-60"> · {entry.movedAt}</span>
        </div>
      </div>
    </li>
  );
}

/** "2026-06-20" → "Jun 20, 2026" — matches the rest of the planning surfaces. */
function formatHumanDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[m - 1]} ${d}, ${y}`;
}

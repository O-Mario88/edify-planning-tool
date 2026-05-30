"use client";

import { useMemo, useState, type FormEvent } from "react";
import { CalendarPlus, History, User, AlertTriangle, ChevronRight } from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Textarea } from "@/components/ui/Textarea";
import { Button } from "@/components/ui/Button";
import {
  CLUSTER_MEETING_SLOT_LABEL,
  RESCHEDULE_REASONS,
  type ClusterGap,
  type ClusterMeetingReschedule,
  type ClusterMeetingSlot,
} from "@/lib/planning/planning-gaps-mock";

// Reschedule a single cluster-meeting slot.
//
// The original cluster-meeting date comes from the cluster leader.
// Reality interferes: exam week, weather, the leader is unavailable,
// schools close for a public holiday. This modal captures the new
// date, who proposed it, and why — and appends a history entry so
// the next person who reads the schedule sees the pattern.
//
// Submit is local (demo) — fires a toast via the parent's `onSubmit`
// callback. Production wires the same outcome to a server action that
// pushes the reschedule to the partner + cluster leader notification
// queue and updates the planning timeline.

export type RescheduleOutcome = {
  cluster:    ClusterGap;
  slot:       ClusterMeetingSlot;
  newDate:    string;
  reason:     string;
  proposedBy: string;
};

export type RescheduleContext = {
  cluster: ClusterGap;
  slot:    ClusterMeetingSlot;
};

export function RescheduleClusterMeetingDrawer({
  open, context, onClose, onSubmit,
}: {
  open: boolean;
  context: RescheduleContext | null;
  onClose: () => void;
  onSubmit: (outcome: RescheduleOutcome) => void;
}) {
  // Pull current date + proposer + history for the active slot.
  const slotData = useMemo(() => {
    if (!context) return null;
    const { cluster, slot } = context;
    const map = {
      first:  { date: cluster.firstMeetingDate,  by: cluster.firstMeetingProposedBy,  history: cluster.firstMeetingReschedules  },
      second: { date: cluster.secondMeetingDate, by: cluster.secondMeetingProposedBy, history: cluster.secondMeetingReschedules },
      third:  { date: cluster.thirdMeetingDate,  by: cluster.thirdMeetingProposedBy,  history: cluster.thirdMeetingReschedules  },
      sit:    { date: cluster.sitDate,           by: cluster.sitProposedBy,           history: cluster.sitReschedules           },
    } as const;
    return map[slot];
  }, [context]);

  const [newDate,    setNewDate]    = useState("");
  const [reason,     setReason]     = useState<string>(RESCHEDULE_REASONS[0]);
  const [otherText,  setOtherText]  = useState("");
  const [proposedBy, setProposedBy] = useState("");
  const [error,      setError]      = useState<string | null>(null);

  // Re-seed proposer when opening for a new context.
  useMemo(() => {
    if (open && slotData) {
      setProposedBy(slotData.by ?? "");
      setNewDate("");
      setReason(RESCHEDULE_REASONS[0]);
      setOtherText("");
      setError(null);
    }
  }, [open, slotData]);

  if (!context || !slotData) return null;

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);
    if (!newDate) {
      setError("Pick a new date for the meeting.");
      return;
    }
    if (!proposedBy.trim()) {
      setError("Name the person proposing the new date — usually the cluster leader.");
      return;
    }
    const resolvedReason = reason === "Other" ? otherText.trim() : reason;
    if (!resolvedReason) {
      setError("Add a short reason so the audit trail has context.");
      return;
    }
    if (!context) return;
    onSubmit({
      cluster:    context.cluster,
      slot:       context.slot,
      newDate:    formatHumanDate(newDate),
      reason:     resolvedReason,
      proposedBy: proposedBy.trim(),
    });
  }

  const slotLabel    = CLUSTER_MEETING_SLOT_LABEL[context.slot];
  const history      = slotData.history ?? [];
  const reasonOptions = RESCHEDULE_REASONS.map((r) => ({ value: r, label: r }));

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Reschedule ${slotLabel}`}
      description={`${context.cluster.clusterName} · ${context.cluster.district}`}
      size="lg"
      variant="sheet"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button
            size="sm"
            Icon={CalendarPlus}
            onClick={() => {
              // Synthesize a form submit to share validation.
              const form = document.getElementById("reschedule-form") as HTMLFormElement | null;
              form?.requestSubmit();
            }}
          >
            Confirm new date
          </Button>
        </div>
      }
    >
      <form id="reschedule-form" onSubmit={handleSubmit} className="space-y-4">

        {/* Current schedule */}
        <section className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 p-3">
          <div className="text-[10px] uppercase tracking-wider font-extrabold text-[var(--color-edify-muted)]">
            Current schedule
          </div>
          {slotData.date ? (
            <>
              <div className="text-[13.5px] font-extrabold mt-0.5">{slotData.date}</div>
              {slotData.by && (
                <div className="text-[11.5px] muted inline-flex items-center gap-1 mt-0.5">
                  <User size={10} />
                  Proposed by {slotData.by}
                </div>
              )}
            </>
          ) : (
            <div className="text-[12px] muted mt-0.5">No date currently on record.</div>
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
                <span>This meeting has been moved more than once. Consider escalating to the CCEO before booking a third date.</span>
              </div>
            )}
          </section>
        )}

        {/* New date form */}
        <section className="space-y-3">
          <Input
            label="New date"
            type="date"
            required
            value={newDate}
            onChange={(e) => setNewDate(e.target.value)}
            helper="Pick the date the cluster leader has now proposed."
          />

          <Select
            label="Reason"
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            options={reasonOptions}
            helper="What's interfering with the original date?"
          />

          {reason === "Other" && (
            <Textarea
              label="Describe the reason"
              required
              rows={2}
              value={otherText}
              onChange={(e) => setOtherText(e.target.value)}
              placeholder="Short, audit-trail-friendly line — what's the actual blocker?"
            />
          )}

          <Input
            label="Proposed by"
            required
            value={proposedBy}
            onChange={(e) => setProposedBy(e.target.value)}
            helper="Cluster leader by default. Override if a CCEO or partner is making the call instead."
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

function HistoryRow({ entry }: { entry: ClusterMeetingReschedule }) {
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

/**
 * Convert "2026-06-20" (HTML date input) to "Jun 20, 2026" (human display).
 * Keeps the format consistent with the rest of the planning surfaces.
 */
function formatHumanDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[m - 1]} ${d}, ${y}`;
}

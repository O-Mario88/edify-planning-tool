"use client";

// Inline cluster-meeting scheduler — used by the partner (their delegated
// clusters) and by Edify staff (Edify-organised training on any cluster).
// The server action derives the organiser from the signed-in user's role.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { CalendarPlus, Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { scheduleClusterMeetingAction } from "@/lib/actions/cluster-actions";
import { GlassDatePicker } from "@/components/ui/GlassDatePicker";

const KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "cluster_meeting", label: "Cluster Meeting" },
  { value: "cluster_training", label: "Cluster Training" },
  { value: "sit", label: "School Improvement Training (SIT)" },
  { value: "training", label: "Targeted Cluster Training" },
];

export function ClusterMeetingScheduler({
  clusterId,
  buttonLabel = "Schedule meeting",
  defaultKind,
  lockKind = false,
}: {
  clusterId: string;
  buttonLabel?: string;
  /** Pre-select a kind (e.g. staff "training" for Edify-organised). */
  defaultKind?: string;
  /** Hide the kind picker (single fixed kind). */
  lockKind?: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();
  const [kind, setKind] = useState(defaultKind ?? "cluster_meeting");
  const [date, setDate] = useState("");
  const [participants, setParticipants] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit() {
    setError(null);
    if (!date) { setError("Pick a date."); return; }
    startTransition(async () => {
      const res = await scheduleClusterMeetingAction(
        clusterId,
        kind as "cluster_meeting" | "cluster_training" | "sit" | "training",
        date,
        participants ? Number(participants) : undefined,
      );
      if (!res.ok) {
        setError(res.reason === "FORBIDDEN" ? "You can't schedule for this cluster." : "Failed to schedule.");
        return;
      }
      setOpen(false);
      setDate("");
      setParticipants("");
      router.refresh();
    });
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1.5 h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60 transition-colors"
      >
        <CalendarPlus size={12} className="text-[var(--color-edify-primary)]" /> {buttonLabel}
      </button>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded-lg border border-[var(--color-edify-primary)]/40 bg-[var(--color-edify-soft)]/30 p-1.5">
      {!lockKind && (
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="h-8 px-2 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px]"
        >
          {KIND_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      )}
      <GlassDatePicker value={date} onChange={setDate} />
      <input
        value={participants}
        onChange={(e) => setParticipants(e.target.value.replace(/\D/g, ""))}
        placeholder="Participants"
        className="h-8 px-2 w-24 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px]"
      />
      <button
        type="button"
        onClick={submit}
        disabled={pending}
        className={cn("inline-flex items-center gap-1 h-8 px-2.5 rounded-md text-[11.5px] font-semibold text-white",
          pending ? "bg-slate-300" : "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)]")}
      >
        <Check size={12} /> Schedule
      </button>
      <button type="button" onClick={() => { setOpen(false); setError(null); }} className="text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]">
        <X size={14} />
      </button>
      {error && <span className="text-[10.5px] text-rose-600 w-full">{error}</span>}
    </div>
  );
}

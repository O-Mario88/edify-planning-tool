"use client";

import { useState, useTransition } from "react";
import { Calendar, Loader2 } from "lucide-react";
import { csrfHeaders } from "@/lib/csrf-client";
import { useRouter } from "next/navigation";

/** Inline schedule control for partner-assigned activities awaiting a date. */
export function PartnerScheduleActions({
  activityId,
  status,
}: {
  activityId: string;
  status: string;
}) {
  const router = useRouter();
  const [date, setDate] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, start] = useTransition();

  if (!["assigned_to_partner", "planned", "scheduled", "returned"].includes(status)) {
    return null;
  }

  const submit = () => {
    if (!date) {
      setError("Pick a delivery date.");
      return;
    }
    setError(null);
    start(async () => {
      try {
        const res = await fetch(`/api/partners/me/activities/${encodeURIComponent(activityId)}/schedule`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json", ...csrfHeaders() },
          body: JSON.stringify({ scheduledDate: date }),
        });
        const j = await res.json();
        if (!res.ok || !j.live) {
          setError(j.error || "Could not schedule");
          return;
        }
        router.refresh();
      } catch {
        setError("Could not reach the server");
      }
    });
  };

  return (
    <div className="flex flex-col sm:flex-row sm:items-center gap-2 mt-2">
      <input
        type="date"
        value={date}
        onChange={(e) => setDate(e.target.value)}
        className="h-8 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px]"
        aria-label="Delivery date"
      />
      <button
        type="button"
        onClick={submit}
        disabled={pending}
        className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg bg-[var(--color-edify-primary)] text-white text-[11px] font-bold disabled:opacity-60"
      >
        {pending ? <Loader2 size={12} className="animate-spin" /> : <Calendar size={12} />}
        Set delivery date
      </button>
      {error && <p className="text-[11px] text-rose-600">{error}</p>}
    </div>
  );
}

"use client";

// My Plan — the living list of the user's planned activities, with row
// actions that close the plan-as-list loop: Reschedule, Reassign, Cancel/Defer,
// Complete. Backend-sourced rows call /api/activities/*; store rows use the
// in-memory server actions (dev fallback).

import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CalendarClock, UserCog, Ban, PauseCircle, CheckCircle2, MapPin, Footprints, GraduationCap, Paperclip } from "lucide-react";
import { cn } from "@/lib/utils";
import { csrfHeaders } from "@/lib/csrf-client";
import { rescheduleActivity, reassignActivity, cancelActivity, deferActivity, completeActivity } from "@/lib/actions/my-plan-actions";
import { RESCHEDULE_SLIP_LIMIT, reschedulesRemaining } from "@/lib/planning/planning-capacity";

const REASONS = [
  "School closed / public holiday", "Head teacher unavailable", "Weather / road impassable",
  "Staff / partner unable to travel", "Funds not yet received", "Conflicting cluster meeting", "Other",
];

export type MyPlanRow = {
  id: string;
  title: string;
  schoolId?: string;
  schoolName?: string;
  kind: string;
  scheduledDate?: string;
  status: string;
  deliveryType?: "staff" | "partner";
  partnerName?: string;
  rescheduleCount?: number;
  lastReason?: string;
  /** Where this row was loaded from — drives which mutation path runs. */
  source?: "backend" | "store";
};

const STATUS_TONE: Record<string, string> = {
  Planned: "bg-slate-100 text-slate-600",
  Completed: "bg-emerald-100 text-emerald-700",
  Cancelled: "bg-rose-100 text-rose-700",
  Deferred: "bg-amber-100 text-amber-700",
};

export function MyPlanList({ rows }: { rows: MyPlanRow[] }) {
  if (!rows.length) {
    return <div className="card p-8 text-center text-[12px] muted italic">Nothing planned yet — schedule a visit or training from a school or cluster.</div>;
  }
  return <div className="space-y-2">{rows.map((r) => <PlanRow key={r.id} row={r} />)}</div>;
}

function backendPost(id: string, action: string, body: Record<string, unknown> = {}) {
  return fetch(`/api/activities/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", ...csrfHeaders() },
    body: JSON.stringify(body),
  });
}

function PlanRow({ row }: { row: MyPlanRow }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [status, setStatus] = useState(row.status);
  const [delivery, setDelivery] = useState(row.deliveryType ?? "staff");
  const [moves, setMoves] = useState(row.rescheduleCount ?? 0);
  const [date, setDate] = useState(row.scheduledDate ?? "");
  const [mode, setMode] = useState<null | "reschedule" | "cancel" | "defer">(null);
  const [reason, setReason] = useState(REASONS[0]);
  const [newDate, setNewDate] = useState("");
  const [error, setError] = useState<string | null>(null);

  const isBackend = row.source === "backend";
  const terminal = status === "Completed" || status === "Cancelled";
  const atLimit = moves >= RESCHEDULE_SLIP_LIMIT;
  const Icon = /training|meeting/i.test(row.kind) ? GraduationCap : Footprints;

  function run(
    fn: () => Promise<{ ok: boolean; reason?: string; message?: string } | Response>,
    after: () => void,
  ) {
    setError(null);
    start(async () => {
      try {
        const r = await fn();
        if (r instanceof Response) {
          const j = await r.json();
          if (!j.live) { setError(j.error || "The action was rejected"); return; }
        } else if (!r.ok) {
          setError(r.message || (r.reason === "SLIP_LIMIT" ? `Slip limit (${RESCHEDULE_SLIP_LIMIT}) reached.` : "The action was rejected"));
          return;
        }
        after();
        setMode(null);
        window.setTimeout(() => router.refresh(), 220);
      } catch {
        setError("Could not reach the server");
      }
    });
  }

  return (
    <div className="rounded-xl border border-[var(--color-edify-divider)] bg-white">
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/70 text-[var(--color-edify-primary)] shrink-0"><Icon size={14} /></span>
        <div className="min-w-0 flex-1">
          <div className="text-[12.5px] font-extrabold truncate">{row.title}</div>
          <div className="text-[11px] muted inline-flex items-center gap-2 flex-wrap">
            {row.schoolName && <span className="inline-flex items-center gap-0.5"><MapPin size={9} />{row.schoolName}</span>}
            {date && <span className="tabular">{date}</span>}
            <span className="inline-flex items-center gap-1">{delivery === "partner" ? "Partner" : "Staff"}{delivery === "partner" && row.partnerName ? ` · ${row.partnerName}` : ""}</span>
            {moves > 0 && <span className="text-amber-700">moved {moves}×</span>}
          </div>
        </div>
        <span className={cn("text-[10px] font-bold px-1.5 py-[2px] rounded-full shrink-0", STATUS_TONE[status] ?? "bg-slate-100 text-slate-600")}>{status}</span>
        <Link href={`/activities/${row.id}/evidence`} title="Upload / review evidence"
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-bold border border-[var(--color-edify-border)] muted hover:bg-[var(--color-edify-soft)]/40 shrink-0">
          <Paperclip size={12} /> Evidence
        </Link>
      </div>

      {error && (
        <p className="px-3 pb-1 text-[11px] text-rose-600 font-semibold">{error}</p>
      )}

      {/* Row actions */}
      {!terminal && (
        <div className="flex items-center gap-1.5 px-3 pb-2.5 flex-wrap">
          <ActionBtn Icon={CalendarClock} label="Reschedule" disabled={pending || atLimit} title={atLimit ? `Slip limit (${RESCHEDULE_SLIP_LIMIT}) reached — escalate or convert` : undefined} onClick={() => setMode(mode === "reschedule" ? null : "reschedule")} />
          <ActionBtn Icon={UserCog} label={delivery === "partner" ? "Reassign to Staff" : "Reassign to Partner"} disabled={pending}
            onClick={() => run(
              () => isBackend
                ? backendPost(row.id, "reassign", { deliveryType: delivery === "partner" ? "staff" : "partner" })
                : reassignActivity(row.id, delivery === "partner" ? "staff" : "partner", delivery === "partner" ? undefined : "Partner"),
              () => setDelivery(delivery === "partner" ? "staff" : "partner"),
            )} />
          <ActionBtn Icon={PauseCircle} label="Defer" disabled={pending} onClick={() => setMode(mode === "defer" ? null : "defer")} />
          <ActionBtn Icon={Ban} label="Cancel" disabled={pending} tone="danger" onClick={() => setMode(mode === "cancel" ? null : "cancel")} />
          <ActionBtn Icon={CheckCircle2} label="Complete" disabled={pending} tone="good"
            onClick={() => run(
              () => isBackend ? backendPost(row.id, "complete", {}) : completeActivity(row.id),
              () => setStatus("Completed"),
            )} />
        </div>
      )}

      {/* Inline reschedule form (date + reason, slip-limit aware) */}
      {mode === "reschedule" && (
        <InlinePanel>
          <input type="date" value={newDate} onChange={(e) => setNewDate(e.target.value)} className="rounded-md border border-[var(--color-edify-border)] px-2 py-1 text-[11.5px]" />
          <ReasonSelect reason={reason} setReason={setReason} />
          <span className="text-[10.5px] muted">{reschedulesRemaining(moves)} left</span>
          <ConfirmBtn disabled={pending || !newDate} onClick={() => run(
            () => isBackend
              ? backendPost(row.id, "reschedule", { scheduledDate: newDate, reason })
              : rescheduleActivity(row.id, newDate, reason),
            () => { setDate(new Date(newDate).toLocaleDateString()); setMoves(moves + 1); setStatus("Planned"); },
          )} />
        </InlinePanel>
      )}
      {(mode === "cancel" || mode === "defer") && (
        <InlinePanel>
          <span className="text-[11px] font-bold">{mode === "cancel" ? "Cancel" : "Defer"} — reason:</span>
          <ReasonSelect reason={reason} setReason={setReason} />
          <ConfirmBtn disabled={pending} onClick={() => run(
            () => isBackend
              ? backendPost(row.id, mode === "cancel" ? "cancel" : "defer", { reason })
              : (mode === "cancel" ? cancelActivity(row.id, reason) : deferActivity(row.id, reason)),
            () => setStatus(mode === "cancel" ? "Cancelled" : "Deferred"),
          )} />
        </InlinePanel>
      )}
    </div>
  );
}

function ActionBtn({ Icon, label, onClick, disabled, tone, title }: { Icon: typeof Footprints; label: string; onClick: () => void; disabled?: boolean; tone?: "danger" | "good"; title?: string }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} title={title}
      className={cn("inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-bold border transition-colors disabled:opacity-40 disabled:cursor-not-allowed",
        tone === "danger" ? "border-rose-200 text-rose-700 hover:bg-rose-50" : tone === "good" ? "border-emerald-200 text-emerald-700 hover:bg-emerald-50" : "border-[var(--color-edify-border)] muted hover:bg-[var(--color-edify-soft)]/40")}>
      <Icon size={12} /> {label}
    </button>
  );
}

function InlinePanel({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center gap-2 flex-wrap px-3 pb-2.5 pt-1 border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/20">{children}</div>;
}

function ReasonSelect({ reason, setReason }: { reason: string; setReason: (r: string) => void }) {
  return (
    <select value={reason} onChange={(e) => setReason(e.target.value)} className="rounded-md border border-[var(--color-edify-border)] px-2 py-1 text-[11.5px] max-w-[230px]">
      {REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
    </select>
  );
}

function ConfirmBtn({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  return <button type="button" onClick={onClick} disabled={disabled} className="rounded-md bg-[var(--color-edify-primary)] text-white px-2.5 py-1 text-[11px] font-extrabold disabled:opacity-40">Confirm</button>;
}

"use client";

// My Plan — the five-section scheduled-work list (spec §10):
// Due Today · Planned This Week · Planned This Month · Waiting on Me ·
// Rescheduled / Needs Attention. The page derives the sections server-side
// (src/lib/planning/my-plan-sections.ts); this component renders the cards and
// owns the ONE next-action button per card. Actions reuse the existing paths:
// store rows call the my-plan-actions server actions; backend rows POST to
// /api/activities/:id/:action (the enforced state machine). Either way the
// row refreshes via router.refresh().

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  CalendarClock, CheckCircle2, Footprints, GraduationCap, MapPin, Hash,
  Sun, CalendarDays, CalendarRange, Hourglass, RotateCcw, Upload, Wallet, X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { completeActivity, rescheduleActivity } from "@/lib/actions/my-plan-actions";
import { RESCHEDULE_SLIP_LIMIT, reschedulesRemaining } from "@/lib/planning/planning-capacity";
import { weekMonthLabel, type MyPlanItem, type MyPlanSection, type MyPlanSectionKey } from "@/lib/planning/my-plan-sections";

const RESCHEDULE_REASONS = [
  "School closed / public holiday", "Head teacher unavailable", "Weather / road impassable",
  "Staff / partner unable to travel", "Funds not yet received", "Conflicting cluster meeting", "Other",
];

const SECTION_ICON: Record<MyPlanSectionKey, typeof Sun> = {
  dueToday: Sun, thisWeek: CalendarDays, thisMonth: CalendarRange,
  waitingOnMe: Hourglass, needsAttention: RotateCcw,
};

const FUNDING_TONE: Record<NonNullable<MyPlanItem["funding"]>, string> = {
  Requested: "bg-slate-100 text-slate-600",
  Approved: "bg-sky-100 text-sky-700",
  Disbursed: "bg-emerald-100 text-emerald-700",
};

const ugx = (cents: number) => `UGX ${Math.round(cents / 100).toLocaleString()}`;

export function MyPlanSections({ sections, live }: { sections: MyPlanSection[]; live: boolean }) {
  const total = sections.reduce((n, s) => n + s.items.length, 0);
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <p className="text-[11.5px] muted">
          {total} scheduled {total === 1 ? "activity" : "activities"} still in play
          {live && <span className="ml-2 inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200 align-middle">Live · backend</span>}
        </p>
        <Link href="/completed-activities" className="text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">
          View Completed Log →
        </Link>
      </div>

      {sections.map((s) => {
        const Icon = SECTION_ICON[s.key];
        return (
          <section key={s.key} className="space-y-1.5">
            <h2 className="text-[12px] font-extrabold uppercase tracking-wide muted inline-flex items-center gap-1.5">
              <Icon size={13} className={s.key === "needsAttention" && s.items.length ? "text-amber-600" : undefined} />
              {s.title}
              <span className="rounded-full bg-[var(--color-edify-soft)] px-1.5 py-px text-[10px] font-bold text-[var(--color-edify-primary)]">{s.items.length}</span>
            </h2>
            {s.items.length === 0 ? (
              <p className="text-[11.5px] muted italic pl-0.5">{s.emptyCopy}</p>
            ) : (
              <div className="space-y-2">{s.items.map((i) => <PlanItemCard key={i.id} item={i} sectionKey={s.key} />)}</div>
            )}
          </section>
        );
      })}
    </div>
  );
}

// ── Card ─────────────────────────────────────────────────────────────

function PlanItemCard({ item, sectionKey }: { item: MyPlanItem; sectionKey: MyPlanSectionKey }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [mode, setMode] = useState<null | "complete" | "reschedule">(null);
  const [field, setField] = useState("");
  const [reason, setReason] = useState(RESCHEDULE_REASONS[0]);
  const [error, setError] = useState<string | null>(null);

  const Icon = /training|meeting/i.test(item.typeLabel) ? GraduationCap : Footprints;

  // Date display: exact for trainings/cluster meetings, week·month for visits.
  const dateLabel = item.exactDate
    ? item.dateIso ? new Date(item.dateIso).toLocaleDateString("en-UG", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }) : "Date TBD"
    : (weekMonthLabel(item) ?? "Not yet dated");

  async function run(fn: () => Promise<{ ok: boolean; reason?: string; message?: string } | Response>) {
    setError(null);
    start(async () => {
      try {
        const r = await fn();
        if (r instanceof Response) {
          const j = await r.json();
          if (!j.live) { setError(j.error || "The action was rejected"); return; }
        } else if (!r.ok) {
          setError(r.message || (r.reason === "SLIP_LIMIT" ? `Slip limit (${RESCHEDULE_SLIP_LIMIT}) reached — escalate or deliver.` : "The action was rejected"));
          return;
        }
        setMode(null); setField("");
        router.refresh();
      } catch {
        setError("Could not reach the server");
      }
    });
  }

  const doComplete = () =>
    run(() => item.source === "backend"
      ? fetch(`/api/activities/${item.id}/complete`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(field.trim() ? { salesforceId: field.trim() } : {}) })
      : completeActivity(item.id, field.trim() || undefined));

  const doReschedule = () =>
    run(() => item.source === "backend"
      ? fetch(`/api/activities/${item.id}/reschedule`, { method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ scheduledDate: field, reason }) })
      : rescheduleActivity(item.id, field, reason));

  return (
    <div className="rounded-xl border border-[var(--color-edify-divider)] bg-white">
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <span className="grid place-items-center h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/70 text-[var(--color-edify-primary)] shrink-0"><Icon size={14} /></span>
        <div className="min-w-0 flex-1">
          <div className="text-[12.5px] font-extrabold truncate">{item.typeLabel}</div>
          <div className="text-[11px] muted inline-flex items-center gap-2 flex-wrap">
            <span className="inline-flex items-center gap-0.5"><MapPin size={9} />{item.entityName}</span>
            <span className="inline-flex items-center gap-0.5 tabular"><CalendarClock size={9} />{dateLabel}</span>
            {item.costCents != null && <span className="inline-flex items-center gap-0.5 tabular"><Wallet size={9} />{ugx(item.costCents)}</span>}
            {item.rescheduleCount > 0 && (
              <span className={cn("font-bold", item.atSlipLimit ? "text-rose-700" : "text-amber-700")}>
                moved {item.rescheduleCount}×{item.atSlipLimit ? " · slip limit" : ""}
              </span>
            )}
          </div>
          {sectionKey === "needsAttention" && item.lastReason && (
            <div className="text-[10.5px] muted italic truncate">Last reason: {item.lastReason}</div>
          )}
        </div>
        <span className="flex flex-col items-end gap-1 shrink-0">
          {item.funding && (
            <span className={cn("text-[9.5px] font-bold px-1.5 py-[2px] rounded-full uppercase tracking-wide", FUNDING_TONE[item.funding])}>
              Funds {item.funding.toLowerCase()}
            </span>
          )}
          <NextActionButton item={item} pending={pending} mode={mode} setMode={(m) => { setMode(m); setField(""); setError(null); }} />
        </span>
      </div>

      {/* Inline panels — one per next action that needs input */}
      {mode === "complete" && (
        <InlinePanel>
          <Hash size={11} className="muted shrink-0" />
          <input
            autoFocus value={field} onChange={(e) => setField(e.target.value)}
            placeholder={item.nextAction === "enterSalesforceId" ? "Salesforce ID (SV- or TS-)" : "Salesforce ID (optional)"}
            className="flex-1 min-w-[160px] rounded-md border border-[var(--color-edify-border)] px-2 py-1 text-[11.5px]"
          />
          <ConfirmBtn disabled={pending || (item.nextAction === "enterSalesforceId" && !field.trim())} onClick={doComplete} />
          <CloseBtn onClick={() => { setMode(null); setField(""); }} />
        </InlinePanel>
      )}
      {mode === "reschedule" && (
        <InlinePanel>
          <input type="date" value={field} onChange={(e) => setField(e.target.value)} className="rounded-md border border-[var(--color-edify-border)] px-2 py-1 text-[11.5px]" />
          <select value={reason} onChange={(e) => setReason(e.target.value)} className="rounded-md border border-[var(--color-edify-border)] px-2 py-1 text-[11.5px] max-w-[210px]">
            {RESCHEDULE_REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <span className="text-[10.5px] muted">{reschedulesRemaining(item.rescheduleCount)} move{reschedulesRemaining(item.rescheduleCount) === 1 ? "" : "s"} left</span>
          <ConfirmBtn disabled={pending || !field} onClick={doReschedule} />
          <CloseBtn onClick={() => { setMode(null); setField(""); }} />
        </InlinePanel>
      )}
      {error && <div className="px-3 pb-2 text-[11px] text-rose-600 font-semibold">{error}</div>}
    </div>
  );
}

// ── The ONE next-action button ───────────────────────────────────────

function NextActionButton({ item, pending, mode, setMode }: {
  item: MyPlanItem;
  pending: boolean;
  mode: null | "complete" | "reschedule";
  setMode: (m: null | "complete" | "reschedule") => void;
}) {
  const base = "inline-flex items-center gap-1 h-7 px-2.5 rounded-lg text-[10.5px] font-bold transition-colors disabled:opacity-40 disabled:cursor-not-allowed";
  const primary = cn(base, "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white");
  const outline = cn(base, "border border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/40");

  switch (item.nextAction) {
    case "enterSalesforceId":
      return (
        <button type="button" disabled={pending} onClick={() => setMode(mode === "complete" ? null : "complete")} className={primary}>
          <Hash size={11} /> Enter Salesforce ID
        </button>
      );
    case "uploadEvidence":
      // No activity-level upload action exists yet — the evidence flow lives
      // with the completed/verification surfaces.
      return (
        <Link href="/completed-activities" className={primary}>
          <Upload size={11} /> Upload Evidence
        </Link>
      );
    case "complete":
      return (
        <button type="button" disabled={pending} onClick={() => setMode(mode === "complete" ? null : "complete")} className={primary}>
          <CheckCircle2 size={11} /> Complete
        </button>
      );
    case "reschedule":
      return (
        <button type="button" disabled={pending || item.atSlipLimit} title={item.atSlipLimit ? `Slip limit (${RESCHEDULE_SLIP_LIMIT}) reached` : undefined}
          onClick={() => setMode(mode === "reschedule" ? null : "reschedule")} className={outline}>
          <CalendarClock size={11} /> Reschedule
        </button>
      );
  }
}

// ── Small bits ───────────────────────────────────────────────────────

function InlinePanel({ children }: { children: React.ReactNode }) {
  return <div className="flex items-center gap-2 flex-wrap px-3 pb-2.5 pt-1.5 border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/20">{children}</div>;
}

function ConfirmBtn({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  return <button type="button" onClick={onClick} disabled={disabled} className="rounded-md bg-[var(--color-edify-primary)] text-white px-2.5 py-1 text-[11px] font-extrabold disabled:opacity-40">Confirm</button>;
}

function CloseBtn({ onClick }: { onClick: () => void }) {
  return <button type="button" onClick={onClick} className="h-6 w-6 grid place-items-center rounded-md border border-[var(--color-edify-border)]"><X size={11} /></button>;
}

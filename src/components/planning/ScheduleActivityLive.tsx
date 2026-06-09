"use client";

// Schedule Activity — LIVE writer. Creates a real activity via POST /api/activities
// (backend enforces assignment policy + capacity), with a cost preview computed
// from the CD rate card (/api/budget/cost-settings) — the SAME formula the budget
// engine uses, so what you see here is what lands in the fund request. No mock.

import { useEffect, useMemo, useState } from "react";
import { CalendarPlus, X, Wallet } from "lucide-react";
import { cn } from "@/lib/utils";

const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// Edify FY quarters: Q1 Jul–Sep, Q2 Oct–Dec, Q3 Jan–Mar, Q4 Apr–Jun.
const quarterFor = (m: number) => (m >= 7 && m <= 9 ? "Q1" : m >= 10 ? "Q2" : m <= 3 ? "Q3" : "Q4");

const VISIT = new Set(["school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit"]);
const TRAINING = new Set(["training", "school_improvement_training", "cluster_training", "core_training"]);

// Each option: v = unique select key, type = real ActivityType, slot = explicit
// cluster slot (cluster options only). The composite key lets the 3 cluster
// meetings share the cluster_meeting type but carry distinct slot tags.
type ActOption = { v: string; l: string; type: string; slot?: string };
const CLIENT_TYPES: ActOption[] = [
  { v: "school_visit", l: "School visit", type: "school_visit" },
  { v: "follow_up_visit", l: "Follow-up visit", type: "follow_up_visit" },
  { v: "coaching_visit", l: "Coaching visit", type: "coaching_visit" },
  { v: "in_school_support", l: "In-school support", type: "in_school_support" },
  { v: "training", l: "Training", type: "training" },
  { v: "school_improvement_training", l: "SIT / SSA", type: "school_improvement_training" },
];
const CORE_TYPES: ActOption[] = [
  { v: "core_visit", l: "Core visit", type: "core_visit" },
  { v: "core_training", l: "Core training", type: "core_training" },
];
const CLUSTER_TYPES: ActOption[] = [
  { v: "sit", l: "SIT / SSA", type: "school_improvement_training", slot: "sit" },
  { v: "meeting1", l: "First cluster meeting", type: "cluster_meeting", slot: "first_meeting" },
  { v: "meeting2", l: "Second cluster meeting", type: "cluster_meeting", slot: "second_meeting" },
  { v: "meeting3", l: "Third cluster meeting", type: "cluster_meeting", slot: "third_meeting" },
  { v: "cluster_training", l: "Cluster training", type: "cluster_training" },
];

const ugx = (n: number) => `UGX ${Math.round(n).toLocaleString()}`;

export function ScheduleActivityLive({
  schoolId, schoolName, schoolType = "client", clusterId, clusterName, onClose, onScheduled,
}: {
  // Provide EITHER a school (schoolId/schoolName/schoolType) OR a cluster
  // (clusterId/clusterName) target — the backend create accepts either.
  schoolId?: string; schoolName?: string; schoolType?: string;
  clusterId?: string; clusterName?: string;
  onClose: () => void; onScheduled?: () => void;
}) {
  const isCluster = !!clusterId;
  const targetName = isCluster ? clusterName ?? "Cluster" : schoolName ?? "School";
  const targetKind = isCluster ? "Cluster" : schoolType;
  const types = isCluster ? CLUSTER_TYPES : schoolType === "core" ? CORE_TYPES : CLIENT_TYPES;
  const [activityType, setActivityType] = useState(types[0].v);
  const [deliveryType, setDeliveryType] = useState<"staff" | "partner">("staff");
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [exactDate, setExactDate] = useState("");
  const [participants, setParticipants] = useState(25);
  const [rates, setRates] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    fetch("/api/budget/cost-settings", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) { const m: Record<string, number> = {}; for (const s of j.settings) m[s.key] = s.unitCost; setRates(m); } })
      .catch(() => undefined);
  }, []);

  // Resolve the selected option → real ActivityType + explicit cluster slot.
  const selected = types.find((t) => t.v === activityType) ?? types[0];
  const realType = selected.type;
  const slot = selected.slot;
  const isTraining = TRAINING.has(realType);
  // Cluster work, trainings and SIT happen on a SPECIFIC date → date required.
  // Plain school visits may be scheduled by month/week only.
  const isVisit = !isCluster && !isTraining;
  const dateRequired = !isVisit;
  const effMonth = exactDate ? Number(exactDate.slice(5, 7)) : month;

  // Same costing the backend budget engine applies.
  const cost = useMemo(() => {
    const lines: { label: string; amount: number }[] = [];
    const add = (label: string, key: string, qty = 1) => { if (rates[key] != null) lines.push({ label, amount: rates[key] * qty }); };
    if (realType === "cluster_meeting") add("Cluster meeting", "cluster_meeting_cost");
    else if (deliveryType === "partner") add("Partner lump sum", "partner_visit_lump_sum");
    else if (VISIT.has(realType)) { add("Transport", "staff_visit_transport_primary"); add("Lunch", "lunch"); }
    else if (isTraining) { add("Training session", "training_session_fee"); add("Venue", "venue"); add("Meals", "meals_per_participant", participants); }
    return { lines, total: lines.reduce((s, l) => s + l.amount, 0) };
  }, [rates, realType, deliveryType, participants, isTraining]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const res = await fetch("/api/activities", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          activityType: realType,
          ...(isCluster ? { clusterId, ...(slot ? { clusterSlot: slot } : {}) } : { schoolId }),
          fy: "2026", quarter: quarterFor(effMonth), plannedMonth: effMonth, deliveryType,
          ...(exactDate ? { scheduledDate: new Date(exactDate + "T09:00:00").toISOString() } : {}),
        }),
      });
      const j = await res.json();
      if (j.live) { setDone(true); onScheduled?.(); }
      else setError(j.error || "The backend rejected this (capacity or scope).");
    } catch { setError("Could not reach the server"); }
    setBusy(false);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative w-full sm:max-w-md card p-4 rounded-t-2xl sm:rounded-2xl max-h-[88vh] overflow-y-auto">
        <header className="flex items-center justify-between gap-2 mb-3">
          <h2 className="text-[14px] font-extrabold inline-flex items-center gap-1.5"><CalendarPlus size={15} /> Schedule activity</h2>
          <button onClick={onClose} className="h-7 w-7 grid place-items-center rounded-lg hover:bg-[var(--surface-3)]"><X size={14} /></button>
        </header>
        <p className="text-[11.5px] muted mb-3 truncate">{targetName} · <span className="capitalize">{targetKind}</span></p>

        {done ? (
          <div className="py-6 text-center">
            <div className="text-[13px] font-extrabold text-emerald-600 mb-1">Scheduled ✓</div>
            <p className="text-[11.5px] muted mb-3">It’s on your plan and in next period’s fund request.</p>
            <button onClick={onClose} className="h-9 px-4 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold">Done</button>
          </div>
        ) : (
          <>
            <div className="space-y-2.5">
              <Field label="Activity">
                <select value={activityType} onChange={(e) => setActivityType(e.target.value)} className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px]">
                  {types.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
                </select>
              </Field>
              <Field label="Delivered by">
                <div className="flex gap-1.5">
                  {(["staff", "partner"] as const).map((d) => (
                    <button key={d} onClick={() => setDeliveryType(d)} className={cn("flex-1 h-9 rounded-lg text-[12px] font-bold border capitalize", deliveryType === d ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "border-[var(--color-edify-border)]")}>{d}</button>
                  ))}
                </div>
              </Field>
              {dateRequired ? (
                <Field label="Date — required for this activity">
                  <input type="date" value={exactDate} onChange={(e) => setExactDate(e.target.value)}
                    className={cn("w-full h-9 px-2 rounded-lg border text-[12px]", exactDate ? "border-[var(--color-edify-border)]" : "border-amber-300")} />
                  {!exactDate && <span className="text-[10px] text-amber-600 font-semibold">Cluster meetings, trainings and SIT need an exact date.</span>}
                </Field>
              ) : (
                <Field label="Month / week">
                  <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px]">
                    {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{MONTHS[m]} (Q{quarterFor(m).slice(1)})</option>)}
                  </select>
                </Field>
              )}
              {isTraining && deliveryType === "staff" && (
                <Field label="Expected participants">
                  <input type="number" min={1} value={participants} onChange={(e) => setParticipants(Math.max(1, Number(e.target.value)))} className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px]" />
                </Field>
              )}
            </div>

            {/* Cost preview — auto from the CD rate card */}
            <div className="mt-3 rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 p-2.5">
              <div className="text-[10px] font-bold uppercase tracking-wide muted mb-1 inline-flex items-center gap-1"><Wallet size={11} /> Estimated cost</div>
              {cost.lines.map((l) => (
                <div key={l.label} className="flex items-center justify-between text-[11px]"><span className="muted">{l.label}</span><span className="tabular">{ugx(l.amount)}</span></div>
              ))}
              <div className="flex items-center justify-between text-[12.5px] font-extrabold border-t border-[var(--color-edify-divider)] mt-1 pt-1"><span>Total</span><span className="tabular">{ugx(cost.total)}</span></div>
              <p className="text-[9.5px] muted mt-1">Added to {MONTHS[effMonth]} fund request automatically.</p>
            </div>

            {error && <div className="mt-2 text-[11px] text-rose-600 font-semibold">{error}</div>}

            <button disabled={busy || (dateRequired && !exactDate)} onClick={submit} className="mt-3 w-full h-10 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[13px] font-extrabold disabled:opacity-50 disabled:cursor-not-allowed">
              {busy ? "Scheduling…" : dateRequired && !exactDate ? "Pick a date to schedule" : "Schedule activity"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10.5px] font-bold uppercase tracking-wide muted">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

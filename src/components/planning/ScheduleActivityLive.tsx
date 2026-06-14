"use client";

// Schedule Activity — LIVE writer. Creates a real activity via POST /api/activities
// (backend enforces assignment policy + capacity), with a cost preview computed
// from the CD rate card (/api/budget/cost-settings) — the SAME formula the budget
// engine uses, so what you see here is what lands in the fund request. No mock.

import { useEffect, useMemo, useState } from "react";
import { CalendarPlus, X, Wallet, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { csrfHeaders } from "@/lib/csrf-client";

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
  { v: "in_school_training", l: "In-school Training", type: "in_school_support" },
  { v: "in_school_ssa_support", l: "In-school SSA Support", type: "ssa_activity" },
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

type BePartnerLite = { id: string; name: string };

export function ScheduleActivityLive({
  schoolId, schoolName, schoolType = "client", clusterId, clusterName, onClose, onScheduled,
  mode = "schedule", assigningRole, intervention,
}: {
  // Provide EITHER a school (schoolId/schoolName/schoolType) OR a cluster
  // (clusterId/clusterName) target — the backend create accepts either.
  schoolId?: string; schoolName?: string; schoolType?: string;
  clusterId?: string; clusterName?: string;
  onClose: () => void; onScheduled?: () => void;
  /** "schedule" = staff plans/owns it (self-assign). "assign" = route to a
   *  partner for delivery (persists assignedPartnerId → status assigned_to_partner). */
  mode?: "schedule" | "assign";
  /** Caller's role — gates the delivery options (CCEO assigns to Partner only). */
  assigningRole?: string;
  /** Recommended intervention (the weakest SSA area). Shown in assign mode so
   *  the partner knows what to focus on. The partner picks the date later. */
  intervention?: string;
}) {
  const isCluster = !!clusterId;
  const isAssign = mode === "assign";
  const isCceo = assigningRole === "CCEO";
  const targetName = isCluster ? clusterName ?? "Cluster" : schoolName ?? "School";
  const targetKind = isCluster ? "Cluster" : schoolType;
  const types = isCluster ? CLUSTER_TYPES : schoolType === "core" ? CORE_TYPES : CLIENT_TYPES;
  const [activityType, setActivityType] = useState(types[0].v);
  // Assign mode is partner-delivered by definition; schedule mode defaults to staff.
  const [deliveryType, setDeliveryType] = useState<"staff" | "partner">(isAssign ? "partner" : "staff");
  const [partners, setPartners] = useState<BePartnerLite[]>([]);
  const [partnerId, setPartnerId] = useState<string>("");
  // Assign mode: the role-aware CCEO target (PL → the school's owner CCEO).
  // Self is intentionally excluded here — self-assign is the [Schedule] button.
  const [cceoOption, setCceoOption] = useState<{ label: string; staffId: string } | null>(null);
  const [assignTarget, setAssignTarget] = useState<"partner" | "staff">("partner");
  const [month, setMonth] = useState(new Date().getMonth() + 1);
  const [week, setWeek] = useState(Math.min(4, Math.ceil(new Date().getDate() / 7)));
  const [exactDate, setExactDate] = useState("");
  const [participants, setParticipants] = useState(25);
  const [rates, setRates] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  // Auto-recommended intervention (weakest SSA area) — fetched in assign mode
  // when the caller didn't pass one in.
  const [autoIntervention, setAutoIntervention] = useState<string | null>(null);
  const shownIntervention = intervention ?? autoIntervention ?? undefined;

  useEffect(() => {
    fetch("/api/budget/cost-settings", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) { const m: Record<string, number> = {}; for (const s of j.settings) m[s.key] = s.unitCost; setRates(m); } })
      .catch(() => undefined);
  }, []);

  // Partner directory — needed whenever partner delivery is possible.
  useEffect(() => {
    fetch("/api/partners", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (j.live && Array.isArray(j.partners)) {
          const list = j.partners.map((p: { id: string; name: string }) => ({ id: p.id, name: p.name }));
          setPartners(list);
          setPartnerId((cur) => cur || list[0]?.id || "");
        }
      })
      .catch(() => undefined);
  }, []);

  // Assign mode: auto-recommend the intervention from the school's weakest SSA
  // area (lowest-scoring intervention on the latest SSA record).
  useEffect(() => {
    if (!isAssign || isCluster || !schoolId || intervention) return;
    fetch(`/api/ssa/school/${encodeURIComponent(schoolId)}`, { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        const recs: Array<{ scores?: Array<{ intervention: string; score: number }> }> = j?.records ?? [];
        const scores = recs[0]?.scores ?? [];
        if (!scores.length) return;
        const weakest = scores.reduce((a, b) => (b.score < a.score ? b : a));
        setAutoIntervention(humanizeIntervention(weakest.intervention));
      })
      .catch(() => undefined);
  }, [isAssign, isCluster, schoolId, intervention]);

  // Assign mode: ask the backend who this school can be assigned to (role +
  // capacity aware). PL gets the school's owner CCEO as a "staff" target;
  // self is filtered out (that's the separate [Schedule] = self-assign path).
  useEffect(() => {
    if (!isAssign || isCluster || !schoolId) return;
    fetch(`/api/assignment/options?schoolId=${encodeURIComponent(schoolId)}`, { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (!j.live || !Array.isArray(j.options)) return;
        const staff = j.options.find((o: { type: string; enabled: boolean; staffId?: string; label: string }) => o.type === "staff" && o.enabled && o.staffId);
        const partner = j.options.find((o: { type: string; enabled: boolean }) => o.type === "partner");
        if (staff) {
          setCceoOption({ label: staff.label, staffId: staff.staffId });
          // When the owner CCEO is the available target and partner is blocked
          // (PL must route through the supervised CCEO), default to the CCEO.
          if (!partner || partner.enabled === false) setAssignTarget("staff");
        }
      })
      .catch(() => undefined);
  }, [isAssign, isCluster, schoolId]);

  const cceoStaffId = assignTarget === "staff" ? cceoOption?.staffId : undefined;
  // Effective delivery: in assign mode the target toggle wins; otherwise the
  // schedule-mode staff/partner toggle.
  const effDelivery: "staff" | "partner" = isAssign ? assignTarget : deliveryType;

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
    else if (effDelivery === "partner") add("Partner lump sum", "partner_visit_lump_sum");
    else if (VISIT.has(realType)) { add("Transport", "staff_visit_transport_primary"); add("Lunch", "lunch"); }
    else if (isTraining) { add("Training session", "training_session_fee"); add("Venue", "venue"); add("Meals", "meals_per_participant", participants); }
    return { lines, total: lines.reduce((s, l) => s + l.amount, 0) };
  }, [rates, realType, effDelivery, participants, isTraining]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      const res = await fetch("/api/activities", {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          activityType: realType,
          ...(isCluster ? { clusterId, ...(slot ? { clusterSlot: slot } : {}) } : { schoolId }),
          fy: "2026", quarter: quarterFor(effMonth), deliveryType: effDelivery,
          // Assign mode carries NO planned month/week — the partner schedules the
          // delivery week on their own dashboard. Schedule mode sets them.
          ...(isAssign ? {} : { plannedMonth: effMonth }),
          ...(effDelivery === "partner" && partnerId ? { assignedPartnerId: partnerId } : {}),
          ...(effDelivery === "staff" && cceoStaffId ? { responsibleStaffId: cceoStaffId } : {}),
          ...(exactDate ? { scheduledDate: new Date(exactDate + "T09:00:00").toISOString() } : {}),
          ...(!isAssign && isVisit ? { plannedWeek: week } : {}),
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
          <h2 className="text-[14px] font-extrabold inline-flex items-center gap-1.5"><CalendarPlus size={15} /> {isAssign ? "Assign to partner" : "Schedule activity"}</h2>
          <button onClick={onClose} className="h-7 w-7 grid place-items-center rounded-lg hover:bg-[var(--surface-3)]"><X size={14} /></button>
        </header>
        <p className="text-[11.5px] muted mb-3 truncate">{targetName} · <span className="capitalize">{targetKind}</span></p>

        {done ? (
          <div className="py-6 text-center">
            <div className="text-[13px] font-extrabold text-emerald-600 mb-1">{isAssign ? "Assigned ✓" : "Scheduled ✓"}</div>
            <p className="text-[11.5px] muted mb-3">{!isAssign ? "It’s on your plan and in next period’s fund request." : effDelivery === "staff" ? "Assigned to the CCEO — it’s on their planning queue. You’ll monitor delivery." : "Sent to the partner’s scheduling dashboard. It returns to your monitoring queue once they schedule."}</p>
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
              {/* Delivery owner. Schedule mode: a CCEO may deliver themselves
                  (self-assign) or route to a partner; other roles get the full
                  toggle. Assign mode: partner by default, plus the school's
                  owner CCEO when the backend allows it (PL → CCEO or Partner). */}
              {!isAssign && (
                <Field label="Delivered by">
                  <div className="flex gap-1.5">
                    {(["staff", "partner"] as const).map((d) => (
                      <button key={d} onClick={() => setDeliveryType(d)} className={cn("flex-1 h-9 rounded-lg text-[12px] font-bold border capitalize", deliveryType === d ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "border-[var(--color-edify-border)]")}>{d === "staff" ? "Myself (staff)" : "Partner"}</button>
                    ))}
                  </div>
                </Field>
              )}
              {isAssign && cceoOption && (
                <Field label="Assign to">
                  <div className="flex gap-1.5">
                    <button onClick={() => setAssignTarget("staff")} className={cn("flex-1 h-9 rounded-lg text-[12px] font-bold border px-1 truncate", assignTarget === "staff" ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "border-[var(--color-edify-border)]")}>{cceoOption.label}</button>
                    <button onClick={() => setAssignTarget("partner")} className={cn("flex-1 h-9 rounded-lg text-[12px] font-bold border", assignTarget === "partner" ? "bg-[var(--color-edify-primary)] text-white border-transparent" : "border-[var(--color-edify-border)]")}>Partner</button>
                  </div>
                </Field>
              )}
              {effDelivery === "partner" && (
                <Field label={isCceo ? "Partner (CCEOs deliver field work through partners)" : "Partner"}>
                  {partners.length === 0 ? (
                    <div className="text-[11px] text-amber-600 font-semibold">No certified partners available to assign.</div>
                  ) : (
                    <select value={partnerId} onChange={(e) => setPartnerId(e.target.value)} className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px]">
                      {partners.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                    </select>
                  )}
                </Field>
              )}
              {/* Intervention — auto-recommended from the school's weakest SSA
                  area so the partner knows what to focus on. Read-only. */}
              {isAssign && (
                <Field label="Intervention (auto from SSA)">
                  <div className="w-full min-h-9 px-2.5 py-2 rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 text-[12px] font-semibold inline-flex items-center gap-1.5">
                    <Sparkles size={12} className="text-[var(--color-edify-primary)] shrink-0" />
                    {shownIntervention ?? "Will be set from the school's SSA"}
                  </div>
                </Field>
              )}
              {/* Assign mode has NO date — the partner picks the delivery week on
                  their own dashboard. Schedule mode keeps the date/month+week. */}
              {isAssign ? null : dateRequired ? (
                <Field label="Date — required for this activity">
                  <input type="date" value={exactDate} onChange={(e) => setExactDate(e.target.value)}
                    className={cn("w-full h-9 px-2 rounded-lg border text-[12px]", exactDate ? "border-[var(--color-edify-border)]" : "border-amber-300")} />
                  {!exactDate && <span className="text-[10px] text-amber-600 font-semibold">Cluster meetings, trainings and SIT need an exact date.</span>}
                </Field>
              ) : (
                <>
                  <Field label="Month">
                    <select value={month} onChange={(e) => setMonth(Number(e.target.value))} className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px]">
                      {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{MONTHS[m]} (Q{quarterFor(m).slice(1)})</option>)}
                    </select>
                  </Field>
                  <Field label="Week of month">
                    <select value={week} onChange={(e) => setWeek(Number(e.target.value))} className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px]">
                      <option value={1}>Week 1 (1st–7th)</option>
                      <option value={2}>Week 2 (8th–14th)</option>
                      <option value={3}>Week 3 (15th–21st)</option>
                      <option value={4}>Week 4 (22nd–end)</option>
                    </select>
                  </Field>
                </>
              )}
              {isTraining && effDelivery === "staff" && (
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
              <p className="text-[9.5px] muted mt-1">{isAssign ? "Drawn from the CD cost catalogue. The partner confirms the delivery week." : `Added to ${MONTHS[effMonth]} fund request automatically.`}</p>
            </div>

            {error && <div className="mt-2 text-[11px] text-rose-600 font-semibold">{error}</div>}

            <button disabled={busy || (!isAssign && dateRequired && !exactDate) || (effDelivery === "partner" && !partnerId)} onClick={submit} className="mt-3 w-full h-10 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[13px] font-extrabold disabled:opacity-50 disabled:cursor-not-allowed">
              {busy ? (isAssign ? "Assigning…" : "Scheduling…")
                : !isAssign && dateRequired && !exactDate ? "Pick a date to schedule"
                : effDelivery === "partner" && !partnerId ? "Choose a partner"
                : isAssign && effDelivery === "staff" ? `Assign to ${cceoOption?.label?.replace("Assign to ", "") ?? "CCEO"}`
                : isAssign ? "Assign to partner"
                : "Schedule activity"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// Backend intervention key → readable label, e.g. "teaching_and_learning" →
// "Teaching & Learning".
function humanizeIntervention(key: string): string {
  return key
    .split("_")
    .map((w) => (w === "and" ? "&" : w.charAt(0).toUpperCase() + w.slice(1)))
    .join(" ");
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10.5px] font-bold uppercase tracking-wide muted">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

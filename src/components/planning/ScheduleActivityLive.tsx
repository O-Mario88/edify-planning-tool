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

const VISIT_PURPOSES = [
  { value: "ssa_follow_up", label: "SSA Follow-up" },
  { value: "leadership_support", label: "Leadership Support" },
  { value: "teaching_learning_support", label: "Teaching & Learning Support" },
  { value: "financial_health_support", label: "Financial Health Support" },
  { value: "compliance_follow_up", label: "Compliance Follow-up" },
  { value: "education_tech_support", label: "Education Technology Support" },
  { value: "learning_env_follow_up", label: "Learning Environment Follow-up" },
  { value: "christlike_behaviour_support", label: "Christlike Behaviour Support" },
  { value: "exposure_word_of_god_support", label: "Exposure to the Word of God Support" },
  { value: "evidence_verification", label: "Evidence Verification" },
  { value: "general_monitoring", label: "General Monitoring" },
  { value: "other", label: "Other" }
];

const CLUSTER_PURPOSES = [
  { value: "group_training", label: "Group Training" },
  { value: "cluster_meeting", label: "Cluster Meeting" },
  { value: "sit", label: "SIT" },
  { value: "ssa_review_meeting", label: "SSA Review Meeting" },
  { value: "intervention_support_meeting", label: "Intervention Support Meeting" },
  { value: "planning_meeting", label: "Planning Meeting" },
  { value: "follow_up_meeting", label: "Follow-up Meeting" },
  { value: "other", label: "Other" }
];

const INTERVENTIONS = [
  { value: "teaching_and_learning", label: "Teaching & Learning" },
  { value: "financial_health", label: "Financial Health" },
  { value: "christlike_behaviour", label: "Christlike Behaviour" },
  { value: "exposure_to_word_of_god", label: "Exposure to Word of God" },
  { value: "government_requirements", label: "Government Requirements" },
  { value: "leadership", label: "Leadership" },
  { value: "education_technology", label: "Education Technology" },
  { value: "learning_environment", label: "Learning Environment" }
];

// Each option: v = unique select key, type = real ActivityType, slot = optional tag
// for legacy slot-based flows (SIT). Cluster meetings/trainings are unlimited;
// no "first/second/third" slots.
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
  { v: "cluster_meeting", l: "Cluster Meeting", type: "cluster_meeting" },
  { v: "cluster_training", l: "Cluster Training", type: "cluster_training" },
  { v: "sit", l: "School Improvement Training (SIT)", type: "school_improvement_training", slot: "sit" },
  { v: "cluster_sit", l: "Cluster SIT", type: "school_improvement_training", slot: "sit" },
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

  // Auto-recommend focus intervention from school/cluster weakest areas
  useEffect(() => {
    if (schoolId) {
      fetch(`/api/ssa/school/${encodeURIComponent(schoolId)}`, { credentials: "include" })
        .then((r) => r.json())
        .then((j) => {
          const recs: Array<{ scores?: Array<{ intervention: string; score: number }> }> = j?.records ?? [];
          const scores = recs[0]?.scores ?? [];
          if (!scores.length) return;
          const weakest = scores.reduce((a, b) => (b.score < a.score ? b : a));
          setAutoIntervention(weakest.intervention);
          setFocusIntervention(weakest.intervention);
        })
        .catch(() => undefined);
    } else if (clusterId) {
      fetch(`/api/clusters/${encodeURIComponent(clusterId)}/weakest-interventions`, { credentials: "include" })
        .then((r) => r.json())
        .then((j) => {
          if (Array.isArray(j) && j.length > 0) {
            setAutoIntervention(j[0].intervention);
            setFocusIntervention(j[0].intervention);
          }
        })
        .catch(() => undefined);
    }
  }, [schoolId, clusterId]);

  useEffect(() => {
    if (intervention) {
      setFocusIntervention(intervention);
    }
  }, [intervention]);

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

  const [activityPurposeText, setActivityPurposeText] = useState("");
  const [focusIntervention, setFocusIntervention] = useState("teaching_and_learning");
  const [secondaryFocusInterventions, setSecondaryFocusInterventions] = useState<string[]>([]);
  const [expectedOutcome, setExpectedOutcome] = useState("");
  const [purposeType, setPurposeType] = useState(isVisit ? "teaching_learning_support" : "group_training");

  useEffect(() => {
    setPurposeType(isVisit ? "teaching_learning_support" : "group_training");
  }, [isVisit]);

  // Cost preview state — loaded dynamically from backend preview API.
  const [costPreview, setCostPreview] = useState<{
    amount: number;
    lines: Array<{ label: string; amount: number; missing?: boolean }>;
    canSchedule: boolean;
    blockers: string[];
  } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const body = {
      activityType: realType,
      ...(isCluster ? { clusterId } : { schoolId }),
      deliveryType: effDelivery,
      plannedMonth: effMonth,
      assignedPartnerId: partnerId || undefined,
      scheduledDate: exactDate ? new Date(exactDate + "T09:00:00").toISOString() : new Date().toISOString(),
      expectedParticipants: (isTraining || isCluster) ? participants : undefined,
    };

    fetch("/api/costing/preview", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", ...csrfHeaders() },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
      .then((r) => r.json())
      .then((j) => {
        if (j.amount != null) {
          setCostPreview({
            amount: j.amount,
            lines: j.lines || [],
            canSchedule: j.canSchedule !== false,
            blockers: j.blockers || [],
          });
        }
      })
      .catch(() => undefined);

    return () => controller.abort();
  }, [realType, effDelivery, participants, exactDate, schoolId, clusterId, partnerId, effMonth, isCluster, isTraining]);

  const submit = async () => {
    setBusy(true); setError(null);
    try {
      let endpoint = "/api/activities/schedule-school-visit";
      if (effDelivery === "partner") {
        endpoint = "/api/activities/schedule-partner-visit";
      } else if (isCluster || isTraining) {
        endpoint = "/api/activities/schedule-cluster-activity";
      }

      const res = await fetch(endpoint, {
        method: "POST", credentials: "include", headers: { "Content-Type": "application/json", ...csrfHeaders() },
        body: JSON.stringify({
          activityType: realType,
          ...(isCluster ? { clusterId, ...(slot ? { clusterSlot: slot } : {}) } : { schoolId }),
          fy: "2026", quarter: quarterFor(effMonth), deliveryType: effDelivery,
          // Assign mode carries NO planned month/week — the partner schedules the
          // delivery week on their own dashboard. Schedule mode sets them.
          ...(isAssign ? {} : { plannedMonth: effMonth }),
          ...(effDelivery === "partner" && partnerId ? { assignedPartnerId: partnerId } : {}),
          ...(effDelivery === "staff" && assignTarget === "staff" && cceoOption ? { responsibleStaffId: cceoOption.staffId } : {}),
          ...(exactDate ? { scheduledDate: new Date(exactDate + "T09:00:00").toISOString() } : {}),
          ...(!isAssign && isVisit ? { plannedWeek: week } : {}),
          ...(isTraining || isCluster ? { expectedParticipants: participants } : {}),
          activityPurposeText,
          purposeType,
          focusIntervention,
          secondaryFocusInterventions,
          expectedOutcome,
        }),
      });
      const j = await res.json();
      if (res.status === 201 || j.live || j.id) {
        setDone(true);
        onScheduled?.();
      } else {
        setError(j.message || j.error || "The backend rejected this (capacity or scope).");
      }
    } catch { setError("Could not reach the server"); }
    setBusy(false);
  };

  const hasBlockers = costPreview ? !costPreview.canSchedule : false;

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
              <Field label={isVisit ? "Visit Purpose (Required)" : "Purpose for Meeting (Required)"}>
                <textarea
                  required
                  value={activityPurposeText}
                  onChange={(e) => setActivityPurposeText(e.target.value)}
                  placeholder={isVisit ? "Describe the specific visit purpose..." : "Describe the purpose of this meeting/training..."}
                  className="w-full min-h-[60px] px-2.5 py-1.5 rounded-lg border border-[var(--color-edify-border)] bg-transparent text-[12px] font-semibold"
                />
              </Field>

              <Field label="Purpose Type">
                <select
                  value={purposeType}
                  onChange={(e) => setPurposeType(e.target.value)}
                  className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px]"
                >
                  {(isVisit ? VISIT_PURPOSES : CLUSTER_PURPOSES).map((p) => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
              </Field>

              <Field label="Primary Focus Intervention">
                <select
                  value={focusIntervention}
                  onChange={(e) => setFocusIntervention(e.target.value)}
                  className="w-full h-9 px-2 rounded-lg border border-[var(--color-edify-border)] text-[12px]"
                >
                  {INTERVENTIONS.map((i) => (
                    <option key={i.value} value={i.value}>{i.label}</option>
                  ))}
                </select>
              </Field>

              {isTraining && (
                <Field label="Secondary Focus Interventions (Optional)">
                  <div className="grid grid-cols-2 gap-1 rounded-lg border border-[var(--color-edify-border)] p-2 max-h-[100px] overflow-y-auto">
                    {INTERVENTIONS.map((i) => (
                      <label key={i.value} className="flex items-center gap-1.5 text-[11px] font-medium text-slate-700">
                        <input
                          type="checkbox"
                          checked={secondaryFocusInterventions.includes(i.value)}
                          onChange={(e) => {
                            if (e.target.checked) {
                              setSecondaryFocusInterventions([...secondaryFocusInterventions, i.value]);
                            } else {
                              setSecondaryFocusInterventions(secondaryFocusInterventions.filter((v) => v !== i.value));
                            }
                          }}
                        />
                        {i.label}
                      </label>
                    ))}
                  </div>
                </Field>
              )}

              <Field label="Expected Outcome">
                <textarea
                  value={expectedOutcome}
                  onChange={(e) => setExpectedOutcome(e.target.value)}
                  placeholder="What is the expected outcome of this activity?"
                  className="w-full min-h-[60px] px-2.5 py-1.5 rounded-lg border border-[var(--color-edify-border)] bg-transparent text-[12px] font-semibold"
                />
              </Field>
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

            <div className="mt-3 rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 p-2.5">
              <div className="text-[10px] font-bold uppercase tracking-wide muted mb-1 inline-flex items-center gap-1"><Wallet size={11} /> Estimated cost</div>
              {costPreview?.lines.map((l) => (
                <div key={l.label} className={cn("flex items-center justify-between text-[11px]", l.missing && "text-rose-600 font-semibold")}>
                  <span>{l.label} {l.missing && "(Missing Rate)"}</span>
                  <span className="tabular">{l.missing ? "Blocked" : ugx(l.amount)}</span>
                </div>
              ))}
              <div className="flex items-center justify-between text-[12.5px] font-extrabold border-t border-[var(--color-edify-divider)] mt-1 pt-1">
                <span>Total</span>
                <span className="tabular">{costPreview ? ugx(costPreview.amount) : "Calculating..."}</span>
              </div>
              <p className="text-[9.5px] muted mt-1">{isAssign ? "Drawn from the CD cost catalogue. The partner confirms the delivery week." : `Added to ${MONTHS[effMonth]} fund request automatically.`}</p>
            </div>

            {costPreview && costPreview.blockers.length > 0 && (
              <div className="mt-2.5 p-2 rounded bg-rose-50 border border-rose-200 text-[10.5px] text-rose-700 font-bold space-y-1">
                <div>Cannot Schedule — Missing rate in CD catalogue:</div>
                <ul className="list-disc pl-4 font-semibold text-[10px]">
                  {costPreview.blockers.map((b) => <li key={b}>{b}</li>)}
                </ul>
              </div>
            )}

            {error && <div className="mt-2 text-[11px] text-rose-600 font-semibold">{error}</div>}

            <button disabled={busy || hasBlockers || (!isAssign && dateRequired && !exactDate) || (effDelivery === "partner" && !partnerId) || !activityPurposeText.trim()} onClick={submit} className="mt-3 w-full h-10 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[13px] font-extrabold disabled:opacity-50 disabled:cursor-not-allowed">
              {busy ? (isAssign ? "Assigning…" : "Scheduling…")
                : hasBlockers ? "Blocked — Missing Catalogue Cost"
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

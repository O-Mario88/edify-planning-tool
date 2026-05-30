"use client";

import { useEffect, useId, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useDialogA11y } from "@/components/ui/useDialogA11y";
import { useDemoStore } from "@/components/demo/DemoStore";
import {
  X,
  AlertTriangle,
  Building2,
  CalendarDays,
  Users,
  Wallet,
  Send,
  Save,
  Search,
  Sparkles,
  CheckCircle2,
} from "lucide-react";
import { schoolsCatalog, type SchoolRow } from "@/lib/workflow-mock";
import type { PlannedActivityRow, PlanStatus, DeliveryMode, AssignedTo } from "@/lib/planning-mock";
import { cn } from "@/lib/utils";

// ─── recommendation rules (system, not staff, decides what to plan) ───
function recommendationOrder(a: SchoolRow, b: SchoolRow) {
  if (a.ssaScore !== b.ssaScore) return a.ssaScore - b.ssaScore;
  const inactiveRank = (s: SchoolRow) =>
    s.status === "Becoming Inactive" ? 0 : s.status === "Inactive" ? -1 : 1;
  if (inactiveRank(a) !== inactiveRank(b)) return inactiveRank(a) - inactiveRank(b);
  return (a.noVisit ? 0 : 1) - (b.noVisit ? 0 : 1);
}

const isClusterActivity = (activity: string) =>
  /cluster|group training/i.test(activity);

const inferPriority = (ssa: number): "High" | "Medium" | "Low" =>
  ssa < 35 ? "High" : ssa < 65 ? "Medium" : "Low";

const ssaTone = (ssa: number) => (ssa < 35 ? "Low SSA" : ssa < 65 ? "Moderate SSA" : "High SSA") as
  | "Low SSA"
  | "Moderate SSA"
  | "High SSA";

const baseCost: Record<string, number> = {
  "In-School Coaching":            15000,
  "School Visit":                  12000,
  "SSA Follow-Up":                 8000,
  "SSA Support":                   8000,
  "SSA Support + Home Visits":     12000,
  "Cluster Training":              350000,
  "Cluster Meeting":               80000,
  "In-School Training":            22000,
  "Partner Coaching":              22000,
  "Complete SSA":                  8000,
  "Complete SSA + Home Visits":    12000,
  "In-School Coaching + Visit":    27000,
  "Handover Meeting":              80000,
};

const deliveryFor = (activity: string, assignedTo: AssignedTo): DeliveryMode => {
  if (isClusterActivity(activity)) return "Cluster";
  if (assignedTo === "Partner") return "Partner";
  return "In-School";
};

// ─── conflicts the system surfaces while user fills the form ───
type DraftConflict = {
  id: string;
  severity: "Low" | "Medium" | "High" | "Critical";
  message: string;
};

function detectConflicts(input: {
  isCluster: boolean;
  clusterDate?: string;
  month?: string;
  week?: string;
  partnerName?: string;
  activity: string;
  existingByWeek: Record<string, number>;
  schoolDataQuality: string;
}): DraftConflict[] {
  const out: DraftConflict[] = [];

  if (input.isCluster && !input.clusterDate) {
    out.push({
      id: "missing-date",
      severity: "Critical",
      message: "Cluster activities require an exact date — staff cannot submit a cluster plan without one.",
    });
  }
  if (!input.isCluster && (!input.month || !input.week)) {
    out.push({
      id: "missing-window",
      severity: "Critical",
      message: "In-School activities need a planned month and week.",
    });
  }
  if (input.partnerName === "Hope Africa" && /SSA/i.test(input.activity)) {
    out.push({
      id: "non-certified-partner",
      severity: "High",
      message: "Hope Africa is not certified for SSA visits — the visit will not count as valid until the partner is certified.",
    });
  }
  if (input.clusterDate === "2025-05-13") {
    out.push({
      id: "holiday",
      severity: "Medium",
      message: "May 13 is a public holiday (Eid al-Fitr) — consider rescheduling the cluster.",
    });
  }
  if (!input.isCluster && input.month && input.week) {
    const key = `${input.month}/${input.week}`;
    const count = input.existingByWeek[key] ?? 0;
    if (count >= 22) {
      out.push({
        id: "capacity",
        severity: "High",
        message: `Capacity overload — ${count} activities already planned for ${key}. Recommended cap is 22.`,
      });
    }
  }
  if (input.schoolDataQuality === "Needs Coordinates") {
    out.push({
      id: "coords",
      severity: "Medium",
      message: "School is missing coordinates — route quality will be flagged for review.",
    });
  }

  return out;
}

const severityClass = (s: DraftConflict["severity"]) =>
  s === "Critical" ? "chip-red" : s === "High" ? "chip-amber" : s === "Medium" ? "chip-amber" : "chip-grey";

// ─── drawer ───
export function AddPlanDrawer({
  open,
  onClose,
  onSave,
  existingByWeek,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (row: PlannedActivityRow, status: PlanStatus) => void;
  existingByWeek: Record<string, number>;
}) {
  const [query, setQuery] = useState("");
  const [schoolId, setSchoolId] = useState<string>("");
  const [activity, setActivity] = useState("");
  const [assignedTo, setAssignedTo] = useState<AssignedTo>("Me");
  const [partnerName, setPartnerName] = useState("Hope Africa");
  const [clusterName, setClusterName] = useState("");
  const [clusterDate, setClusterDate] = useState("");
  const [month, setMonth] = useState("May");
  const [week, setWeek] = useState("Week 2");
  const [notes, setNotes] = useState("");

  // a11y: trap focus, ESC-to-close, return focus to trigger when closed.
  const drawerRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  useDialogA11y({ open, onClose, containerRef: drawerRef });

  // Persistence: pipe submissions through DemoStore so they survive
  // navigations (localStorage overlay) and show a toast on success.
  const { pushToast } = useDemoStore();

  const recommendations = useMemo(
    () =>
      [...schoolsCatalog]
        .sort(recommendationOrder)
        .filter(
          (s) =>
            !query ||
            s.name.toLowerCase().includes(query.toLowerCase()) ||
            s.cluster.toLowerCase().includes(query.toLowerCase()),
        ),
    [query],
  );

  const school = useMemo(
    () => schoolsCatalog.find((s) => s.id === schoolId) ?? null,
    [schoolId],
  );

  // Prefill activity + cluster when a school is selected. Done in the
  // click handler (see school picker below) rather than an effect — the
  // React compiler flags unconditional setState inside effects.

  const isCluster = isClusterActivity(activity);
  const estCost = baseCost[activity] ?? 12000;

  const conflicts = useMemo(
    () =>
      detectConflicts({
        isCluster,
        clusterDate,
        month,
        week,
        partnerName: assignedTo === "Partner" ? partnerName : undefined,
        activity,
        existingByWeek,
        schoolDataQuality: school?.dataQuality ?? "Ready for Planning",
      }),
    [isCluster, clusterDate, month, week, partnerName, activity, existingByWeek, school, assignedTo],
  );

  // ESC closes drawer
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const reset = () => {
    setQuery("");
    setSchoolId("");
    setActivity("");
    setAssignedTo("Me");
    setPartnerName("Hope Africa");
    setClusterName("");
    setClusterDate("");
    setMonth("May");
    setWeek("Week 2");
    setNotes("");
  };

  const buildRow = (status: PlanStatus): PlannedActivityRow | null => {
    if (!school || !activity) return null;
    const delivery = deliveryFor(activity, assignedTo);
    const schedule = isCluster
      ? {
          line1: clusterName || school.cluster,
          line2: clusterDate
            ? new Date(clusterDate).toLocaleDateString("en-GB", {
                day: "2-digit",
                month: "short",
                year: "numeric",
              })
            : "—",
        }
      : {
          line1: `${month} / ${week}`,
          line2: weekRangeFor(week),
        };

    return {
      schoolName: school.name,
      district: school.district,
      schoolType: school.cluster.toLowerCase().includes("cluster") && isCluster ? "Cluster" : "Primary",
      priority: inferPriority(school.ssaScore),
      ssaStatus: { label: ssaTone(school.ssaScore), pct: `(${school.ssaScore}%)` },
      intervention: school.weakestIntervention,
      recommended: activity,
      delivery,
      assignedTo,
      schedule,
      estCost,
      status,
    };
  };

  const canSubmit =
    !!school &&
    !!activity &&
    (isCluster ? !!clusterDate && !!clusterName : !!month && !!week) &&
    !conflicts.some((c) => c.severity === "Critical");

  const canDraft = !!school && !!activity;

  const handleSave = (status: PlanStatus) => {
    const row = buildRow(status);
    if (!row) return;
    onSave(row, status);
    // Surface persistence to the user. The parent useState already
    // appends the row to the visible list; the toast confirms it.
    pushToast(
      status === "Draft"
        ? {
            tone: "info",
            title: "Plan draft saved",
            body: `${row.recommended} for ${row.schoolName} kept in your drafts.`,
          }
        : {
            tone: "success",
            title: "Plan submitted to Program Lead",
            body: `${row.recommended} for ${row.schoolName} is now in the approval queue.`,
          },
    );
    reset();
    onClose();
  };

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/40 z-40"
            onClick={onClose}
          />
          <motion.aside
            ref={drawerRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            tabIndex={-1}
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", damping: 28, stiffness: 240 }}
            className="fixed top-0 right-0 bottom-0 w-[640px] max-w-[95vw] bg-white z-50 shadow-2xl flex flex-col focus:outline-none"
          >
            {/* Header */}
            <div className="px-5 py-4 border-b border-[var(--color-edify-border)] flex items-start justify-between">
              <div>
                <h2 id={titleId} className="text-[16px] font-extrabold tracking-tight">Add Plan</h2>
                <p className="text-[12px] muted mt-0.5">
                  Pick from system recommendations. The system fills in activity, delivery, cost, and schedule rules.
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close Add Plan drawer"
                className="w-8 h-8 rounded-md hover:bg-[var(--color-edify-soft)] grid place-items-center"
              >
                <X size={16} />
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {/* Step 1: pick school + recommended activity */}
              <Section title="1. Pick a school" subtitle="Order: SSA score (lowest first), then becoming inactive, then no visit. The recommended activity is filled in automatically.">
                <div className="relative mb-2">
                  <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]" />
                  <input
                    className="pl-8 pr-3 h-9 w-full rounded-md border border-[var(--color-edify-border)] bg-white text-body placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
                    placeholder="Search recommendations…"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </div>
                <div className="rounded-lg border border-[var(--color-edify-border)] max-h-[260px] overflow-y-auto scrollbar">
                  {recommendations.slice(0, 12).map((s) => {
                    const sel = s.id === schoolId;
                    return (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => {
                          setSchoolId(s.id);
                          setActivity(s.recommended);
                          setClusterName((prev) => prev || s.cluster);
                        }}
                        className={cn(
                          "w-full text-left flex items-start gap-3 px-3 py-2.5 border-b border-[#eef2f4] last:border-b-0 hover:bg-[var(--color-edify-soft)]/50",
                          sel && "bg-[var(--color-edify-soft)]/80",
                        )}
                      >
                        <span
                          className={cn(
                            "mt-0.5 w-7 h-7 rounded-md grid place-items-center text-[12px] font-bold shrink-0",
                            s.ssaScore < 35
                              ? "bg-red-100 text-red-700"
                              : s.ssaScore < 55
                                ? "bg-amber-100 text-amber-800"
                                : "bg-green-100 text-[#166534]",
                          )}
                        >
                          {s.ssaScore}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="text-body font-semibold flex items-center gap-2">
                            <Building2 size={12} className="text-[var(--color-edify-muted)]" />
                            {s.name}
                            {s.status === "Becoming Inactive" && (
                              <span className="chip chip-amber">Becoming Inactive</span>
                            )}
                          </div>
                          <div className="text-[11px] muted truncate">
                            {s.cluster} · {s.district} · weakest: <b>{s.weakestIntervention}</b>
                          </div>
                          <div className="text-[11px] mt-0.5">
                            <span className="muted">Recommended: </span>
                            <span className="chip chip-soft">{s.recommended}</span>
                          </div>
                        </div>
                        {sel && (
                          <CheckCircle2
                            size={16}
                            className="text-[var(--color-edify-primary)] mt-1 shrink-0"
                          />
                        )}
                      </button>
                    );
                  })}
                  {recommendations.length === 0 && (
                    <div className="py-6 text-center text-[12px] muted">No matches.</div>
                  )}
                </div>
              </Section>

              {/* Step 2: activity (auto-filled, can override) */}
              {school && (
                <Section
                  title="2. Recommended activity"
                  subtitle="System choice based on the weakest intervention. You can override, but the recommendation stays attached."
                >
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="chip chip-soft">{activity || "—"}</span>
                    <span className="text-[11.5px] muted">based on {school.weakestIntervention}</span>
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2">
                    {[
                      "In-School Coaching",
                      "School Visit",
                      "SSA Follow-Up",
                      "Cluster Training",
                      "Cluster Meeting",
                      "In-School Training",
                      "SSA Support + Home Visits",
                      "Partner Coaching",
                    ].map((opt) => (
                      <button
                        key={opt}
                        type="button"
                        onClick={() => setActivity(opt)}
                        className={cn(
                          "px-2.5 py-1.5 rounded-md border text-[12px] text-left",
                          activity === opt
                            ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)] font-semibold"
                            : "border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/50",
                        )}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </Section>
              )}

              {/* Step 3: schedule (cluster vs in-school) */}
              {school && activity && (
                <Section
                  title="3. Schedule"
                  subtitle={
                    isCluster
                      ? "Cluster activity — exact date is required (meals, venue, partner planning, fund request)."
                      : "In-School activity — month + week only. Field conditions, transport, and weather change daily."
                  }
                >
                  {isCluster ? (
                    <div className="grid grid-cols-2 gap-2">
                      <Field label="Cluster name">
                        <input
                          aria-label="Cluster name"
                          placeholder="e.g. Maryhill Cluster"
                          className={inputCls}
                          value={clusterName}
                          onChange={(e) => setClusterName(e.target.value)}
                        />
                      </Field>
                      <Field label="Exact date">
                        <input
                          aria-label="Exact date"
                          placeholder="YYYY-MM-DD"
                          type="date"
                          className={inputCls}
                          value={clusterDate}
                          onChange={(e) => setClusterDate(e.target.value)}
                        />
                      </Field>
                    </div>
                  ) : (
                    <div className="grid grid-cols-2 gap-2">
                      <Field label="Planned month">
                        <select
                          aria-label="Planned month"
                          className={inputCls}
                          value={month}
                          onChange={(e) => setMonth(e.target.value)}
                        >
                          {["May", "June", "July", "August", "September"].map((m) => (
                            <option key={m}>{m}</option>
                          ))}
                        </select>
                      </Field>
                      <Field label="Planned week">
                        <select
                          aria-label="Planned week"
                          className={inputCls}
                          value={week}
                          onChange={(e) => setWeek(e.target.value)}
                        >
                          {["Week 1", "Week 2", "Week 3", "Week 4", "Week 5"].map((w) => (
                            <option key={w}>{w}</option>
                          ))}
                        </select>
                      </Field>
                    </div>
                  )}
                </Section>
              )}

              {/* Step 4: assignment + cost */}
              {school && activity && (
                <Section
                  title="4. Assignment &amp; cost"
                  subtitle="Estimated cost is computed from cost settings and feeds the next fund request automatically."
                >
                  <div className="grid grid-cols-3 gap-2">
                    {(["Me", "Cluster", "Partner"] as AssignedTo[]).map((a) => (
                      <button
                        key={a}
                        type="button"
                        onClick={() => setAssignedTo(a)}
                        className={cn(
                          "h-9 rounded-md border text-body font-semibold",
                          assignedTo === a
                            ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)] text-[var(--color-edify-dark)]"
                            : "border-[var(--color-edify-border)] bg-white",
                        )}
                      >
                        {a}
                      </button>
                    ))}
                  </div>
                  {assignedTo === "Partner" && (
                    <div className="mt-2">
                      <Field label="Partner">
                        <select
                          aria-label="Partner"
                          className={inputCls}
                          value={partnerName}
                          onChange={(e) => setPartnerName(e.target.value)}
                        >
                          {["Hope Africa", "Eagle Africa", "Bright Path", "Lumiere"].map((p) => (
                            <option key={p}>{p}</option>
                          ))}
                        </select>
                      </Field>
                    </div>
                  )}
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <div className="rounded-md border border-[var(--color-edify-border)] p-2.5">
                      <div className="text-caption muted font-semibold uppercase flex items-center gap-1">
                        <Wallet size={11} /> Est. Cost
                      </div>
                      <div className="text-[15px] font-extrabold tabular mt-0.5">
                        UGX {estCost.toLocaleString()}
                      </div>
                      <div className="text-caption muted">
                        {isCluster ? "per cluster session" : "per session"} · cost setting
                      </div>
                    </div>
                    <div className="rounded-md border border-[var(--color-edify-border)] p-2.5">
                      <div className="text-caption muted font-semibold uppercase flex items-center gap-1">
                        <CalendarDays size={11} /> Window
                      </div>
                      <div className="text-body font-bold mt-0.5">
                        {isCluster
                          ? clusterDate
                            ? new Date(clusterDate).toLocaleDateString("en-GB", { weekday: "long", day: "2-digit", month: "short" })
                            : "Pick exact date"
                          : `${month} · ${week}`}
                      </div>
                      <div className="text-caption muted">{isCluster ? clusterName : weekRangeFor(week)}</div>
                    </div>
                  </div>
                  <div className="mt-2">
                    <Field label="Notes (optional)">
                      <textarea
                        className={cn(inputCls, "h-[64px] py-2 leading-snug")}
                        value={notes}
                        onChange={(e) => setNotes(e.target.value)}
                        placeholder="Any context for the supervisor reviewing the plan…"
                      />
                    </Field>
                  </div>
                </Section>
              )}

              {/* Step 5: live conflicts */}
              {school && activity && (
                <Section
                  title="5. Conflict check"
                  subtitle="Surfaced live as you fill the form. Critical conflicts block submission for approval."
                >
                  {conflicts.length === 0 ? (
                    <div className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-success-soft)] px-3 py-2 flex items-center gap-2 text-body">
                      <CheckCircle2 size={14} className="text-[var(--color-success)]" />
                      <span>No conflicts detected. Plan is ready for submission.</span>
                    </div>
                  ) : (
                    <ul className="space-y-1.5">
                      {conflicts.map((c) => (
                        <li
                          key={c.id}
                          className="rounded-lg border border-[var(--color-edify-border)] bg-white px-3 py-2 flex items-start gap-2"
                        >
                          <AlertTriangle
                            size={13}
                            className={cn(
                              "mt-0.5 shrink-0",
                              c.severity === "Critical"
                                ? "text-[var(--color-danger)]"
                                : c.severity === "High"
                                  ? "text-[#9a3412]"
                                  : "text-[var(--color-edify-orange)]",
                            )}
                          />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                              <span className={cn("chip", severityClass(c.severity))}>{c.severity}</span>
                            </div>
                            <div className="text-[12px] mt-0.5">{c.message}</div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </Section>
              )}

              {!school && (
                <div className="rounded-xl border border-dashed border-[var(--color-edify-border)] p-6 text-center">
                  <div className="w-9 h-9 rounded-full mx-auto bg-[var(--color-edify-soft)] grid place-items-center text-[var(--color-edify-primary)]">
                    <Sparkles size={16} />
                  </div>
                  <div className="text-body font-semibold mt-2">Pick a school to begin</div>
                  <div className="text-[11.5px] muted">
                    Recommendations are SSA-driven. Staff schedule the work — they don&apos;t invent it.
                  </div>
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-5 py-3 border-t border-[var(--color-edify-border)] flex items-center justify-between gap-2 bg-white">
              <div className="text-[11.5px] muted flex items-center gap-1.5">
                <Users size={12} />
                Saving will route to{" "}
                <span className="font-semibold text-[var(--color-edify-text)]">Country Program Lead</span> for plan approval.
              </div>
              <div className="flex items-center gap-2">
                <button type="button" className="btn btn-sm" onClick={onClose}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={!canDraft}
                  onClick={() => handleSave("Draft")}
                >
                  <Save size={12} />
                  Save as Draft
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={!canSubmit}
                  onClick={() => handleSave("Submitted for Approval")}
                >
                  <Send size={12} />
                  Submit for Approval
                </button>
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

// ─── small layout helpers ───
const inputCls =
  "w-full h-9 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white text-body focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30";

function Section({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="text-body font-bold">{title}</div>
      {subtitle && <div className="text-[11.5px] muted mt-0.5 mb-2">{subtitle}</div>}
      {children}
    </section>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block text-caption uppercase tracking-wide text-[var(--color-edify-muted)] font-semibold mb-1">
        {label}
      </span>
      {children}
    </label>
  );
}

function weekRangeFor(week: string) {
  const ranges: Record<string, string> = {
    "Week 1": "(5–9 May)",
    "Week 2": "(12–16 May)",
    "Week 3": "(19–23 May)",
    "Week 4": "(26–30 May)",
    "Week 5": "(2–6 Jun)",
  };
  return ranges[week] ?? "";
}

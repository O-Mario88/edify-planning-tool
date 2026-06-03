"use client";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { useDialogA11y } from "@/components/ui/useDialogA11y";
import { useDemoStore } from "@/components/demo/DemoStore";
import { X, AlertTriangle, CalendarDays, Save, CheckCircle2, UserCheck } from "lucide-react";
import { leaveRequests, type LeaveType } from "@/lib/leave-mock";
import { plannedActivities as seedPlannedActivities, type PlannedActivityRow } from "@/lib/planning-mock";
import { GlassDatePicker } from "@/components/ui/GlassDatePicker";
import { cn } from "@/lib/utils";

// May/June 2025 week dates lookup map for accurate conflict matching
const WEEK_DATES: Record<string, { start: string; end: string }> = {
  "May / Week 1": { start: "2025-05-05", end: "2025-05-09" },
  "May / Week 2": { start: "2025-05-12", end: "2025-05-16" },
  "May / Week 3": { start: "2025-05-19", end: "2025-05-23" },
  "May / Week 4": { start: "2025-05-26", end: "2025-05-30" },
  "May / Week 5": { start: "2025-06-02", end: "2025-06-06" },
  "Jun / Week 1": { start: "2025-06-02", end: "2025-06-06" },
  "Jun / Week 2": { start: "2025-06-09", end: "2025-06-13" },
  "Jun / Week 3": { start: "2025-06-16", end: "2025-06-20" },
  "Jun / Week 4": { start: "2025-06-23", end: "2025-06-27" },
  "Jul / Week 1": { start: "2025-06-30", end: "2025-07-04" },
  "Jul / Week 2": { start: "2025-07-07", end: "2025-07-11" },
  "Jul / Week 3": { start: "2025-07-14", end: "2025-07-18" },
};

function getDatesInRange(startISO: string, endISO: string): string[] {
  const dates: string[] = [];
  const s = new Date(startISO + "T00:00:00");
  const e = new Date(endISO + "T00:00:00");
  if (isNaN(s.getTime()) || isNaN(e.getTime())) return [];
  for (let d = new Date(s); d <= e; d.setDate(d.getDate() + 1)) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    dates.push(`${y}-${m}-${day}`);
  }
  return dates;
}

type LeaveConflict = {
  activity: PlannedActivityRow;
  weekName: string;
  rangeLabel: string;
};

// Detect planned activity conflicts with the proposed leave dates
function detectLeaveConflicts(
  startDate: string,
  endDate: string,
  activities: PlannedActivityRow[]
): LeaveConflict[] {
  if (!startDate || !endDate) return [];
  const conflicts: LeaveConflict[] = [];

  for (const act of activities) {
    const weekKey = act.schedule.line1;
    const range = WEEK_DATES[weekKey];
    if (range) {
      // Overlap formula: start1 <= end2 && end1 >= start2
      if (startDate <= range.end && endDate >= range.start) {
        conflicts.push({
          activity: act,
          weekName: weekKey,
          rangeLabel: act.schedule.line2,
        });
      }
    }
  }
  return conflicts;
}

export function AddLeaveDrawer({
  open,
  onClose,
  onSave,
  activitiesList = seedPlannedActivities,
}: {
  open: boolean;
  onClose: () => void;
  onSave: (leaveId: string, count: number) => void;
  activitiesList?: PlannedActivityRow[];
}) {
  const [leaveType, setLeaveType] = useState<LeaveType>("Annual Leave");
  const [startDate, setStartDate] = useState("2025-05-12"); // default to mock week 2
  const [endDate, setEndDate] = useState("2025-05-14");
  const [notes, setNotes] = useState("");

  const drawerRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  useDialogA11y({ open, onClose, containerRef: drawerRef });

  const { pushToast } = useDemoStore();

  const conflicts = useMemo(
    () => detectLeaveConflicts(startDate, endDate, activitiesList),
    [startDate, endDate, activitiesList]
  );

  const canSubmit = !!startDate && !!endDate && startDate <= endDate;

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
    setLeaveType("Annual Leave");
    setStartDate("2025-05-12");
    setEndDate("2025-05-14");
    setNotes("");
  };

  const handleSave = () => {
    if (!canSubmit) return;
    const dates = getDatesInRange(startDate, endDate);
    const leaveId = `LV-${Date.now()}`;

    // Mutate the mock database state so other tools immediately see the blocked dates
    leaveRequests.push({
      leaveId,
      staffId: "STF-DM-014", // Daniel Mwangi (CCEO Planner)
      staffName: "Daniel Mwangi",
      region: "Central",
      leaveType,
      startDate,
      endDate,
      selectedDates: dates,
      validLeaveDates: dates,
      excludedDates: [],
      excludedReasonByDate: {},
      workingDays: dates.length,
      approvalStatus: "Approved", // Auto-approved in the interactive prototype
      planningImpact: "Blocked",
      affectedActivityIds: conflicts.map((c) => `${c.activity.schoolName}-${c.weekName}`),
    });

    onSave(leaveId, conflicts.length);

    pushToast({
      tone: "success",
      title: "Leave dates scheduled successfully",
      body: `${leaveType} set from ${new Date(startDate).toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
      })} to ${new Date(endDate).toLocaleDateString("en-GB", {
        day: "2-digit",
        month: "short",
      })}. ${conflicts.length} conflicting activities flagged.`,
    });

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
            className="fixed top-0 right-0 bottom-0 w-[580px] max-w-[95vw] bg-white z-50 shadow-2xl flex flex-col focus:outline-none"
          >
            {/* Header */}
            <div className="px-5 py-4 border-b border-[var(--color-edify-border)] flex items-start justify-between">
              <div>
                <h2 id={titleId} className="text-[16px] font-extrabold tracking-tight flex items-center gap-2">
                  <CalendarDays size={18} className="text-[var(--color-edify-primary)]" />
                  Schedule Leave Dates
                </h2>
                <p className="text-[12px] muted mt-0.5">
                  Set your upcoming leave. The Planning Engine automatically blocks these dates and warns you of any activity overlaps.
                </p>
              </div>
              <button
                type="button"
                onClick={onClose}
                aria-label="Close Schedule Leave drawer"
                className="w-8 h-8 rounded-md hover:bg-[var(--color-edify-soft)] grid place-items-center"
              >
                <X size={16} />
              </button>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              {/* Step 1: Pick Leave Type */}
              <Section
                title="1. Leave category"
                subtitle="Choose the classification of your leave. Approved leaves protect your rest and excuse shortfalls."
              >
                <div className="grid grid-cols-2 gap-2 mt-2">
                  {(["Annual Leave", "Medical Leave", "Personal Leave", "Other"] as LeaveType[]).map((opt) => (
                    <button
                      key={opt}
                      type="button"
                      onClick={() => setLeaveType(opt)}
                      className={cn(
                        "px-3 py-2 rounded-xl border text-body font-semibold text-left transition-colors flex items-center justify-between",
                        leaveType === opt
                          ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)] text-[var(--color-edify-dark)] font-bold shadow-sm"
                          : "border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/50"
                      )}
                    >
                      <span>{opt}</span>
                      {leaveType === opt && <span className="w-2 h-2 rounded-full bg-[var(--color-edify-primary)]" />}
                    </button>
                  ))}
                </div>
              </Section>

              {/* Step 2: Date Picker */}
              <Section
                title="2. Select leave dates"
                subtitle="Provide the starting and ending dates. Public holidays and Sundays are automatically excluded from working days."
              >
                <div className="grid grid-cols-2 gap-3 mt-2">
                  <Field label="Start date">
                    <GlassDatePicker
                      value={startDate}
                      onChange={setStartDate}
                      placeholder="dd/mm/yyyy"
                    />
                  </Field>
                  <Field label="End date">
                    <GlassDatePicker
                      value={endDate}
                      onChange={setEndDate}
                      min={startDate}
                      placeholder="dd/mm/yyyy"
                    />
                  </Field>
                </div>
                {startDate && endDate && startDate > endDate && (
                  <div className="mt-2 text-[11.5px] text-[var(--color-danger)] font-semibold flex items-center gap-1.5">
                    <AlertTriangle size={12} />
                    Start date cannot be after end date.
                  </div>
                )}
              </Section>

              {/* Step 3: Conflict Check */}
              <Section
                title="3. Live calendar overlap check"
                subtitle="The Planning Engine scans your active May/June 2025 school activities in real-time."
              >
                {conflicts.length === 0 ? (
                  <div className="rounded-xl border border-transparent bg-[#ecfdf5] border-[#dcfce7] p-3 flex items-start gap-2.5 mt-2">
                    <CheckCircle2 size={15} className="text-green-600 mt-0.5 shrink-0" />
                    <div className="text-body text-[#166534] leading-tight">
                      <div className="font-bold">No scheduling conflicts!</div>
                      <div className="text-[11.5px] mt-0.5">Your proposed leave dates do not overlap with any planned school visits or cluster trainings.</div>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2 mt-2">
                    <div className="rounded-xl border border-transparent bg-[#fffbeb] border-[#fef3c7] p-3 flex items-start gap-2.5">
                      <AlertTriangle size={15} className="text-[#d97706] mt-0.5 shrink-0" />
                      <div className="text-body text-amber-800 leading-tight">
                        <div className="font-bold">Overlapping Activities Found ({conflicts.length})</div>
                        <div className="text-[11.5px] mt-0.5">
                          Scheduling this leave will block planning on these dates. The overlapping activities will be flagged in red and need to be rescheduled or reassigned.
                        </div>
                      </div>
                    </div>

                    <div className="rounded-xl border border-[var(--color-edify-border)] divide-y divide-[var(--color-edify-divider)] overflow-hidden bg-white max-h-[180px] overflow-y-auto scrollbar">
                      {conflicts.map((c, i) => (
                        <div key={i} className="p-2.5 flex items-center justify-between gap-3 text-[12px]">
                          <div className="min-w-0">
                            <span className="font-semibold text-[var(--color-edify-text)] truncate block">
                              {c.activity.schoolName}
                            </span>
                            <span className="text-[11px] muted">
                              {c.activity.recommended} · {c.activity.district}
                            </span>
                          </div>
                          <div className="text-right shrink-0">
                            <span className="chip chip-soft text-[10px] font-bold block">{c.weekName}</span>
                            <span className="text-[10px] muted block mt-0.5">{c.rangeLabel}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </Section>

              {/* Step 4: Notes */}
              <Section title="4. Leave context" subtitle="Provide any brief details for your supervisor to review.">
                <textarea
                  className={cn(inputCls, "h-[72px] py-2 leading-snug mt-2")}
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Notes, handover plans, or contact info during leave..."
                />
              </Section>
            </div>

            {/* Footer */}
            <div className="px-5 py-3 border-t border-[var(--color-edify-border)] flex items-center justify-between gap-2 bg-white">
              <div className="text-[11.5px] muted flex items-center gap-1.5">
                <UserCheck size={12} className="text-[var(--color-edify-primary)]" />
                <span>Auto-routed for supervisor approval.</span>
              </div>
              <div className="flex items-center gap-2">
                <button type="button" className="btn btn-sm" onClick={onClose}>
                  Cancel
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={!canSubmit}
                  onClick={handleSave}
                >
                  <Save size={12} />
                  Schedule Leave
                </button>
              </div>
            </div>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

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
      {subtitle && <div className="text-[11.5px] muted mt-0.5 mb-2 leading-snug">{subtitle}</div>}
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

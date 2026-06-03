"use client";

// PartnerScheduleDrawer — the partner's "schedule activity" surface.
// Opened from an Assigned card in the Partner Action Inbox. Captures
// the planned week + date + facilitator + duration + delivery method
// + notes, and transitions the activity AssignedToPartner →
// ScheduledByPartner. Also exposes the three escape hatches:
// Request date change · Unable to support · Cancel.

import { useState } from "react";
import { X, Calendar, Clock, User as UserIcon, MapPin, FileText, AlertTriangle, CheckCircle2 } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { cn } from "@/lib/utils";
import { GlassDatePicker } from "@/components/ui/GlassDatePicker";

export type ScheduleDraft = {
  weekKey: string;
  preferredDate?: string;
  facilitator: string;
  durationHours: string;
  deliveryMethod: "in_person" | "virtual" | "hybrid";
  notes: string;
};

export type ScheduleOutcome =
  | { kind: "scheduled"; draft: ScheduleDraft }
  | { kind: "request_change"; reason: string }
  | { kind: "unable"; reason: string };

const WEEKS = [
  { key: "wk-22", label: "This Week (May 12 - May 18)" },
  { key: "wk-23", label: "Next week (May 19 - May 25)" },
  { key: "wk-24", label: "Week of May 26 - Jun 1" },
  { key: "wk-25", label: "Week of Jun 2 - Jun 8" },
];

export function PartnerScheduleDrawer({
  open,
  activityLabel,
  schoolName,
  urgency,
  onClose,
  onSubmit,
}: {
  open: boolean;
  activityLabel: string;
  schoolName: string;
  urgency: "Critical" | "High" | "Medium" | "Low";
  onClose: () => void;
  onSubmit: (outcome: ScheduleOutcome) => void;
}) {
  const [tab, setTab] = useState<"schedule" | "request" | "unable">("schedule");
  const [draft, setDraft] = useState<ScheduleDraft>({
    weekKey: "wk-22",
    preferredDate: "",
    facilitator: "",
    durationHours: "2",
    deliveryMethod: "in_person",
    notes: "",
  });
  const [reason, setReason] = useState("");

  function reset() {
    setTab("schedule");
    setDraft({ weekKey: "wk-22", preferredDate: "", facilitator: "", durationHours: "2", deliveryMethod: "in_person", notes: "" });
    setReason("");
  }

  function handleClose() {
    reset();
    onClose();
  }

  function handleSubmit() {
    if (tab === "schedule") {
      onSubmit({ kind: "scheduled", draft });
    } else if (tab === "request") {
      onSubmit({ kind: "request_change", reason });
    } else {
      onSubmit({ kind: "unable", reason });
    }
    handleClose();
  }

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.15 }}
            onClick={handleClose}
            className="fixed inset-0 bg-black/40 z-40 backdrop-blur-sm"
            aria-hidden
          />
          <motion.aside
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 320, damping: 32 }}
            className="fixed top-0 right-0 bottom-0 w-full sm:w-[480px] bg-white z-50 shadow-2xl flex flex-col"
            aria-label="Schedule activity"
          >
            {/* Header */}
            <header className="flex items-start justify-between gap-3 px-5 pt-5 pb-3 border-b border-[var(--color-edify-divider)]">
              <div className="min-w-0">
                <p className="text-caption uppercase tracking-wider font-bold text-[var(--color-edify-muted)]">
                  Schedule Activity
                </p>
                <h2 className="text-[16px] font-extrabold tracking-tight leading-tight mt-1 truncate">
                  {activityLabel}
                </h2>
                <p className="text-[11.5px] muted leading-tight mt-1 flex items-center gap-1.5">
                  <MapPin size={11} className="text-[var(--color-edify-primary)]" />
                  {schoolName}
                  <UrgencyChip urgency={urgency} />
                </p>
              </div>
              <button
                type="button"
                onClick={handleClose}
                aria-label="Close"
                className="h-8 w-8 rounded-md hover:bg-[var(--color-edify-soft)] grid place-items-center text-[var(--color-edify-muted)]"
              >
                <X size={16} />
              </button>
            </header>

            {/* Tabs */}
            <div className="flex items-center gap-1 px-5 pt-3">
              <TabBtn active={tab === "schedule"} onClick={() => setTab("schedule")}>
                Schedule
              </TabBtn>
              <TabBtn active={tab === "request"} onClick={() => setTab("request")}>
                Request date change
              </TabBtn>
              <TabBtn active={tab === "unable"} onClick={() => setTab("unable")}>
                Unable to support
              </TabBtn>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {tab === "schedule" && (
                <div className="space-y-3.5">
                  <Field label="Planned week" Icon={Calendar}>
                    <select
                      className={inputCls}
                      value={draft.weekKey}
                      onChange={(e) => setDraft({ ...draft, weekKey: e.target.value })}
                    >
                      {WEEKS.map((w) => (
                        <option key={w.key} value={w.key}>{w.label}</option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Preferred date (optional)" Icon={Calendar}>
                    <GlassDatePicker
                      value={draft.preferredDate}
                      onChange={(iso) => setDraft({ ...draft, preferredDate: iso })}
                    />
                  </Field>
                  <Field label="Facilitator" Icon={UserIcon}>
                    <input
                      type="text"
                      placeholder="Who is delivering this?"
                      className={inputCls}
                      value={draft.facilitator}
                      onChange={(e) => setDraft({ ...draft, facilitator: e.target.value })}
                    />
                  </Field>
                  <div className="grid grid-cols-2 gap-3">
                    <Field label="Duration (hours)" Icon={Clock}>
                      <input
                        type="number"
                        min={1}
                        max={8}
                        className={inputCls}
                        value={draft.durationHours}
                        onChange={(e) => setDraft({ ...draft, durationHours: e.target.value })}
                      />
                    </Field>
                    <Field label="Delivery method" Icon={MapPin}>
                      <select
                        className={inputCls}
                        value={draft.deliveryMethod}
                        onChange={(e) => setDraft({ ...draft, deliveryMethod: e.target.value as ScheduleDraft["deliveryMethod"] })}
                      >
                        <option value="in_person">In person</option>
                        <option value="virtual">Virtual</option>
                        <option value="hybrid">Hybrid</option>
                      </select>
                    </Field>
                  </div>
                  <Field label="Notes (optional)" Icon={FileText}>
                    <textarea
                      rows={3}
                      placeholder="Anything the staff monitor should know"
                      className={inputCls + " resize-none"}
                      value={draft.notes}
                      onChange={(e) => setDraft({ ...draft, notes: e.target.value })}
                    />
                  </Field>
                  <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 flex items-start gap-2 mt-2">
                    <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
                    <p className="text-[11.5px] text-emerald-800 leading-snug">
                      Once scheduled, this activity appears on your CCEO's monitoring dashboard so they know it's in your plan.
                    </p>
                  </div>
                </div>
              )}

              {tab === "request" && (
                <ReasonForm
                  label="Reason for date change request"
                  placeholder="e.g. School term break overlaps with planned date — proposing to shift by one week."
                  value={reason}
                  onChange={setReason}
                  tone="amber"
                  note="Your CCEO will see this request and can approve a new date or keep the original."
                />
              )}

              {tab === "unable" && (
                <ReasonForm
                  label="Reason you cannot support this activity"
                  placeholder="e.g. Facilitator is on extended leave and we have no qualified backup."
                  value={reason}
                  onChange={setReason}
                  tone="rose"
                  note="This will return the activity to the assigning CCEO for reassignment to another partner."
                />
              )}
            </div>

            {/* Footer */}
            <footer className="flex items-center justify-between gap-2 px-5 py-3 border-t border-[var(--color-edify-divider)] bg-[var(--color-edify-soft)]/40">
              <button
                type="button"
                onClick={handleClose}
                className="h-9 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSubmit}
                disabled={(tab !== "schedule" && !reason) || (tab === "schedule" && !draft.facilitator)}
                className="inline-flex items-center gap-1.5 h-9 px-4 rounded-md bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold disabled:opacity-50 disabled:cursor-not-allowed hover:bg-[var(--color-edify-dark)]"
              >
                {tab === "schedule" ? "Confirm schedule" : tab === "request" ? "Send request" : "Send to CCEO"}
              </button>
            </footer>
          </motion.aside>
        </>
      )}
    </AnimatePresence>
  );
}

// ────────── small bits ──────────

const inputCls =
  "w-full h-9 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-body focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30";

function TabBtn({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "h-8 px-3 rounded-md text-[11.5px] font-semibold transition-colors",
        active
          ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
          : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
      )}
    >
      {children}
    </button>
  );
}

function Field({ label, Icon, children }: { label: string; Icon: typeof Calendar; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-caption uppercase tracking-wider font-bold text-[var(--color-edify-muted)] flex items-center gap-1.5 mb-1.5">
        <Icon size={11} />
        {label}
      </span>
      {children}
    </label>
  );
}

function ReasonForm({
  label, placeholder, value, onChange, tone, note,
}: {
  label: string;
  placeholder: string;
  value: string;
  onChange: (v: string) => void;
  tone: "amber" | "rose";
  note: string;
}) {
  const toneCls = tone === "rose"
    ? "border-rose-200 bg-rose-50 text-rose-800"
    : "border-amber-200 bg-amber-50 text-amber-800";
  return (
    <div className="space-y-3.5">
      <Field label={label} Icon={AlertTriangle}>
        <textarea
          rows={5}
          placeholder={placeholder}
          className={inputCls + " resize-none h-auto"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </Field>
      <div className={cn("rounded-xl border px-3 py-2.5 flex items-start gap-2", toneCls)}>
        <AlertTriangle size={14} className="shrink-0 mt-0.5" />
        <p className="text-[11.5px] leading-snug">{note}</p>
      </div>
    </div>
  );
}

function UrgencyChip({ urgency }: { urgency: "Critical" | "High" | "Medium" | "Low" }) {
  const map = {
    Critical: "bg-rose-100 text-rose-700",
    High:     "bg-rose-50 text-rose-700",
    Medium:   "bg-amber-50 text-amber-700",
    Low:      "bg-emerald-50 text-emerald-700",
  } as const;
  return (
    <span className={cn("inline-flex items-center px-1.5 py-[1px] rounded-md text-[9.5px] font-extrabold uppercase tracking-wide ml-1", map[urgency])}>
      {urgency}
    </span>
  );
}

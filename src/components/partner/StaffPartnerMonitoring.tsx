"use client";

// StaffPartnerMonitoring — the CCEO/staff view of all partner work
// they've assigned. Solves the "lose sight of partner work" problem
// from the workflow spec: every status the activity moves through
// remains visible to the staff who assigned it, with delay alerts
// surfaced when SLAs slip, until the school journey closes.
//
// Tabs map 1-to-1 to the workflow state machine in partner-workflow.ts,
// so the same activity can never appear in two tabs at once.

import { useState } from "react";
import {
  AlertTriangle, Building2, Handshake, CheckCircle2, RotateCcw,
  Flag, XCircle, MoreHorizontal, ArrowRight,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  staffMonitorTabs,
  staffMonitorRows,
  delayAlerts,
  monitorEvidenceLink,
  type StaffMonitorTabKey,
  type StaffMonitorRow,
  type DelayAlert,
} from "@/lib/partner/partner-monitoring-mock";
import { STATUS_LABEL, STATUS_TONE } from "@/lib/partner/partner-workflow";
import { evidenceSummaries } from "@/lib/partner/partner-evidence-mock";

// Status tone → chip classes. Same colour vocabulary as the partner
// dashboard so a CCEO and a partner see the same activity at the same
// status the same way.
const TONE_CLS: Record<string, string> = {
  neutral: "bg-slate-100 text-slate-700",
  info:    "bg-blue-50 text-blue-700",
  warn:    "bg-amber-50 text-amber-700",
  danger:  "bg-rose-50 text-rose-700",
  success: "bg-emerald-50 text-emerald-700",
  muted:   "bg-slate-50 text-slate-600",
};

// Tab → which workflow statuses appear under it.
const TAB_STATUSES: Record<StaffMonitorTabKey, ReadonlyArray<string>> = {
  assigned:            ["AssignedToPartner"],
  scheduled:           ["ScheduledByPartner"],
  delayed:             ["Delayed"],
  dueThisWeek:         ["ScheduledByPartner", "Delivered"],
  evidenceSubmitted:   ["EvidenceSubmitted", "AwaitingCceoConfirmation"],
  needsMyConfirmation: ["AwaitingCceoConfirmation"],
  paymentPending:      ["ConfirmedByCceo", "AwaitingPlApproval", "ApprovedByPl", "SentToAccountant"],
  completed:           ["Paid", "Closed"],
};

export function StaffPartnerMonitoring() {
  const [active, setActive] = useState<StaffMonitorTabKey>("needsMyConfirmation");
  const [toast, setToast] = useState<string | null>(null);

  const visibleRows = staffMonitorRows.filter((r) =>
    TAB_STATUSES[active].includes(r.status),
  );

  function handleAction(row: StaffMonitorRow, action: "confirm" | "return" | "flag" | "reject") {
    const labels: Record<typeof action, string> = {
      confirm: `Confirmed — ${row.school} routed to PL for payment approval.`,
      return:  `Returned to partner — ${row.school} needs evidence correction.`,
      flag:    `Flagged for review — escalated to Program Lead.`,
      reject:  `Rejected — payment will not move forward for this activity.`,
    };
    setToast(labels[action]);
    setTimeout(() => setToast(null), 3500);
  }

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
              <Handshake size={14} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Partner Activity Monitoring</h3>
          </div>
          <p className="text-[12px] muted mt-1">
            Every partner activity you assigned — from schedule through evidence to payment.
          </p>
        </div>
      </header>

      {/* Delay alerts band — only renders when there are alerts. */}
      {delayAlerts.length > 0 && (
        <div className="mb-3 space-y-2">
          {delayAlerts.map((a) => (
            <DelayAlertRow key={a.id} alert={a} />
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 overflow-x-auto scrollbar -mx-1 px-1 pb-1.5 border-b border-[var(--color-edify-divider)]">
        {staffMonitorTabs.map((t) => {
          const isActive = active === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setActive(t.key)}
              className={cn(
                "inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-[11.5px] font-semibold whitespace-nowrap transition-colors",
                isActive
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
              )}
            >
              {t.label}
              {t.count > 0 && (
                <span
                  className={cn(
                    "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold",
                    isActive ? "bg-[var(--color-edify-primary)] text-white" : "bg-slate-100 text-slate-700",
                  )}
                >
                  {t.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Rows */}
      <div className="overflow-auto scrollbar -mx-1 px-1 mt-3 max-h-[480px] rounded-md">
        {visibleRows.length === 0 ? (
          <div className="text-center py-8 text-[12px] muted italic">
            Nothing in this queue right now.
          </div>
        ) : (
          <table className="w-full dtable">
            <thead className="sticky top-0 z-10 bg-white">
              <tr>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">School</th>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Partner</th>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Activity</th>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Status</th>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Evidence</th>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">When / Amount</th>
                <th className="text-right text-[10px] uppercase tracking-wide font-bold muted">Action</th>
              </tr>
            </thead>
            <tbody>
              {visibleRows.map((r) => {
                const evidenceId = monitorEvidenceLink[r.id];
                const ev = evidenceId
                  ? evidenceSummaries.find((e) => e.activityId === evidenceId)
                  : undefined;
                return (
                  <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/40 transition-colors">
                    <td>
                      <div className="flex items-center gap-2">
                        <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                          <Building2 size={11} />
                        </span>
                        <div className="min-w-0">
                          <div className="text-body font-semibold leading-tight truncate">{r.school}</div>
                          <div className="text-caption muted leading-tight">{r.district}</div>
                        </div>
                      </div>
                    </td>
                    <td className="text-[12px]">{r.partner}</td>
                    <td>
                      <div className="text-[12px] font-semibold leading-tight">{r.activity}</div>
                      <div className="text-caption muted leading-tight mt-0.5">{r.activitySub}</div>
                    </td>
                    <td>
                      <span className={cn(
                        "inline-flex items-center px-2 py-[3px] rounded-md text-caption font-bold whitespace-nowrap",
                        TONE_CLS[STATUS_TONE[r.status]],
                      )}>
                        {STATUS_LABEL[r.status]}
                      </span>
                    </td>
                    <td>
                      {ev ? (
                        <div className="leading-tight">
                          <div className={cn(
                            "text-[12px] font-extrabold tabular",
                            ev.completenessScore >= 80 ? "text-emerald-700" :
                            ev.completenessScore >= 50 ? "text-amber-700" :
                            "text-rose-700",
                          )}>
                            {ev.completenessScore}%
                          </div>
                          <div className="text-[10px] muted mt-0.5">
                            {ev.criticalMissingCount > 0
                              ? `${ev.criticalMissingCount} critical missing`
                              : `${ev.uploadedCount}/${ev.requiredCount} items`}
                          </div>
                        </div>
                      ) : (
                        <span className="muted text-[11px]">—</span>
                      )}
                    </td>
                    <td className="text-[11.5px]">
                      {r.delayDays != null ? (
                        <span className="text-rose-700 font-semibold">{r.delayDays} days delayed</span>
                      ) : r.scheduledWeek ? (
                        <span className="text-[var(--color-edify-text)]">{r.scheduledWeek}</span>
                      ) : r.amountUgx ? (
                        <span className="font-semibold text-[var(--color-edify-text)]">UGX {(r.amountUgx / 1000).toFixed(0)}K</span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td className="text-right">
                      <RowActions row={r} onAction={handleAction} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-[var(--color-edify-deep)] text-white text-body font-semibold px-4 py-3 max-w-[400px]">
          {toast}
        </div>
      )}
    </section>
  );
}

function DelayAlertRow({ alert }: { alert: DelayAlert }) {
  const tone = alert.severity === "danger"
    ? "border-rose-200 bg-rose-50 text-rose-800"
    : "border-amber-200 bg-amber-50 text-amber-800";
  return (
    <div className={cn("rounded-xl border px-3 py-2.5 flex items-start gap-2.5", tone)}>
      <AlertTriangle size={14} className="shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <div className="text-[12px] font-extrabold leading-tight">{alert.message}</div>
        <div className="text-[11px] mt-0.5 leading-snug opacity-90">{alert.recommendedAction}</div>
      </div>
      <button
        type="button"
        className="text-[11px] font-bold underline shrink-0 whitespace-nowrap"
      >
        Take action
      </button>
    </div>
  );
}

function RowActions({
  row, onAction,
}: {
  row: StaffMonitorRow;
  onAction: (row: StaffMonitorRow, action: "confirm" | "return" | "flag" | "reject") => void;
}) {
  const [open, setOpen] = useState(false);
  const showConfirm = row.status === "AwaitingCceoConfirmation" || row.status === "EvidenceSubmitted";

  // Evidence gate: pull the linked summary (if any) so the Confirm
  // CTA is disabled when evidence is incomplete. This is the system's
  // protection against the "accidental confirm" pattern from the spec.
  const evidenceId = monitorEvidenceLink[row.id];
  const evidence = evidenceId
    ? evidenceSummaries.find((e) => e.activityId === evidenceId)
    : undefined;
  const evidenceBlocking = !!evidence && !evidence.isReadyForCceoConfirmation;
  const tooltip = evidenceBlocking
    ? `Evidence ${evidence.completenessScore}% complete · ${evidence.criticalMissingCount} critical item${evidence.criticalMissingCount === 1 ? "" : "s"} missing. Return to partner for correction first.`
    : undefined;

  return (
    <div className="relative inline-flex items-center gap-1">
      {showConfirm && (
        <button
          type="button"
          onClick={() => !evidenceBlocking && onAction(row, "confirm")}
          disabled={evidenceBlocking}
          title={tooltip}
          className={cn(
            "inline-flex items-center justify-center h-8 px-3 rounded-md text-[11.5px] font-extrabold whitespace-nowrap transition-colors",
            evidenceBlocking
              ? "bg-slate-100 text-slate-400 cursor-not-allowed"
              : "bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]",
          )}
        >
          {evidenceBlocking ? "Evidence Incomplete" : "Confirm"}
          {!evidenceBlocking && <ArrowRight size={11} className="ml-1" />}
        </button>
      )}
      {showConfirm && evidenceBlocking && (
        <button
          type="button"
          onClick={() => onAction(row, "return")}
          className="inline-flex items-center justify-center h-8 px-3 rounded-md text-[11.5px] font-extrabold bg-amber-500 text-white hover:bg-amber-600 whitespace-nowrap"
        >
          Return for correction
        </button>
      )}
      {!showConfirm && (
        <button
          type="button"
          className="inline-flex items-center justify-center h-8 px-3 rounded-md text-[11.5px] font-semibold border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60 whitespace-nowrap"
        >
          Monitor
        </button>
      )}
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label="More actions"
        className="h-8 w-8 grid place-items-center rounded-md border border-[var(--color-edify-border)] bg-white hover:bg-[var(--color-edify-soft)]/60"
      >
        <MoreHorizontal size={13} className="text-[var(--color-edify-muted)]" />
      </button>
      {open && (
        <div className="absolute right-0 top-9 z-20 w-56 rounded-lg border border-[var(--color-edify-border)] bg-white shadow-lg py-1">
          <MenuItem Icon={CheckCircle2} label="Confirm completed" tone="emerald" onClick={() => { setOpen(false); onAction(row, "confirm"); }} />
          <MenuItem Icon={RotateCcw} label="Return to partner" tone="amber" onClick={() => { setOpen(false); onAction(row, "return"); }} />
          <MenuItem Icon={Flag} label="Flag for review" tone="amber" onClick={() => { setOpen(false); onAction(row, "flag"); }} />
          <MenuItem Icon={XCircle} label="Reject confirmation" tone="rose" onClick={() => { setOpen(false); onAction(row, "reject"); }} />
        </div>
      )}
    </div>
  );
}

function MenuItem({
  Icon, label, tone, onClick,
}: {
  Icon: typeof CheckCircle2;
  label: string;
  tone: "emerald" | "amber" | "rose";
  onClick: () => void;
}) {
  const cls = tone === "emerald"
    ? "text-emerald-700"
    : tone === "amber"
      ? "text-amber-700"
      : "text-rose-700";
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left px-3 py-2 text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/60 inline-flex items-center gap-2"
    >
      <Icon size={12} className={cls} />
      {label}
    </button>
  );
}

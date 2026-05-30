"use client";

import { useId, useMemo, useRef, useState } from "react";
import { X, ShieldCheck, AlertTriangle, FileText, ArrowUpRight } from "lucide-react";
import {
  pipGate,
  supportReviewCases,
  notificationCopyFor,
  type StaffTargetRow,
  type SupportReviewCase,
} from "@/lib/team-targets-mock";
import { cn } from "@/lib/utils";
import { useDialogA11y } from "@/components/ui/useDialogA11y";
import { useDemoStore } from "@/components/demo/DemoStore";

const CHECKLIST: { key: keyof SupportReviewCase; label: string }[] = [
  { key: "workloadCapacityReview",    label: "Workload + capacity reviewed" },
  { key: "leaveHolidayImpactReview",  label: "Leave + holiday impact considered" },
  { key: "routeDifficultyReview",     label: "Route quality + travel difficulty reviewed" },
  { key: "schoolAccessReview",        label: "School access challenges reviewed" },
  { key: "fundingDelayReview",        label: "Funding delay impact reviewed" },
  { key: "partnerDependencyReview",   label: "Partner dependency reviewed" },
  { key: "salesforceIssueReview",     label: "Salesforce / system issues reviewed" },
  { key: "planApprovalDelayReview",   label: "Plan approval delays reviewed" },
  { key: "staffContextNotes",         label: "Staff context (voluntarily shared) noted" },
  { key: "supervisorSupportHistory",  label: "Supervisor support history reviewed" },
  { key: "targetFairnessReview",      label: "Target fairness vs school load reviewed" },
];

export function SupportReviewDrawer({
  staff,
  onClose,
}: {
  staff: StaffTargetRow;
  onClose: () => void;
}) {
  const existing = useMemo(
    () => supportReviewCases.find((c) => c.staffId === staff.staffId),
    [staff.staffId],
  );

  const [supportPlanCreated, setSupportPlanCreated] = useState(existing?.supportPlanCreated ?? false);
  const [reportCompleted, setReportCompleted] = useState(existing?.reviewReportCompleted ?? false);
  const [escalated, setEscalated] = useState(false);

  const drawerRef = useRef<HTMLElement | null>(null);
  const titleId = useId();
  useDialogA11y({ open: true, onClose, containerRef: drawerRef });
  const { pushToast } = useDemoStore();

  // Helper: emit a toast + audit-like trace when supervisor advances the
  // workflow. In production each of these would also POST to the support
  // review API; here the localStorage overlay carries state across navs.
  function trace(step: "plan" | "report" | "escalate") {
    if (step === "plan") {
      pushToast({
        tone: "info",
        title: `Support plan created for ${staff.staffName}`,
        body: "Workload, leave, route, funding, partner, and Salesforce factors documented.",
      });
    } else if (step === "report") {
      pushToast({
        tone: "info",
        title: `Review report completed for ${staff.staffName}`,
        body: "Context, support history, and recommended actions ready for leadership.",
      });
    } else {
      pushToast({
        tone: "warning",
        title: `Escalated for HR-led performance review`,
        body: `${staff.staffName} — audit entry recorded. HR decision happens outside this dashboard.`,
      });
    }
  }

  const gate = pipGate({
    ...(existing ?? {} as SupportReviewCase),
    supportPlanCreated,
    reviewReportCompleted: reportCompleted,
    pipEscalationAllowed: false,
  });

  const isMidYear = staff.midYearBelow40Triggered;

  return (
    <div className="fixed inset-0 z-50 bg-[rgba(15,23,32,0.45)] flex items-stretch justify-end" onClick={onClose}>
      <aside
        ref={drawerRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="w-[640px] max-w-full bg-white shadow-2xl flex flex-col focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="px-5 py-4 border-b border-[var(--color-edify-border)] flex items-start gap-3">
          <div className="w-10 h-10 rounded-full bg-[var(--color-edify-primary)] text-white text-[12px] font-bold grid place-items-center shrink-0">
            {staff.initials}
          </div>
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-[16px] font-extrabold tracking-tight">{staff.staffName}</h2>
            <div className="text-[12px] muted">{staff.role} · {staff.region} · Achievement {staff.achievementPercent}%</div>
          </div>
          <button type="button" aria-label="Close support review" onClick={onClose} className="h-8 w-8 rounded-md border border-[var(--color-edify-border)] grid place-items-center">
            <X size={14} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {isMidYear && (
            <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-3">
              <div className="text-body font-bold text-emerald-800 inline-flex items-center gap-1.5">
                <ShieldCheck size={13} />
                Possible Performance Improvement Review Required
              </div>
              <div className="text-[12px] text-emerald-900 mt-1 leading-snug">
                {notificationCopyFor("mid-year")}
              </div>
            </div>
          )}

          {/* Target snapshot */}
          <div className="rounded-xl border border-[var(--color-edify-border)] p-3">
            <div className="text-[12px] font-bold mb-2">Target snapshot</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
              <Snap label="Trainings completed" v={staff.targetCategoryProgress.trainingsCompleted} />
              <Snap label="Valid visits"        v={staff.targetCategoryProgress.validVisits} />
              <Snap label="SSA completion"      v={staff.targetCategoryProgress.ssaCompletion} />
              <Snap label="Salesforce logging"  v={staff.targetCategoryProgress.salesforceLogging} />
              <Snap label="Core school targets" v={staff.targetCategoryProgress.coreSchoolTargets} />
            </div>
          </div>

          {/* Context */}
          <div className="rounded-xl border border-[var(--color-edify-border)] p-3">
            <div className="text-[12px] font-bold mb-2">Context indicators</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]">
              <Ctx label="Approved leave days"           v={staff.approvedLeaveDays} />
              <Ctx label="Blocked planning days"         v={staff.blockedPlanningDays} />
              <Ctx label="Route difficulty (0–100)"      v={staff.routeDifficultyIndex} />
              <Ctx label="Funding delay (days)"          v={staff.fundingDelayDays} />
              <Ctx label="Unresolved Salesforce issues"  v={staff.unresolvedSalesforceIssues} />
              <Ctx label="Partner dependency blocks"     v={staff.partnerDependencyBlocks} />
            </div>
          </div>

          {/* Checklist */}
          <div className="rounded-xl border border-[var(--color-edify-border)] p-3">
            <div className="text-[12px] font-bold mb-2">Support review checklist</div>
            <ul className="space-y-1 text-[12px]">
              {CHECKLIST.map((c) => {
                const filled = Boolean(existing?.[c.key]);
                return (
                  <li key={String(c.key)} className="flex items-start gap-2">
                    <span className={cn(
                      "mt-1 w-3.5 h-3.5 rounded-sm border grid place-items-center",
                      filled ? "bg-emerald-500 border-emerald-500 text-white" : "border-[var(--color-edify-border)] bg-white",
                    )}>
                      {filled && <span className="text-[9px] font-bold">✓</span>}
                    </span>
                    <span className={filled ? "" : "muted"}>
                      {c.label}
                      {filled && existing && typeof existing[c.key] === "string" && (
                        <span className="muted"> — {String(existing[c.key])}</span>
                      )}
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>

          {/* Recommended support actions */}
          <div className="rounded-xl border border-[var(--color-edify-border)] p-3">
            <div className="text-[12px] font-bold mb-2">Recommended support actions</div>
            <ul className="space-y-1 text-[12px]">
              {(existing?.recommendedSupportActions ?? staff.recommendedSupportActions).map((a, i) => (
                <li key={i} className="flex items-start gap-2">
                  <span className="mt-1.5 w-1.5 h-1.5 rounded-full bg-[var(--color-edify-primary)] shrink-0" />
                  {a}
                </li>
              ))}
            </ul>
          </div>

          {/* Report form (mock) */}
          <div className="rounded-xl border border-[var(--color-edify-border)] p-3">
            <div className="text-[12px] font-bold mb-2 inline-flex items-center gap-1.5">
              <FileText size={12} />
              Program Lead support report
            </div>
            <textarea
              rows={4}
              defaultValue={existing?.staffContextNotes ?? ""}
              placeholder="Document context, support already provided, and recommended next steps. This report must be complete before any escalation."
              className="w-full p-2 rounded-md border border-[var(--color-edify-border)] bg-white text-body focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </div>
        </div>

        <footer className="px-5 py-3 border-t border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setSupportPlanCreated(true);
              trace("plan");
            }}
            className={cn("btn btn-sm", supportPlanCreated && "bg-emerald-600 text-white border-emerald-600")}
          >
            {supportPlanCreated ? "Support plan created" : "Create Support Plan"}
          </button>
          <button
            type="button"
            onClick={() => {
              setReportCompleted(true);
              trace("report");
            }}
            disabled={!supportPlanCreated}
            className={cn("btn btn-sm", reportCompleted && "bg-emerald-600 text-white border-emerald-600", !supportPlanCreated && "opacity-55 cursor-not-allowed")}
          >
            {reportCompleted ? "Review report completed" : "Prepare Review Report"}
          </button>
          <div className="flex-1" />
          <button
            type="button"
            disabled={!gate.allowed || escalated}
            title={gate.reason}
            onClick={() => {
              setEscalated(true);
              trace("escalate");
            }}
            className={cn(
              "h-8 px-3 rounded-md text-[12px] font-semibold border inline-flex items-center gap-1.5",
              gate.allowed
                ? escalated
                  ? "bg-emerald-600 text-white border-emerald-600"
                  : "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]"
                : "bg-white border-[var(--color-edify-border)] text-[var(--color-edify-muted)] cursor-not-allowed",
            )}
          >
            <ArrowUpRight size={12} />
            {escalated ? "Escalated for HR review" : "Escalate for PIP Review"}
          </button>
        </footer>

        {!gate.allowed && (
          <div className="px-5 py-2 bg-amber-50 border-t border-amber-200 text-[11.5px] text-amber-800 flex items-center gap-1.5">
            <AlertTriangle size={12} />
            {gate.reason}
          </div>
        )}
      </aside>
    </div>
  );
}

function Snap({ label, v }: { label: string; v: number }) {
  const tone =
    v >= 80 ? "text-emerald-700" :
    v >= 60 ? "text-amber-700"  :
    v >= 40 ? "text-orange-700" :
              "text-rose-700";
  return (
    <div className="flex items-center justify-between">
      <span className="muted">{label}</span>
      <span className={cn("font-extrabold tabular", tone)}>{v}%</span>
    </div>
  );
}

function Ctx({ label, v }: { label: string; v: number }) {
  return (
    <div className="flex items-center justify-between">
      <span className="muted">{label}</span>
      <span className="font-semibold tabular">{v}</span>
    </div>
  );
}

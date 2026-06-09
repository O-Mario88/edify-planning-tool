"use client";

// Card-level components extracted from PlanBuilderDesktopView. They sit
// next to the main view as siblings — none of them hold business logic
// beyond local UI state (e.g. SubmittedBatchesStrip's localStorage-backed
// approval simulation).

import { useEffect, useState } from "react";
import { Calendar, ChevronRight, CheckCircle2, Eye, Wallet } from "lucide-react";
import type { EvidencePanel } from "@/lib/plan-cost-calculator";
import type { PlanningWarning } from "@/lib/plan-builder-engine";
import { cn } from "@/lib/utils";
import { Mini, Row } from "@/components/planning/PlanBuilderParts";

type Tab = "staff" | "training" | "meeting" | "partner";

// ────────── Evidence panel (right-rail "why this visit") ──────────

export function EvidencePanelCard({ evidence }: { evidence: EvidencePanel | null }) {
  if (!evidence) {
    return (
      <div className="card p-3.5 sticky top-4">
        <div className="text-body font-extrabold tracking-tight uppercase muted mb-2 inline-flex items-center gap-2">
          <Eye size={11} />
          Why this visit?
        </div>
        <p className="text-[11.5px] muted leading-snug">
          Select a school to see the evidence behind the recommendation — SSA scores, training history, intervention
          weakness, and overdue follow-ups.
        </p>
      </div>
    );
  }
  return (
    <div className="card p-3.5 sticky top-4 space-y-2">
      <div className="text-body font-extrabold tracking-tight uppercase muted inline-flex items-center gap-2">
        <Eye size={11} />
        Why this visit?
      </div>
      <div className="text-[13px] font-extrabold tracking-tight">{evidence.schoolName}</div>
      <EvidenceBody panel={evidence} />
    </div>
  );
}

function EvidenceBody({ panel }: { panel: EvidencePanel }) {
  switch (panel.kind) {
    case "coaching":
      return (
        <div className="space-y-1.5 text-[11.5px]">
          <Row label="Intervention" value={panel.intervention} />
          <Row label="SSA score" value={panel.ssaScore.toFixed(1)} tone={panel.ssaScore < 5.5 ? "rose" : "edify"} />
          <p className="muted leading-snug pt-1">{panel.weaknessReason}</p>
        </div>
      );
    case "training-follow-up":
      return (
        <div className="space-y-1.5 text-[11.5px]">
          <Row label="Training" value={panel.trainingTitle} />
          <Row label="Date" value={panel.trainingDate} />
          <Row label="Intervention" value={panel.intervention} />
          <Row label="Provider" value={panel.provider} />
          <Row label="Facilitator" value={panel.facilitator} />
          <Row label="Days since" value={`${panel.daysSince}d`} tone={panel.daysSince > 30 ? "rose" : "edify"} />
          <Row label="Salesforce" value={panel.salesforceId} mono />
        </div>
      );
    case "partner-follow-up":
      return (
        <div className="space-y-1.5 text-[11.5px]">
          <Row label="Partner" value={panel.partnerName} />
          <Row label="Training" value={panel.trainingTitle} />
          <Row label="Date" value={panel.trainingDate} />
          <Row label="Intervention" value={panel.intervention} />
          <Row label="Days since" value={`${panel.daysSince}d`} tone={panel.daysSince > 60 ? "rose" : "edify"} />
        </div>
      );
    case "ssa":
      return (
        <div className="space-y-1.5 text-[11.5px]">
          <Row
            label="SSA score"
            value={panel.ssaScore == null ? "Not on record" : panel.ssaScore.toFixed(2)}
            tone={panel.ssaScore == null ? "rose" : "edify"}
          />
          <Row label="Last SSA" value={panel.lastSsaDate} />
          <p className="muted leading-snug pt-1">{panel.reason}</p>
        </div>
      );
    case "core":
      return (
        <div className="space-y-1.5 text-[11.5px]">
          <Row label="Last visit" value={panel.lastVisitDate} />
          <Row label="Gap" value={`${panel.gapDays}d`} tone={panel.gapDays > 60 ? "rose" : "edify"} />
        </div>
      );
    case "improvement":
      return (
        <div className="space-y-1.5 text-[11.5px]">
          <Row label="Weakest area" value={panel.weakestIntervention} />
          <Row label="SSA score" value={panel.ssaScore == null ? "—" : panel.ssaScore.toFixed(2)} />
        </div>
      );
    case "data-collection":
      return (
        <div className="space-y-1.5 text-[11.5px]">
          <Row label="Task" value={panel.task} />
        </div>
      );
  }
}

// ────────── Submitted batches strip (with localStorage approval state) ──────────

type ApprovalStatus = "PL Reviewing" | "Approved" | "Returned";

export function SubmittedBatchesStrip({
  batches,
  totalCost,
  totalActivities,
  onClear,
}: {
  batches: Array<{
    id: string;
    tab: Tab;
    label: string;
    summary: string;
    activities: number;
    totalCost: number;
    submittedAt: string;
  }>;
  totalCost: number;
  totalActivities: number;
  onClear: () => void;
}) {
  // Demo-time client-side approval state. In production this comes from the
  // PL approval workflow. Simulate controls only render with `?dev=1`.
  const [approvals, setApprovals] = useState<
    Record<string, { status: ApprovalStatus; reviewedAt?: string; reviewerNote?: string }>
  >({});
  const [devMode, setDevMode] = useState(false);
  // One-shot client-side hydration from localStorage + URL search.
  // Migrate to useSyncExternalStore during the React-19 sweep.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    try {
      const raw = localStorage.getItem("cceo.batchApprovals");
      if (raw) setApprovals(JSON.parse(raw));
    } catch {
      /* ignore */
    }
    if (typeof window !== "undefined") {
      setDevMode(new URLSearchParams(window.location.search).has("dev"));
    }
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  function statusFor(id: string): ApprovalStatus {
    return approvals[id]?.status ?? "PL Reviewing";
  }
  function simulate(id: string, status: ApprovalStatus, note?: string) {
    const next = {
      ...approvals,
      [id]: {
        status,
        reviewedAt: new Date().toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" }),
        reviewerNote: note,
      },
    };
    setApprovals(next);
    try {
      localStorage.setItem("cceo.batchApprovals", JSON.stringify(next));
    } catch {
      /* ignore */
    }
  }

  const counts = {
    reviewing: batches.filter((b) => statusFor(b.id) === "PL Reviewing").length,
    approved: batches.filter((b) => statusFor(b.id) === "Approved").length,
    returned: batches.filter((b) => statusFor(b.id) === "Returned").length,
  };

  return (
    <div className="card p-3.5 bg-emerald-50/60 border-emerald-200 space-y-2">
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2 text-emerald-900">
          <CheckCircle2 size={14} className="text-emerald-600" />
          Submitted batches ({batches.length}) — Program Lead approval status
        </h3>
        <div className="text-[11px] muted flex items-center gap-2 flex-wrap">
          <span className="font-extrabold text-emerald-900">{totalActivities} activities</span>
          <span>·</span>
          <span className="font-extrabold text-emerald-900">UGX {totalCost.toLocaleString()}</span>
          <span>·</span>
          <span>
            <span className="font-extrabold text-amber-700">{counts.reviewing}</span> reviewing ·{" "}
            <span className="font-extrabold text-emerald-700">{counts.approved}</span> approved
            {counts.returned > 0 && (
              <>
                {" "}
                · <span className="font-extrabold text-rose-700">{counts.returned}</span> returned
              </>
            )}
          </span>
        </div>
      </div>
      <ul className="space-y-1.5">
        {batches.slice(0, 6).map((b) => {
          const s = statusFor(b.id);
          const rec = approvals[b.id];
          return (
            <li
              key={b.id}
              className={cn(
                "rounded-xl border bg-white p-2.5 space-y-1",
                s === "Returned" ? "border-rose-200" : s === "Approved" ? "border-emerald-300" : "border-emerald-200",
              )}
            >
              <div className="flex items-baseline justify-between gap-2 flex-wrap">
                <div className="min-w-0">
                  <span className="text-caption muted font-bold uppercase tracking-wide mr-2">{b.label}</span>
                  <span className="text-body font-extrabold tracking-tight">{b.summary}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                      s === "Approved"
                        ? "bg-emerald-100 text-emerald-700"
                        : s === "Returned"
                          ? "bg-rose-100    text-rose-700"
                          : "bg-amber-100   text-amber-800",
                    )}
                  >
                    {s}
                  </span>
                  <span className="text-caption muted whitespace-nowrap">UGX {b.totalCost.toLocaleString()}</span>
                </div>
              </div>
              <div className="text-caption muted">
                Submitted {b.submittedAt}
                {rec?.reviewedAt && <> · PL reviewed {rec.reviewedAt}</>}
              </div>
              {s === "Returned" && rec?.reviewerNote && (
                <div className="rounded-lg bg-rose-50 border border-rose-200 px-2.5 py-1.5 text-[11px] text-rose-900 leading-snug">
                  <span className="font-extrabold">PL note:</span> {rec.reviewerNote}
                </div>
              )}
              {devMode && (
                <div className="flex items-center gap-1.5 flex-wrap pt-0.5">
                  <span className="text-[10px] muted uppercase tracking-wide font-bold mr-1">Dev · simulate PL action:</span>
                  <button
                    type="button"
                    onClick={() => simulate(b.id, "Approved")}
                    className="h-6 px-2 rounded-md border border-emerald-200 bg-white text-caption font-extrabold text-emerald-800 hover:bg-emerald-50"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      simulate(b.id, "Returned", "Reduce week-2 visits to 5/day max; redistribute to week 3.")
                    }
                    className="h-6 px-2 rounded-md border border-rose-200 bg-white text-caption font-extrabold text-rose-700 hover:bg-rose-50"
                  >
                    Return with note
                  </button>
                  <button
                    type="button"
                    onClick={() => simulate(b.id, "PL Reviewing")}
                    className="h-6 px-2 rounded-md border border-amber-200 bg-white text-caption font-extrabold text-amber-800 hover:bg-amber-50"
                  >
                    Reset
                  </button>
                </div>
              )}
            </li>
          );
        })}
        {batches.length > 6 && (
          <li className="text-caption muted text-center">Showing first 6 of {batches.length}.</li>
        )}
      </ul>
      <div className="flex items-center gap-2 pt-1">
        {devMode && (
          <button
            type="button"
            onClick={onClear}
            className="h-7 px-2 rounded-md border border-emerald-200 bg-white text-caption font-extrabold text-emerald-800 hover:bg-emerald-100/60"
          >
            Clear submitted (dev)
          </button>
        )}
        <span className="text-caption muted">
          Approved batches generate todos in My Targets. Returned batches open the Program Lead note for clarification.
        </span>
      </div>
    </div>
  );
}

// ────────── Current batch actions ──────────

export function BatchActionsCard({
  tabLabel,
  hasItems,
  batchSummary,
  draft,
  hasBlockingErrors,
  onSubmit,
  onSaveDraft,
  onDiscard,
}: {
  tab: Tab;
  tabLabel: string;
  hasItems: boolean;
  batchSummary?: string;
  draft?: { summary: string; activities: number; totalCost: number; savedAt: string };
  hasBlockingErrors: boolean;
  onSubmit: () => void;
  onSaveDraft: () => void;
  onDiscard: () => void;
}) {
  if (!hasItems && !draft) {
    return (
      <div className="card p-3.5">
        <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">Current {tabLabel} batch</h3>
        <p className="text-[11.5px] muted leading-snug">
          Nothing selected yet. Pick items above to build a batch — one activity type at a time.
        </p>
      </div>
    );
  }
  return (
    <div className="card p-3.5 space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-body font-extrabold tracking-tight uppercase muted">Current {tabLabel} batch</h3>
        {hasBlockingErrors && (
          <span className="text-[10px] font-extrabold uppercase tracking-wide text-rose-700">Errors block submit</span>
        )}
      </div>
      {hasItems && batchSummary && (
        <div className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 px-3 py-2 text-[11.5px] leading-snug">
          <span className="font-extrabold text-[var(--color-edify-text)]">{batchSummary}</span>
        </div>
      )}
      {draft && !hasItems && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] text-amber-900 leading-snug">
          <span className="font-extrabold">Draft saved {draft.savedAt}.</span> {draft.summary} · UGX{" "}
          {draft.totalCost.toLocaleString()}. Re-open this tab to keep building.
        </div>
      )}
      {hasItems && (
        <div className="grid grid-cols-1 gap-2">
          <button
            type="button"
            onClick={onSubmit}
            disabled={hasBlockingErrors}
            className={cn(
              "h-10 rounded-xl text-body font-extrabold inline-flex items-center justify-center gap-1.5",
              hasBlockingErrors
                ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed"
                : "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white shadow-sm shadow-emerald-500/25",
            )}
          >
            <CheckCircle2 size={13} />
            Submit batch
          </button>
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={onSaveDraft}
              className="h-9 rounded-xl border border-[var(--color-edify-border)] bg-white text-[12px] font-extrabold hover:bg-[var(--color-edify-soft)]/40"
            >
              Save as draft
            </button>
            <button
              type="button"
              onClick={onDiscard}
              className="h-9 rounded-xl border border-rose-200 bg-white text-[12px] font-extrabold text-rose-700 hover:bg-rose-50"
            >
              Discard
            </button>
          </div>
        </div>
      )}
      <p className="text-caption muted leading-snug">
        One activity batch at a time. Submitted batches become todos in My Targets, lines in the monthly budget request,
        and items in the Program Lead approval queue.
      </p>
    </div>
  );
}

// ────────── Tab switch modal ──────────

export function TabSwitchModal({
  fromLabel,
  toLabel,
  summary,
  hasBlockingErrors,
  onSubmit,
  onSaveDraft,
  onDiscard,
  onContinue,
}: {
  fromLabel: string;
  toLabel: string;
  summary: string;
  hasBlockingErrors: boolean;
  onSubmit: () => void;
  onSaveDraft: () => void;
  onDiscard: () => void;
  onContinue: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" role="dialog" aria-modal>
      <div className="card p-3.5 max-w-md w-full space-y-3">
        <h3 className="text-[15px] font-extrabold tracking-tight">Unfinished {fromLabel} batch</h3>
        <p className="text-[12px] muted leading-snug">
          You have an unfinished {fromLabel} schedule ({summary}). Submit it, save it as draft, or discard it before
          scheduling {toLabel}.
        </p>
        <div className="grid grid-cols-1 gap-2">
          <button
            type="button"
            onClick={onSubmit}
            disabled={hasBlockingErrors}
            className={cn(
              "h-10 rounded-xl text-body font-extrabold inline-flex items-center justify-center gap-1.5",
              hasBlockingErrors
                ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed"
                : "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white shadow-sm shadow-emerald-500/25",
            )}
          >
            Submit batch
          </button>
          <button
            type="button"
            onClick={onSaveDraft}
            className="h-10 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-extrabold hover:bg-[var(--color-edify-soft)]/40"
          >
            Save as draft
          </button>
          <button
            type="button"
            onClick={onDiscard}
            className="h-10 rounded-xl border border-rose-200 bg-white text-body font-extrabold text-rose-700 hover:bg-rose-50"
          >
            Discard batch
          </button>
          <button
            type="button"
            onClick={onContinue}
            className="h-9 rounded-xl text-[11.5px] font-extrabold text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/40"
          >
            Continue scheduling
          </button>
        </div>
        {hasBlockingErrors && (
          <p className="text-caption text-rose-700 leading-snug">
            Resolve planning errors before submitting, or save as draft and fix later.
          </p>
        )}
      </div>
    </div>
  );
}

// ────────── Right-rail selection summary ──────────

export function SelectionSummary({
  staffCount,
  trainingCount,
  meetingCount,
  partnerCount,
  estimatedBudget,
  warnings,
  totalSelected,
  staffVisitTotal,
  trainingTotal,
  meetingTotal,
  partnerTotal,
}: {
  staffCount: number;
  trainingCount: number;
  meetingCount: number;
  partnerCount: number;
  estimatedBudget: number;
  warnings: PlanningWarning[];
  totalSelected: number;
  staffVisitTotal: number;
  trainingTotal: number;
  meetingTotal: number;
  partnerTotal: number;
}) {
  const hasErrors = warnings.some((w) => w.level === "error");
  return (
    <div className="card p-3.5">
      <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">Your Plan</h3>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <Mini label="Staff" value={staffCount} tone="rose" />
        <Mini label="Training" value={trainingCount} tone="violet" />
        <Mini label="Meeting" value={meetingCount} tone="sky" />
        <Mini label="Partner" value={partnerCount} tone="amber" />
      </div>
      <div className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-3">
        <div className="flex items-center gap-2 mb-1.5 text-caption muted font-bold uppercase tracking-wide">
          <Wallet size={11} />
          Estimated budget
        </div>
        <div className="text-[20px] font-extrabold tabular leading-none">UGX {estimatedBudget.toLocaleString()}</div>
        <ul className="mt-2 text-caption muted space-y-0.5">
          <li className="flex justify-between">
            <span>Staff visits</span>
            <span className="tabular">UGX {staffVisitTotal.toLocaleString()}</span>
          </li>
          <li className="flex justify-between">
            <span>Cluster trainings</span>
            <span className="tabular">UGX {trainingTotal.toLocaleString()}</span>
          </li>
          <li className="flex justify-between">
            <span>Cluster meetings</span>
            <span className="tabular">UGX {meetingTotal.toLocaleString()}</span>
          </li>
          <li className="flex justify-between">
            <span>Partner visits</span>
            <span className="tabular">UGX {partnerTotal.toLocaleString()}</span>
          </li>
        </ul>
        <div className="text-[10px] muted mt-2">From active Country Cost Settings × selected activities.</div>
      </div>
      <button
        type="button"
        disabled={totalSelected === 0 || hasErrors}
        className={cn(
          "mt-3 w-full h-10 rounded-xl text-body font-extrabold inline-flex items-center justify-center gap-1.5",
          totalSelected === 0 || hasErrors
            ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)] cursor-not-allowed"
            : "bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white shadow-sm shadow-emerald-500/25",
        )}
      >
        <Calendar size={13} />
        Continue to schedule
        <ChevronRight size={13} />
      </button>
      {hasErrors && (
        <p className="text-caption text-rose-700 mt-2 text-center">Resolve planning errors before continuing.</p>
      )}
      {totalSelected === 0 && (
        <p className="text-caption muted mt-2 text-center">Pick at least one item from any tab.</p>
      )}
    </div>
  );
}

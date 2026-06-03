"use client";

// Role-aware project pipeline board. Rows are grouped by workflow stage; each
// row shows only the action buttons the current role may perform at that
// status (from the state machine). Actions that need input (Salesforce ID,
// return reason) prompt for it, then call the single workflow server action.

import { useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Sparkles, MapPin, AlertTriangle, Handshake } from "lucide-react";
import { cn } from "@/lib/utils";
import { StatusBadge } from "@/components/ui/primitives";
import { runProjectWorkflowAction } from "@/lib/actions/project-partner-actions";
import {
  availableActions,
  ACTION_LABEL,
  STATUS_LABEL,
  STATUS_TONE,
  PIPELINE_STAGES,
  type ProjectWorkflowStatus,
  type ProjectWorkflowAction,
} from "@/lib/projects/project-partner-workflow";

export type PipelineRowVM = {
  id: string;
  projectId: string;
  projectShortName: string;
  schoolName: string;
  schoolId?: string;
  district?: string;
  intervention: string;
  activityType: string;
  partnerName?: string;
  salesforceActivityId?: string;
  salesforceType?: "visit" | "training";
  evidenceNote?: string;
  returnReason?: string;
  paymentRef?: string;
  workflowStatus: ProjectWorkflowStatus;
};

const BRANCH_STATUSES: ProjectWorkflowStatus[] = ["ReturnedForCorrection", "Rejected", "ReturnedByIA", "OnHold"];

const ACTION_BTN_TONE: Partial<Record<ProjectWorkflowAction, string>> = {
  returnEvidence: "border-amber-300 text-amber-700 hover:bg-amber-50",
  rejectWork: "border-rose-300 text-rose-700 hover:bg-rose-50",
  iaReturn: "border-amber-300 text-amber-700 hover:bg-amber-50",
};

export function ProjectActivityPipeline({ rows, userRole }: { rows: PipelineRowVM[]; userRole: string }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function run(row: PipelineRowVM, action: ProjectWorkflowAction) {
    setError(null);
    const patch: { salesforceActivityId?: string; returnReason?: string; evidenceNote?: string } = {};
    if (action === "enterSalesforceId") {
      const prefix = row.salesforceType === "training" ? "TS-" : "SV-";
      const id = window.prompt(`Enter the Salesforce ID (${prefix} for this ${row.salesforceType ?? "activity"}):`, prefix);
      if (!id) return;
      patch.salesforceActivityId = id.trim();
    }
    if (action === "returnEvidence" || action === "rejectWork" || action === "iaReturn") {
      const reason = window.prompt("Reason:");
      if (!reason) return;
      patch.returnReason = reason.trim();
    }
    setBusyId(row.id);
    startTransition(async () => {
      const res = await runProjectWorkflowAction(row.id, action, patch);
      setBusyId(null);
      if (!res.ok) {
        setError(res.reason === "FORBIDDEN" ? "You don't have permission for that step." : res.message);
        return;
      }
      router.refresh();
    });
  }

  const groups: { status: ProjectWorkflowStatus; label: string; rows: PipelineRowVM[] }[] = [
    ...PIPELINE_STAGES.map((st) => ({ status: st, label: STATUS_LABEL[st], rows: rows.filter((r) => r.workflowStatus === st) })),
  ];
  const needsAttention = rows.filter((r) => BRANCH_STATUSES.includes(r.workflowStatus));

  function Row({ row }: { row: PipelineRowVM }) {
    const actions = availableActions(row.workflowStatus, userRole);
    return (
      <li className="rounded-lg border border-[var(--color-edify-border)] p-2.5">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <Link href={`/projects/${row.projectId}`} className="text-[12.5px] font-extrabold hover:text-[var(--color-edify-primary)] hover:underline">{row.projectShortName}</Link>
              <span className="px-1.5 py-[1px] rounded text-[10px] font-bold bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">{row.intervention}</span>
              <StatusBadge tone={STATUS_TONE[row.workflowStatus]}>{STATUS_LABEL[row.workflowStatus]}</StatusBadge>
            </div>
            <div className="mt-0.5 text-[11.5px] muted flex items-center gap-x-3 flex-wrap">
              <span>{row.activityType}</span>
              {row.schoolId ? <Link href={`/schools/${row.schoolId}`} className="hover:underline inline-flex items-center gap-1"><MapPin size={9} />{row.schoolName}</Link> : <span>{row.schoolName}</span>}
              {row.partnerName && <span className="inline-flex items-center gap-1"><Handshake size={9} />{row.partnerName}</span>}
              {row.salesforceActivityId && <span className="tabular">SF: {row.salesforceActivityId}</span>}
              {row.paymentRef && <span className="tabular text-emerald-700">{row.paymentRef}</span>}
            </div>
            {row.returnReason && <div className="mt-1 text-[11px] text-amber-700 inline-flex items-start gap-1"><AlertTriangle size={11} className="mt-0.5" />{row.returnReason}</div>}
          </div>
          <div className="flex items-center gap-1.5 flex-wrap shrink-0">
            {actions.length === 0 ? (
              <span className="text-[11px] muted">No action for your role</span>
            ) : actions.map((a) => (
              <button
                key={a}
                type="button"
                disabled={pending && busyId === row.id}
                onClick={() => run(row, a)}
                className={cn(
                  "h-8 px-2.5 rounded-lg border text-[11.5px] font-bold transition-colors",
                  ACTION_BTN_TONE[a] ?? "border-[var(--color-edify-primary)] bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]",
                )}
              >
                {busyId === row.id && pending ? "…" : ACTION_LABEL[a]}
              </button>
            ))}
          </div>
        </div>
      </li>
    );
  }

  if (rows.length === 0) {
    return (
      <div className="card rounded-2xl p-10 text-center">
        <Sparkles size={22} className="mx-auto text-[var(--color-edify-muted)]" />
        <p className="mt-2 text-[13px] font-bold">No partner project activities in the pipeline.</p>
        <p className="text-[12px] muted mt-0.5">Assign a project activity to a partner to start the execution→payment flow.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {error && (
        <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] text-rose-700 inline-flex items-start gap-1.5">
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />{error}
        </div>
      )}
      {needsAttention.length > 0 && (
        <section className="card rounded-2xl p-3.5 border-amber-200">
          <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5 text-amber-800">
            <AlertTriangle size={14} /> Needs attention ({needsAttention.length})
          </h2>
          <ul className="mt-2 space-y-1.5">{needsAttention.map((r) => <Row key={r.id} row={r} />)}</ul>
        </section>
      )}
      {groups.map((g) => (
        <section key={g.status} className="card rounded-2xl p-3.5">
          <div className="flex items-center justify-between">
            <h2 className="text-[13px] font-extrabold tracking-tight">{g.label}</h2>
            <span className="text-[11px] muted tabular">{g.rows.length}</span>
          </div>
          {g.rows.length > 0 ? (
            <ul className="mt-2 space-y-1.5">{g.rows.map((r) => <Row key={r.id} row={r} />)}</ul>
          ) : (
            <p className="mt-2 text-[11.5px] muted">None at this stage.</p>
          )}
        </section>
      ))}
    </div>
  );
}

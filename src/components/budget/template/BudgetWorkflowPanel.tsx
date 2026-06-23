"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  CalendarCheck, ChevronRight, ClipboardCheck, Landmark, Send, Users, Wallet,
} from "lucide-react";
import type { EdifyRole } from "@/lib/auth-public";
import type { BeFundRequest } from "@/lib/api/surfaces";
import {
  buildBudgetWorkflow,
  workflowAsStepper,
  type BudgetWorkflowStage,
} from "@/lib/budget/budget-workflow";
import { ApprovalWorkflowStepper } from "@/components/budget/ApprovalWorkflowStepper";
import { cn } from "@/lib/utils";

const STAGE_ICONS: Record<string, typeof Wallet> = {
  plan: CalendarCheck,
  "cceo-pl": Users,
  "staff-cd": ClipboardCheck,
  "cd-admin": Landmark,
  "rvp-final": Send,
  disburse: Wallet,
};

type Props = {
  role: EdifyRole;
  activityCount: number;
  costMissingCount: number;
};

export function BudgetWorkflowPanel({ role, activityCount, costMissingCount }: Props) {
  const [fundRequests, setFundRequests] = useState<BeFundRequest[]>([]);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(() => {
    fetch("/api/fund-requests", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => {
        if (j.live && Array.isArray(j.requests)) setFundRequests(j.requests as BeFundRequest[]);
      })
      .finally(() => setLoaded(true));
  }, []);

  useEffect(load, [load]);

  const stages = buildBudgetWorkflow(role, { activityCount, costMissingCount, fundRequests });
  const stepper = workflowAsStepper(stages);
  const currentStage = stages.find((s) => s.status === "current");

  return (
    <div className="bg-white border border-[var(--color-edify-border)] rounded-lg overflow-hidden">
      <div className="bg-[var(--color-edify-dark)] text-white text-[11px] font-extrabold uppercase tracking-wider px-3 py-2 flex items-center justify-between">
        <span>Approval workflow</span>
        {currentStage && (
          <span className="text-[10px] font-semibold normal-case tracking-normal text-white/80">
            Your stage: {currentStage.label}
          </span>
        )}
      </div>

      <div className="p-4 border-b border-[var(--color-edify-divider)] hidden md:block">
        <ApprovalWorkflowStepper steps={stepper} />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="bg-[var(--color-edify-soft)]/60 text-[10px] uppercase tracking-wide text-[var(--color-edify-dark)]">
              <th className="text-left font-bold px-3 py-2">Stage</th>
              <th className="text-left font-bold px-3 py-2">Route</th>
              <th className="text-left font-bold px-3 py-2 min-w-[120px]">Progress</th>
              <th className="text-left font-bold px-3 py-2">Status</th>
              <th className="text-right font-bold px-3 py-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {stages.map((s) => (
              <WorkflowRow key={s.id} stage={s} loaded={loaded} />
            ))}
          </tbody>
        </table>
      </div>

      {!loaded && (
        <p className="px-3 py-2 text-[10px] muted border-t border-[var(--color-edify-divider)]">
          Loading live fund-request status…
        </p>
      )}
    </div>
  );
}

function WorkflowRow({ stage, loaded }: { stage: BudgetWorkflowStage; loaded: boolean }) {
  const Icon = STAGE_ICONS[stage.id] ?? ClipboardCheck;
  const tone =
    stage.status === "complete"
      ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-dark)]"
      : stage.status === "current"
        ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] ring-1 ring-[var(--color-edify-primary)]/30"
        : stage.status === "waiting"
          ? "bg-amber-50 text-amber-800"
          : "bg-slate-50 text-slate-500";

  return (
    <tr className={cn("border-t border-[var(--color-edify-divider)]", stage.status === "current" && "bg-[var(--color-edify-soft)]/25")}>
      <td className="px-3 py-2.5">
        <span className="inline-flex items-center gap-2 font-semibold text-[var(--color-edify-text)]">
          <Icon size={14} className="text-[var(--color-edify-primary)] shrink-0" />
          {stage.label}
          {!stage.live && (
            <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">
              Soon
            </span>
          )}
        </span>
      </td>
      <td className="px-3 py-2.5 text-[var(--color-edify-muted)] max-w-[220px]">{stage.detail}</td>
      <td className="px-3 py-2.5">
        <div className="h-2.5 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
          <div
            className="h-full rounded-full bg-[var(--color-edify-primary)] transition-all"
            style={{ width: `${loaded ? stage.progressPct : 0}%` }}
          />
        </div>
      </td>
      <td className="px-3 py-2.5">
        <span className={cn("inline-block px-2 py-0.5 rounded text-[10px] font-extrabold uppercase", tone)}>
          {stage.statusLabel}
        </span>
      </td>
      <td className="px-3 py-2.5 text-right">
        {stage.actionHref && stage.actionLabel ? (
          <Link
            href={stage.actionHref}
            className="inline-flex items-center gap-0.5 text-[10px] font-bold text-[var(--color-edify-primary)] hover:underline"
          >
            {stage.actionLabel}
            <ChevronRight size={12} />
          </Link>
        ) : (
          <span className="text-[10px] muted">—</span>
        )}
      </td>
    </tr>
  );
}

"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowUpRight,
  Cloud,
} from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  cceoSalesforceQueue,
  type CceoSalesforceRow,
  type CceoSfMatchStatus,
} from "@/lib/cceo-mock";
import { useDemoStore } from "@/components/demo/DemoStore";
import { cn } from "@/lib/utils";

// Match-status → inline action mapping. Smart Match → Confirm,
// Possible Match → Review, No Match → Create ID. Once tapped, the row
// flips to a "Submitted" pill — same one-shot pattern as the Training
// Follow-Up card.

type ActionConfig = { label: string; tone: "primary" | "neutral" };

const ACTION_BY_STATUS: Record<CceoSfMatchStatus, ActionConfig> = {
  "Smart Match":    { label: "Confirm",   tone: "primary" },
  "Possible Match": { label: "Review",    tone: "neutral" },
  "No Match":       { label: "Create ID", tone: "neutral" },
  "Submitted":      { label: "Submitted", tone: "neutral" },
};

const STATUS_TONE: Record<CceoSfMatchStatus, { chip: string; dot: string }> = {
  "Smart Match":    { chip: "bg-emerald-50 text-emerald-700", dot: "bg-emerald-500" },
  "Possible Match": { chip: "bg-amber-50   text-amber-700",   dot: "bg-amber-500"   },
  "No Match":       { chip: "bg-rose-50    text-rose-700",    dot: "bg-rose-500"    },
  "Submitted":      { chip: "bg-slate-50   text-slate-600",   dot: "bg-slate-400"   },
};

export function CceoSalesforceQueueCard() {
  const { pushToast } = useDemoStore();
  // Local one-shot state — flips a row to "Submitted" the moment its
  // primary action is tapped, so the queue gives instant feedback
  // without a server roundtrip.
  const [submitted, setSubmitted] = useState<Record<string, true>>({});

  function handleAction(r: CceoSalesforceRow) {
    setSubmitted((prev) => ({ ...prev, [r.key]: true }));
    pushToast({
      tone: "success",
      title: `${ACTION_BY_STATUS[r.matchStatus].label} sent`,
      body: `${r.school} routed to Salesforce.`,
    });
  }

  return (
    <SectionCard
      icon={<Cloud size={13} />}
      title="Salesforce Completion Queue"
      subtitle="This Month"
      actions={
        <Link
          href="/queue"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View All
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* Internal scroll container — fixed max-height keeps the card the
          same physical size whether 5 rows or 50, so the dashboard's
          row alignment stays stable. */}
      <div className="rounded-xl border border-[var(--color-edify-border)] bg-white overflow-hidden">
        <div className="grid grid-cols-[1.6fr_72px_120px_96px] gap-2 px-3 py-2 bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600 font-bold">
          <div>School</div>
          <div className="text-right">Completed</div>
          <div>Match Status</div>
          <div className="text-right">Action</div>
        </div>
        <div className="max-h-[224px] overflow-y-auto scrollbar divide-y divide-[var(--color-edify-divider)]">
          {cceoSalesforceQueue.map((r) => {
            const isSubmitted = !!submitted[r.key];
            const statusKey: CceoSfMatchStatus = isSubmitted ? "Submitted" : r.matchStatus;
            const tone = STATUS_TONE[statusKey];
            const action = ACTION_BY_STATUS[statusKey];
            return (
              <div
                key={r.key}
                className="grid grid-cols-[1.6fr_72px_120px_96px] gap-2 px-3 py-2.5 items-center text-[11.5px]"
              >
                <div className="font-semibold text-slate-900 leading-tight truncate">{r.school}</div>
                <div className="text-right tabular muted">{r.completedOn}</div>
                <div>
                  <span className={cn("inline-flex items-center gap-1.5 px-2 py-[2px] rounded-md text-caption font-extrabold", tone.chip)}>
                    <span className={cn("w-1.5 h-1.5 rounded-full", tone.dot)} />
                    {statusKey}
                  </span>
                </div>
                <div className="text-right">
                  <button
                    type="button"
                    disabled={isSubmitted}
                    onClick={() => !isSubmitted && handleAction(r)}
                    className={cn(
                      "btn btn-sm whitespace-nowrap",
                      action.tone === "primary" && !isSubmitted && "btn-primary",
                      isSubmitted && "opacity-60",
                    )}
                  >
                    {action.label}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11px] muted">
        Smart Match auto-confirms; Possible Match needs review; No Match opens the Salesforce form.
      </div>
    </SectionCard>
  );
}

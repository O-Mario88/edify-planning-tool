"use client";

// RiskBottleneckBoard — "What needs attention", grouped by risk type.
// Each item is action-oriented: a count, the reason, the owner, and a
// one-tap route to the recommended action. This is the dashboard's
// answer to "what is blocking, and what do I do about it?"

import Link from "next/link";
import { ArrowRight, ShieldAlert } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { cceoRiskBoard, type CceoRiskType } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

// Risk type → chip tone. Light + dark variants so it reads in every
// theme (mirrors the StatusBadge tone convention).
const RISK_TONE: Record<CceoRiskType, string> = {
  Planning:     "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  Execution:    "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  Verification: "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300",
  Partner:      "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
  Payment:      "bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300",
  Performance:  "bg-sky-100 text-sky-700 dark:bg-sky-500/15 dark:text-sky-300",
};

export function RiskBottleneckBoard() {
  return (
    <SectionCard
      title="What Needs Attention"
      subtitle="Risks grouped by type — each with an owner and the next action"
      icon={<ShieldAlert size={13} />}
    >
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
        {cceoRiskBoard.map((r) => (
          <div
            key={r.type}
            className="rounded-xl border border-[var(--border-card)] bg-[var(--surface-1)] p-3 flex items-start gap-3"
          >
            <div className="shrink-0 w-9 text-center">
              <div className="text-[22px] font-semibold tabular leading-none text-[var(--text-primary)]">
                {r.count}
              </div>
            </div>
            <div className="min-w-0 flex-1">
              <span
                className={cn(
                  "inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-semibold uppercase tracking-wide",
                  RISK_TONE[r.type],
                )}
              >
                {r.type} Risk
              </span>
              <p className="text-[12px] text-[var(--text-primary)] mt-1.5 leading-snug">{r.reason}</p>
              <p className="text-[11px] muted mt-1">
                Owner: <span className="font-semibold text-[var(--text-secondary)]">{r.owner}</span>
              </p>
              <Link
                href={r.href}
                className="mt-2 inline-flex items-center gap-1 h-7 px-2.5 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-semibold hover:bg-[var(--color-edify-dark)] transition-colors"
              >
                {r.action}
                <ArrowRight size={11} />
              </Link>
            </div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

export default RiskBottleneckBoard;

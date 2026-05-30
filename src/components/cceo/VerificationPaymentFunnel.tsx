"use client";

// VerificationPaymentFunnel — the operations→finance pipeline made
// visible. Every completed activity must walk Completed → Evidence →
// Salesforce ID → PL verify → IA verify → Accountant → Paid. The biggest
// stage-to-stage drop is the bottleneck; we surface it with an insight
// sentence and a one-tap route to clear it.

import Link from "next/link";
import { ArrowRight, AlertTriangle, GitMerge } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { cceoVerificationFunnel } from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

export function VerificationPaymentFunnel() {
  const stages = cceoVerificationFunnel;
  const max = stages[0]?.count || 1;

  // Bottleneck = the largest drop between consecutive stages.
  let bottleneckIdx = 1;
  let biggestDrop = -1;
  for (let i = 1; i < stages.length; i++) {
    const drop = stages[i - 1].count - stages[i].count;
    if (drop > biggestDrop) {
      biggestDrop = drop;
      bottleneckIdx = i;
    }
  }
  const bn = stages[bottleneckIdx];
  const bnFrom = stages[bottleneckIdx - 1];

  return (
    <SectionCard
      title="Verification & Payment Pipeline"
      subtitle="Completed → Evidence → Salesforce ID → PL → IA → Accountant → Paid"
      icon={<GitMerge size={13} />}
    >
      <div className="space-y-1.5">
        {stages.map((s, i) => {
          const pct = Math.max(6, Math.round((s.count / max) * 100));
          const isBottleneck = i === bottleneckIdx;
          return (
            <Link key={s.key} href={s.href} className="group block" title={`Open ${s.label}`}>
              <div className="flex items-center gap-3">
                <div className="w-36 shrink-0 text-[11.5px] muted group-hover:text-[var(--text-primary)] transition-colors truncate">
                  {s.label}
                </div>
                <div className="flex-1 h-6 rounded-md bg-[var(--surface-2)] overflow-hidden relative">
                  <div
                    className={cn(
                      "h-full rounded-md transition-all duration-500",
                      isBottleneck ? "bg-amber-500/75" : "bg-[var(--color-edify-primary)]/70 group-hover:bg-[var(--color-edify-primary)]",
                    )}
                    style={{ width: `${pct}%` }}
                  />
                </div>
                <div className="w-9 text-right text-[13px] font-semibold tabular text-[var(--text-primary)]">
                  {s.count}
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      {/* Bottleneck insight + action — connects operations to finance. */}
      <div className="mt-3 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2.5 flex items-start gap-2">
        <AlertTriangle size={14} className="text-amber-500 mt-0.5 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-[12px] text-[var(--text-primary)] leading-snug">
            <span className="font-semibold">Main bottleneck:</span> {biggestDrop} activities drop between{" "}
            <span className="font-semibold">{bnFrom.label}</span> and{" "}
            <span className="font-semibold">{bn.label}</span>.
          </p>
          <Link
            href={bn.href}
            className="mt-1.5 inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline"
          >
            Clear the {bn.label.toLowerCase()} bottleneck
            <ArrowRight size={12} />
          </Link>
        </div>
      </div>
    </SectionCard>
  );
}

export default VerificationPaymentFunnel;

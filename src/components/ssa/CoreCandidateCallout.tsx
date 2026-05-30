"use client";

import Link from "next/link";
import { Star, ArrowRight } from "lucide-react";
import { ssaCoreCandidateSummary } from "@/lib/ssa-mock";

// Reusable rollup of the SSA verification + core-candidate workflow.
// Drop into CCEO / Country Program Lead dashboards to surface the queue
// without re-implementing the engine.
export function CoreCandidateCallout({
  variant,
}: {
  variant: "cpl" | "cceo";
}) {
  const s = ssaCoreCandidateSummary();
  const subtitle =
    variant === "cpl"
      ? "Supervise verification queue across teams"
      : "Verify SSAs flagged by the recommendation engine";
  return (
    <section className="card p-3.5">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-7 h-7 rounded-md grid place-items-center bg-emerald-100 text-emerald-700">
          <Star size={14} />
        </span>
        <div className="leading-tight">
          <h3 className="text-[13px] font-bold">Potential Core School Pipeline</h3>
          <div className="text-caption muted">{subtitle}</div>
        </div>
        <Link
          href="/ssa/core-candidates"
          className="ml-auto inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)]"
        >
          Open Queue
          <ArrowRight size={11} />
        </Link>
      </div>
      <div className="grid grid-cols-4 gap-3">
        <Tile label="Eligible Clients (SSA 7.5+)" value={s.eligibleClients} />
        <Tile label="Awaiting Verification" value={s.awaitingVerification} tone="amber" />
        <Tile label="Verified — Potential Core" value={s.flaggedPotential} tone="emerald" />
        <Tile label="October Onboarding Recommended" value={s.octoberRecommended} tone="violet" />
      </div>
      <div className="mt-2 pt-2 border-t border-[#eef2f4] text-caption muted">
        Engine rule: Client &amp; verified SSA average ≥ 7.5 across all 8 interventions. Onboarding queues for the next October FY.
      </div>
    </section>
  );
}

function Tile({
  label,
  value,
  tone = "edify",
}: {
  label: string;
  value: number;
  tone?: "edify" | "amber" | "emerald" | "violet";
}) {
  const cls =
    tone === "amber"   ? "text-amber-800" :
    tone === "emerald" ? "text-[#065f46]" :
    tone === "violet"  ? "text-violet-700" :
                         "text-[var(--color-edify-text)]";
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] p-2.5 overflow-hidden">
      <div className="text-[10px] muted font-semibold leading-tight line-clamp-2 min-h-[24px]">{label}</div>
      <div className={`text-[18px] font-extrabold tabular leading-none mt-1.5 truncate ${cls}`}>{value}</div>
    </div>
  );
}

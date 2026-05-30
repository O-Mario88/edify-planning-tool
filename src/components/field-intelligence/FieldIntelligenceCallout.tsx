"use client";

import Link from "next/link";
import { Brain, ArrowRight, AlertTriangle, Sparkles } from "lucide-react";
import { fieldIntelligenceSummaryFor } from "@/lib/field-intelligence-mock";
import type { CurrentUser } from "@/lib/schools-mock";

// Reusable rollup for CCEO / CPL / Director dashboards.
export function FieldIntelligenceCallout({
  user,
  variant,
}: {
  user: CurrentUser;
  variant: "cceo" | "cpl" | "cd";
}) {
  const s = fieldIntelligenceSummaryFor(user);
  const subtitle =
    variant === "cceo" ? "Capture today's field reality. Auto-rolls into your weekly summary." :
    variant === "cpl"  ? "Team daily debriefs roll up into your weekly Program Lead report." :
                         "Country execution reality from every staff debrief this week.";

  return (
    <section className="card p-3.5">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-7 h-7 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
          <Brain size={14} />
        </span>
        <div className="leading-tight">
          <h3 className="text-[13px] font-bold">Field Intelligence Engine</h3>
          <div className="text-caption muted">{subtitle}</div>
        </div>
        <Link
          href="/field-intelligence"
          className="ml-auto inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)]"
        >
          {variant === "cceo" ? "Submit today's debrief" : "Open weekly report"}
          <ArrowRight size={11} />
        </Link>
      </div>

      <div className="grid grid-cols-4 gap-3">
        <Tile label="Debriefs this week" value={s.debriefsThisWeek} />
        <Tile label="Raw achievement" value={`${s.raw}%`} />
        <Tile label="Context-adjusted" value={`${s.adjusted}%`} tone="emerald" />
        <Tile label="Decisions surfaced" value={s.decisionCount} tone="violet" />
      </div>

      {s.needsTodaysDebrief && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-2 flex items-center gap-2 text-[11.5px]">
          <AlertTriangle size={12} className="text-amber-700" />
          <span className="font-semibold text-amber-800">You haven&apos;t submitted today&apos;s debrief yet.</span>
          <Link href="/field-intelligence" className="ml-auto text-amber-800 font-bold underline">
            Submit now
          </Link>
        </div>
      )}

      {!s.needsTodaysDebrief && s.topBarrier && (
        <div className="mt-3 rounded-lg border border-[var(--color-edify-border)] bg-white px-2.5 py-2 flex items-center gap-2 text-[11.5px]">
          <Sparkles size={12} className="text-[var(--color-edify-primary)]" />
          <span className="muted">Top barrier this week:</span>
          <span className="font-semibold">{s.topBarrier}</span>
        </div>
      )}
    </section>
  );
}

function Tile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | string;
  tone?: "emerald" | "violet";
}) {
  const cls =
    tone === "emerald" ? "text-emerald-700" :
    tone === "violet"  ? "text-violet-700"  :
                         "text-[var(--color-edify-text)]";
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] p-2.5 overflow-hidden">
      <div className="text-[10px] muted font-semibold leading-tight line-clamp-2 min-h-[24px]">{label}</div>
      <div className={`text-[18px] font-extrabold tabular leading-none mt-1.5 truncate ${cls}`}>{value}</div>
    </div>
  );
}

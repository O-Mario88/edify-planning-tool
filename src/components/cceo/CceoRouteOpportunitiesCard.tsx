"use client";

import Link from "next/link";
import { ArrowUpRight, MapPin, Route } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import {
  cceoRouteOpportunities,
  type CceoRouteImpact,
} from "@/lib/cceo-mock";
import { cn } from "@/lib/utils";

const IMPACT_TONE: Record<CceoRouteImpact, string> = {
  "High Impact":   "bg-emerald-50 text-emerald-700 border-emerald-200",
  "Medium Impact": "bg-amber-50   text-amber-700   border-amber-200",
  "Low Impact":    "bg-slate-50   text-slate-600   border-slate-200",
};

export function CceoRouteOpportunitiesCard() {
  return (
    <SectionCard
      icon={<Route size={13} />}
      title="Monthly Route Opportunities"
      actions={
        <Link
          href="/route"
          className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] whitespace-nowrap"
        >
          View Map
          <ArrowUpRight size={11} />
        </Link>
      }
    >
      {/* Fixed-height scroll container — keeps the card aligned with
          peer cards in the same row even if the bundle list grows. */}
      <div className="rounded-xl border border-[var(--color-edify-border)] bg-white overflow-hidden">
        <div className="grid grid-cols-[2fr_60px_72px_110px_64px] gap-2 px-3 py-2 bg-gradient-to-r from-[var(--color-edify-soft)] to-[var(--color-edify-soft)]/40 text-[9.5px] uppercase tracking-wide text-slate-600 font-bold">
          <div>Bundle</div>
          <div>Weeks</div>
          <div className="text-right">Schools</div>
          <div>Impact</div>
          <div className="text-right">Open</div>
        </div>
        <div className="max-h-[224px] overflow-y-auto scrollbar divide-y divide-[var(--color-edify-divider)]">
          {cceoRouteOpportunities.map((b) => (
            <div
              key={b.key}
              className="grid grid-cols-[2fr_60px_72px_110px_64px] gap-2 px-3 py-2.5 items-center text-[11.5px]"
            >
              <div className="font-bold text-slate-900 leading-tight truncate inline-flex items-center gap-1.5">
                <MapPin size={11} className="text-[var(--color-edify-muted)]" />
                {b.label}
              </div>
              <div className="tabular muted">{b.weekRange}</div>
              <div className="text-right tabular font-semibold">{b.schools}</div>
              <div>
                <span className={cn("inline-block px-1.5 py-[2px] rounded-md text-[10px] font-extrabold border whitespace-nowrap", IMPACT_TONE[b.impact])}>
                  {b.impact}
                </span>
              </div>
              <div className="text-right tabular font-bold text-slate-700">{b.openCount} Open</div>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11px] muted">
        High-impact bundles cover the largest backlog. Tap a bundle to load it into your weekly route plan.
      </div>
    </SectionCard>
  );
}

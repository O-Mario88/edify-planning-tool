"use client";

import Link from "next/link";
import { Info, ArrowRight } from "lucide-react";

export function PlanningEngineActiveBar() {
  return (
    <section className="card p-3 flex items-start gap-3 bg-[var(--color-edify-soft)]/50">
      <span className="w-9 h-9 rounded-md grid place-items-center bg-white text-[var(--color-edify-primary)] border border-[var(--color-edify-border)] shrink-0">
        <Info size={16} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="text-[13px] font-bold leading-tight">Planning Engine Active</div>
        <div className="text-[11.5px] muted mt-0.5 leading-snug">
          Our planning engine automatically enforces leave, holidays, and blackout rules. You cannot save or schedule activities on blocked dates.
        </div>
      </div>
      <Link
        href="#planning-rules"
        className="inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)] shrink-0 mt-1"
      >
        Learn more about planning rules
        <ArrowRight size={12} />
      </Link>
    </section>
  );
}

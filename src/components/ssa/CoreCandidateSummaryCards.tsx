"use client";

import { Star, ShieldCheck, CheckCircle2, Calendar } from "lucide-react";
import { ssaCoreCandidateSummary } from "@/lib/ssa-mock";

export function CoreCandidateSummaryCards() {
  const s = ssaCoreCandidateSummary();
  const tiles = [
    { key: "elig",  label: "Eligible Client Schools",          value: s.eligibleClients,      icon: Star,         tone: "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]" },
    { key: "wait",  label: "Awaiting Verification",            value: s.awaitingVerification, icon: ShieldCheck,  tone: "bg-amber-100 text-amber-800" },
    { key: "core",  label: "Verified — Potential Core",        value: s.flaggedPotential,     icon: CheckCircle2, tone: "bg-[#d1fae5] text-[#065f46]" },
    { key: "oct",   label: "Recommended for October Onboarding", value: s.octoberRecommended, icon: Calendar,     tone: "bg-violet-100 text-violet-700" },
  ];
  return (
    <section className="grid grid-cols-4 gap-3">
      {tiles.map((t) => (
        <div key={t.key} className="card p-3 overflow-hidden">
          <div className="flex items-start gap-2.5">
            <span className={`w-10 h-10 rounded-full grid place-items-center shrink-0 ${t.tone}`}>
              <t.icon size={16} />
            </span>
            <div className="leading-tight min-w-0 flex-1">
              <div className="text-[11px] muted font-semibold leading-tight line-clamp-2 min-h-[28px]">
                {t.label}
              </div>
              <div className="text-[22px] font-extrabold tabular leading-none mt-1.5 truncate">
                {t.value}
              </div>
            </div>
          </div>
        </div>
      ))}
    </section>
  );
}

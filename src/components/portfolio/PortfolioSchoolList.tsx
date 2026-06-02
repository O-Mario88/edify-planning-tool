"use client";

// PortfolioSchoolList — a dense, collapsible list of owned schools.
//
// Each school is a compact one-line row by default (so many schools fit on the
// page at once); tap a row to expand its detail — full location, learners,
// partner-delegation control, and the Plan link. A header toggle expands or
// collapses everything. This is the "collapse the detail-heavy list" pattern —
// it keeps the page from growing unbounded as a portfolio scales.

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, Lock, CheckCircle2, Handshake, Building2 } from "lucide-react";
import { SchoolPartnerControl } from "@/components/portfolio/SchoolPartnerControl";
import { cn } from "@/lib/utils";

export type PortfolioSchoolRow = {
  schoolId: string;
  schoolName: string;
  schoolType: string;
  district: string;
  region: string;
  enrollment?: number;
  planningLocked: boolean;
  delegations: { id: string; partnerName: string; interventionArea?: string }[];
};

export function PortfolioSchoolList({
  schools,
  partnerOptions,
  interventionAreas,
}: {
  schools: PortfolioSchoolRow[];
  partnerOptions: string[];
  interventionAreas: string[];
}) {
  const [open, setOpen] = useState<Set<string>>(new Set());
  const allOpen = open.size === schools.length && schools.length > 0;

  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  const toggleAll = () => setOpen(allOpen ? new Set() : new Set(schools.map((s) => s.schoolId)));

  return (
    <section className="card p-0 overflow-hidden">
      <div className="flex items-center justify-between gap-2 px-3.5 py-2.5 border-b border-[var(--color-edify-divider)]">
        <h2 className="text-[12.5px] font-extrabold tracking-tight">Schools you own ({schools.length})</h2>
        <button
          type="button"
          onClick={toggleAll}
          className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline shrink-0"
        >
          {allOpen ? "Collapse all" : "Expand all"}
        </button>
      </div>

      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {schools.map((s) => {
          const isOpen = open.has(s.schoolId);
          return (
            <li key={s.schoolId}>
              {/* Compact row — the toggle. */}
              <button
                type="button"
                onClick={() => toggle(s.schoolId)}
                aria-expanded={isOpen}
                className="w-full flex items-center gap-2.5 px-3.5 py-2 text-left hover:bg-[var(--color-edify-soft)]/40 transition-colors"
              >
                <span className="h-7 w-7 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0 text-[9px] font-extrabold">
                  {s.schoolType.slice(0, 2).toUpperCase()}
                </span>
                <span className="flex-1 min-w-0">
                  <span className="block text-[13px] font-extrabold tracking-tight truncate">{s.schoolName}</span>
                  <span className="block text-caption muted truncate">{s.schoolId} · {s.district}</span>
                </span>
                {s.delegations.length > 0 && (
                  <span className="hidden sm:inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-sky-100 text-sky-700 whitespace-nowrap shrink-0">
                    <Handshake size={10} /> {s.delegations.length}
                  </span>
                )}
                {s.planningLocked ? (
                  <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-amber-100 text-amber-700 whitespace-nowrap shrink-0">
                    <Lock size={10} /> SSA pending
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-emerald-100 text-emerald-700 whitespace-nowrap shrink-0">
                    <CheckCircle2 size={10} /> Open
                  </span>
                )}
                <ChevronDown size={15} className={cn("text-[var(--color-edify-muted)] shrink-0 transition-transform", isOpen ? "rotate-180" : "")} />
              </button>

              {/* Expanded detail. */}
              {isOpen && (
                <div className="px-3.5 pb-3 pt-0.5 pl-[42px]">
                  <div className="text-caption muted">
                    <span className="inline-flex items-center gap-1"><Building2 size={11} /> {s.district}, {s.region}</span>
                    {" · "}{s.schoolType}
                    {s.enrollment != null ? ` · ${s.enrollment} learners` : ""}
                  </div>
                  <div className="mt-1.5">
                    <SchoolPartnerControl
                      schoolId={s.schoolId}
                      schoolName={s.schoolName}
                      delegations={s.delegations}
                      partnerOptions={partnerOptions}
                      interventionAreas={interventionAreas}
                    />
                  </div>
                  <Link href="/planning" className="mt-2 inline-flex text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline">
                    Plan this school →
                  </Link>
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

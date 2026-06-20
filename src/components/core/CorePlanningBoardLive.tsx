"use client";

import { useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronRight, School2, ArrowUpRight } from "lucide-react";
import type { BeCorePlanningBucket } from "@/lib/api/surfaces";

// Backend-driven Core School Planning board. Each of the 12 gap buckets from
// /planning/core is a collapsible section: collapsed shows the count; expanded
// shows the schools behind it with progress + the next required action. All data
// is live (no mock arrays) so the counts and lists always agree.

const URGENT = new Set(["missingSsa", "missingVisit1", "missingTraining1"]);
const POSITIVE = new Set(["ready", "fullPackage", "potentialChampion"]);

function countClass(key: string, count: number): string {
  const base = "text-[12px] font-bold tabular rounded-full px-2.5 py-0.5 shrink-0 ";
  if (count === 0) return base + "bg-[var(--color-edify-soft)] text-[var(--color-edify-muted)]";
  if (URGENT.has(key)) return base + "bg-rose-50 text-rose-700";
  if (POSITIVE.has(key)) return base + "bg-emerald-50 text-emerald-700";
  return base + "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)]";
}

export function CorePlanningBoardLive({ buckets }: { buckets: BeCorePlanningBucket[] }) {
  // Expand the first bucket that actually has schools, so the board opens useful.
  const firstWithSchools = buckets.find((b) => b.count > 0)?.key;
  const [open, setOpen] = useState<Set<string>>(() => new Set(firstWithSchools ? [firstWithSchools] : []));

  function toggle(key: string) {
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="space-y-2">
      {buckets.map((b) => {
        const isOpen = open.has(b.key);
        return (
          <section key={b.key} className="rounded-xl border border-[var(--color-edify-border)] bg-white overflow-hidden">
            <button
              type="button"
              onClick={() => b.count > 0 && toggle(b.key)}
              disabled={b.count === 0}
              aria-expanded={isOpen}
              className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left enabled:hover:bg-[var(--color-edify-soft)]/40 disabled:opacity-70"
            >
              <span className="flex items-center gap-2 min-w-0">
                {b.count > 0 ? (
                  isOpen ? <ChevronDown size={15} className="shrink-0" /> : <ChevronRight size={15} className="shrink-0" />
                ) : (
                  <span className="w-[15px] shrink-0" />
                )}
                <span className="font-bold text-[13.5px] truncate">{b.label}</span>
              </span>
              <span className={countClass(b.key, b.count)}>{b.count}</span>
            </button>

            {isOpen && b.count > 0 && (
              <ul className="border-t border-[var(--color-edify-border)] divide-y divide-[var(--color-edify-border)]">
                {b.schools.map((s) => (
                  <li key={s.schoolId} className="px-4 py-2.5 flex items-center justify-between gap-3 flex-wrap">
                    <div className="min-w-0">
                      <div className="font-semibold text-[13px] flex items-center gap-1.5 min-w-0">
                        <School2 size={12} className="text-[var(--color-edify-muted)] shrink-0" />
                        <span className="truncate">{s.name}</span>
                        <span className="text-[11px] muted font-normal shrink-0">#{s.schoolId}</span>
                      </div>
                      <div className="text-[11px] muted mt-0.5 flex items-center gap-1.5 flex-wrap">
                        {s.subCounty && <span>{s.subCounty}</span>}
                        <span>· {s.cluster ?? "unclustered"}</span>
                        {s.owner && <span>· {s.owner}</span>}
                        {s.latestSsa != null && <span>· SSA {s.latestSsa}</span>}
                        <span>· visits {s.visitProgress ?? "0/4"}</span>
                        <span>· trainings {s.trainingProgress ?? "0/4"}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2.5 shrink-0">
                      {s.nextAction && (
                        <span className="text-[11px] font-semibold text-[var(--color-edify-primary)] hidden sm:inline">{s.nextAction}</span>
                      )}
                      <Link
                        href={`/schools/${encodeURIComponent(s.schoolId)}`}
                        className="inline-flex items-center gap-1 text-[11.5px] font-semibold rounded-lg border border-[var(--color-edify-border)] px-2.5 py-1 hover:bg-[var(--color-edify-soft)]/60"
                      >
                        View <ArrowUpRight size={11} />
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}
    </div>
  );
}

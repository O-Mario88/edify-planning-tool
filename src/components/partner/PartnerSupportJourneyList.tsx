"use client";

// PartnerSupportJourneyList — compact list of every assigned school
// with a one-line journey-stage indicator. Acts as the index for the
// detailed SchoolPartnerJourney views below.

import { useState } from "react";
import Link from "next/link";
import { Building2, ArrowRight } from "lucide-react";
import { cn } from "@/lib/utils";

type Stage =
  | "Need identified"
  | "Partner assigned"
  | "Scheduled"
  | "Delivered"
  | "Evidence uploaded"
  | "CCEO confirmed"
  | "M&E verified"
  | "Improvement detected";

type JourneyRow = {
  schoolId: string;
  name: string;
  district: string;
  ssaScore: number;
  ssaArea: string;
  stage: Stage;
  lastUpdate: string;
  nextDue?: string;
};

const ROWS: JourneyRow[] = [
  { schoolId: "SCH-HOPE",   name: "Hope Primary School",     district: "Mukono",  ssaScore: 4.2, ssaArea: "Teaching & Learning", stage: "CCEO confirmed",      lastUpdate: "May 13, 2026", nextDue: "PL approval" },
  { schoolId: "SCH-GRACE",  name: "Grace Primary School",    district: "Mukono",  ssaScore: 5.8, ssaArea: "Numeracy",            stage: "Evidence uploaded",   lastUpdate: "May 12, 2026", nextDue: "CCEO confirmation" },
  { schoolId: "SCH-KIREKA", name: "Kireka Primary School",   district: "Mukono",  ssaScore: 6.4, ssaArea: "Leadership",          stage: "Delivered",           lastUpdate: "May 10, 2026", nextDue: "Evidence upload" },
  { schoolId: "SCH-STMARY", name: "St. Mary's Primary",      district: "Kayunga", ssaScore: 5.1, ssaArea: "Leadership",          stage: "Scheduled",           lastUpdate: "May 09, 2026", nextDue: "May 17 delivery" },
  { schoolId: "SCH-NAMI",   name: "Namilyango Primary",      district: "Mukono",  ssaScore: 7.1, ssaArea: "Resources",           stage: "M&E verified",        lastUpdate: "May 06, 2026", nextDue: "Reassess in 60d" },
  { schoolId: "SCH-EAST",   name: "Eastview Junior",         district: "Mukono",  ssaScore: 7.4, ssaArea: "Leadership",          stage: "Improvement detected",lastUpdate: "May 02, 2026", nextDue: "Maintain quarterly" },
  { schoolId: "SCH-MAPLE",  name: "Maple Grove Primary",     district: "Kayunga", ssaScore: 3.6, ssaArea: "Teaching & Learning", stage: "Partner assigned",    lastUpdate: "Apr 22, 2026", nextDue: "Schedule visit" },
  { schoolId: "SCH-GAL",    name: "Galiraaya Primary",       district: "Kayunga", ssaScore: 3.2, ssaArea: "Critical · multiple", stage: "Need identified",     lastUpdate: "Apr 06, 2026", nextDue: "Awaiting assignment" },
];

const STAGE_INDEX: Record<Stage, number> = {
  "Need identified":      0,
  "Partner assigned":     1,
  "Scheduled":            2,
  "Delivered":            3,
  "Evidence uploaded":    4,
  "CCEO confirmed":       5,
  "M&E verified":         6,
  "Improvement detected": 7,
};

const STAGE_TONE: Record<Stage, string> = {
  "Need identified":      "bg-rose-50 text-rose-700",
  "Partner assigned":     "bg-slate-100 text-slate-700",
  "Scheduled":            "bg-blue-50 text-blue-700",
  "Delivered":            "bg-blue-50 text-blue-700",
  "Evidence uploaded":    "bg-amber-50 text-amber-700",
  "CCEO confirmed":       "bg-emerald-50 text-emerald-700",
  "M&E verified":         "bg-emerald-50 text-emerald-700",
  "Improvement detected": "bg-emerald-100 text-emerald-800",
};

export function PartnerSupportJourneyList() {
  const [stageFilter, setStageFilter] = useState<"all" | Stage>("all");
  const rows = stageFilter === "all" ? ROWS : ROWS.filter((r) => r.stage === stageFilter);

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div>
          <h3 className="text-[15px] font-extrabold tracking-tight">All schools — journey index</h3>
          <p className="text-[12px] muted mt-1">
            Every school you support, with where its journey currently stands. Click any row to open the full timeline.
          </p>
        </div>
      </header>

      {/* Stage filter chips */}
      <div className="flex items-center gap-1 flex-wrap mb-3 overflow-x-auto scrollbar pb-1">
        <FilterChip active={stageFilter === "all"} count={ROWS.length} onClick={() => setStageFilter("all")} label="All stages" />
        {(Object.keys(STAGE_INDEX) as Stage[]).map((s) => (
          <FilterChip
            key={s}
            active={stageFilter === s}
            count={ROWS.filter((r) => r.stage === s).length}
            onClick={() => setStageFilter(s)}
            label={s}
          />
        ))}
      </div>

      <ul className="divide-y divide-[var(--color-edify-divider)]">
        {rows.map((r) => <Row key={r.schoolId} row={r} />)}
      </ul>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[12px] muted">
        Showing <span className="font-semibold text-[var(--color-edify-text)]">{rows.length}</span>{" "}
        of <span className="font-semibold text-[var(--color-edify-text)]">{ROWS.length}</span> active journeys
      </div>
    </section>
  );
}

function Row({ row: r }: { row: JourneyRow }) {
  const stageIdx = STAGE_INDEX[r.stage];
  return (
    <li className="py-2.5 flex items-center gap-3">
      <span className="grid place-items-center h-9 w-9 rounded-lg bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
        <Building2 size={14} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-body font-extrabold tracking-tight truncate">{r.name}</span>
          <span className="text-caption muted">·</span>
          <span className="text-caption muted">{r.district}</span>
          <span className="text-caption muted">·</span>
          <span className="text-caption muted">SSA {r.ssaScore.toFixed(1)} ({r.ssaArea})</span>
        </div>
        {/* Mini progress strip */}
        <div className="mt-1.5 flex items-center gap-0.5">
          {Array.from({ length: 8 }).map((_, i) => (
            <span
              key={i}
              className={cn(
                "h-1.5 flex-1 rounded-full",
                i <= stageIdx ? "bg-emerald-500" : "bg-[var(--color-edify-soft)]",
              )}
            />
          ))}
        </div>
        <div className="flex items-center justify-between gap-3 mt-1.5">
          <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide whitespace-nowrap", STAGE_TONE[r.stage])}>
            {r.stage}
          </span>
          <span className="text-caption muted">
            {r.nextDue ? <>Next: <span className="font-semibold text-[var(--color-edify-text)]">{r.nextDue}</span></> : null}
          </span>
        </div>
      </div>
      <Link
        href={`/schools/sch-1`}
        className="inline-flex items-center gap-1 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60 whitespace-nowrap shrink-0"
      >
        Open <ArrowRight size={11} />
      </Link>
    </li>
  );
}

function FilterChip({
  active, count, onClick, label,
}: {
  active: boolean;
  count: number;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold transition-colors whitespace-nowrap",
        active
          ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
          : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
      )}
    >
      {label}
      <span className={cn(
        "inline-flex items-center justify-center min-w-[16px] h-[14px] px-1 rounded-md text-[9px] font-extrabold",
        active ? "bg-[var(--color-edify-primary)] text-white" : "bg-slate-100 text-slate-700",
      )}>
        {count}
      </span>
    </button>
  );
}

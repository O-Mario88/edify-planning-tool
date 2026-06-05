"use client";

// Filtered result list for the Core School page.
//
// Renders the list of school records that match the currently-active
// tile filter, with role-appropriate fields and a primary action per
// row. Shape matches the entityType "school" — visit / training rows
// are still anchored to the school they belong to.

import Link from "next/link";
import {
  AlertOctagon,
  ArrowUpRight,
  Calendar,
  CheckCircle2,
  Footprints,
  GraduationCap,
  MapPin,
  UserCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import type { CoreSchoolResultRow } from "./tile-filters";

const TONE_TEXT: Record<CoreSchoolResultRow["riskTone"], string> = {
  rose:    "text-rose-700",
  amber:   "text-amber-700",
  violet:  "text-violet-700",
  emerald: "text-emerald-700",
};

const TONE_BG: Record<CoreSchoolResultRow["riskTone"], string> = {
  rose:    "bg-rose-50",
  amber:   "bg-amber-50",
  violet:  "bg-violet-50",
  emerald: "bg-emerald-50",
};

const EVIDENCE_TONE: Record<CoreSchoolResultRow["evidenceStatus"], string> = {
  Submitted: "pill-info",
  Missing:   "pill-danger",
  Verified:  "pill-success",
  "—":       "pill-neutral",
};

export function CoreSchoolFilteredResultList({
  rows,
}: {
  rows: CoreSchoolResultRow[];
}) {
  return (
    <article className="card p-3.5 lg:p-5">
      <header className="flex items-baseline justify-between gap-3 mb-3">
        <h3 className="text-[14px] font-extrabold tracking-tight">
          Matching Core Schools
        </h3>
        <span className="text-[11px] muted font-semibold">
          Showing {rows.length} {rows.length === 1 ? "school" : "schools"}
        </span>
      </header>

      <ul className="flex flex-col gap-2">
        {rows.map((r) => (
          <li
            key={r.id}
            className={cn(
              "rounded-xl border border-[var(--color-edify-border)] bg-white",
              "px-3.5 py-3 flex flex-col gap-2.5 sm:flex-row sm:items-start sm:gap-4",
            )}
          >
            <div className="min-w-0 flex-1">
              <div className="text-[13.5px] font-extrabold tracking-tight text-slate-900 truncate">
                {r.schoolName}
              </div>
              <div className="text-[11.5px] muted leading-tight mt-0.5 flex items-center flex-wrap gap-x-2 gap-y-0.5">
                <span className="inline-flex items-center gap-1">
                  <MapPin size={10} /> {r.district}
                </span>
                <span className="text-slate-300">·</span>
                <span className="inline-flex items-center gap-1">
                  <UserCircle size={10} /> {r.cceo}
                </span>
              </div>

              <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-x-3 gap-y-1.5">
                <Fact
                  icon={<Footprints size={10} />}
                  label="Visits"
                  value={r.visits}
                />
                <Fact
                  icon={<GraduationCap size={10} />}
                  label="Trainings"
                  value={r.trainings}
                />
                <Fact
                  icon={<CheckCircle2 size={10} />}
                  label="Package"
                  value={r.packageStatus}
                />
                <Fact
                  icon={<AlertOctagon size={10} />}
                  label="Status"
                  value={r.status}
                />
              </div>

              <div className="mt-2 rounded-lg bg-amber-50 border border-amber-100 px-2.5 py-1.5 flex items-start gap-2">
                <Calendar size={11} className="text-amber-600 shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <div className="text-[9.5px] muted font-semibold uppercase tracking-wide">
                    Next action
                  </div>
                  <div className="text-[12px] font-semibold text-slate-800 leading-snug mt-0.5">
                    {r.nextAction}
                  </div>
                </div>
              </div>
            </div>

            <div className="flex sm:flex-col items-center sm:items-end gap-2 shrink-0">
              <div className={cn(
                "rounded-lg px-2.5 py-1.5 text-center min-w-[68px]",
                TONE_BG[r.riskTone],
              )}>
                <div className={cn(
                  "text-[15px] font-extrabold tabular leading-none",
                  TONE_TEXT[r.riskTone],
                )}>
                  {r.ssaScore.toFixed(1)}
                </div>
                <div className="text-[9px] muted font-bold uppercase tracking-wide mt-0.5">
                  SSA
                </div>
              </div>
              <span className={cn("premium-badge", EVIDENCE_TONE[r.evidenceStatus])}>
                {r.evidenceStatus}
              </span>
              <Link
                href={`/schools?name=${encodeURIComponent(r.schoolName)}`}
                className="tile-filter-btn-secondary inline-flex items-center gap-1 h-8 px-2.5 rounded-lg text-[11.5px] font-semibold whitespace-nowrap"
              >
                Open
                <ArrowUpRight size={10} />
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </article>
  );
}

function Fact({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-[9px] muted font-semibold uppercase tracking-wide flex items-center gap-0.5">
        {icon}
        {label}
      </dt>
      <dd className="text-[12px] font-extrabold tracking-tight mt-0.5 truncate">
        {value}
      </dd>
    </div>
  );
}

"use client";

// Mobile / tablet view for the Monthly Fund Request.
//
// On phones we deliberately don't try to squeeze the 26-column matrix
// into the viewport. Instead we group the request by team, list each
// staff/partner as a card, and surface the weekly meal breakdown +
// transport + total inside each card. Numeric values stay clickable
// for the same drilldown drawer.

import {
  Calendar,
  GraduationCap,
  School,
  Users,
} from "lucide-react";
import type {
  MfrLine,
  MonthlyFundRequest,
} from "@/lib/funds/monthly-fund-request-types";
import type { MfrCellTarget } from "./MonthlyFundRequestMatrix";
import { cn } from "@/lib/utils";

export function MobileMonthlyFundRequest({
  mfr,
  onCellClick,
}: {
  mfr: MonthlyFundRequest;
  onCellClick?: (t: MfrCellTarget) => void;
}) {
  // Group lines by team, mirror the matrix order
  const TEAM_ORDER = [
    "Team East", "Team North", "Team West", "Team Central",
    "Partners", "Special Projects",
  ];
  const groups = TEAM_ORDER
    .map((t) => ({
      team: t,
      lines: mfr.lines.filter((l) => {
        if (t === "Partners")         return l.kind === "partner";
        if (t === "Special Projects") return l.kind === "special_project";
        return l.team === t && l.kind === "staff";
      }),
    }))
    .filter((g) => g.lines.length > 0);

  return (
    <div className="flex flex-col gap-3">
      {groups.map((g) => (
        <section key={g.team} className="card p-3">
          <header className="flex items-center justify-between gap-2 mb-2 pb-2 border-b border-dashed border-[var(--color-edify-border)]">
            <h3 className="text-[12.5px] font-extrabold tracking-tight">{g.team}</h3>
            <span className="text-[10px] muted font-semibold">{g.lines.length} {g.lines.length === 1 ? "row" : "rows"}</span>
          </header>
          <ul className="flex flex-col gap-2">
            {g.lines.map((line) => (
              <LineCard key={line.id} line={line} onCellClick={onCellClick} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function LineCard({
  line,
  onCellClick,
}: {
  line: MfrLine;
  onCellClick?: (t: MfrCellTarget) => void;
}) {
  const cellClick = (category: Parameters<NonNullable<typeof onCellClick>>[0]["category"], week?: 1 | 2 | 3 | 4 | 5) =>
    onCellClick ? () => onCellClick({ lineId: line.id, category, week }) : undefined;
  return (
    <li className="rounded-xl border border-[var(--color-edify-border)] bg-white px-3 py-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[13px] font-extrabold tracking-tight text-slate-900 truncate">
            {line.staffName ?? line.partnerName ?? "—"}
          </div>
          <div className="text-[10.5px] muted leading-tight mt-0.5">
            {line.staffRole ? `${line.staffRole} · ${line.region}` : line.region}
          </div>
          <p className="text-[10.5px] muted leading-snug mt-1 line-clamp-2">{line.particulars}</p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[14px] font-extrabold tabular num-hero text-slate-900 leading-none">
            {(line.totalMonthlyAllocation / 1_000_000).toFixed(2)}M
          </div>
          <div className="text-[9.5px] muted font-semibold mt-0.5">monthly</div>
        </div>
      </div>

      {/* Category quick facts */}
      <div className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-1.5">
        <Fact
          icon={<School size={11} />}
          label="Staff visits"
          value={line.staffVisits.total}
          onClick={cellClick("StaffVisits")}
          tone="slate"
        />
        <Fact
          icon={<Users size={11} />}
          label="Partner visits"
          value={line.partnerVisits.total}
          onClick={cellClick("PartnerVisits")}
          tone="blue"
        />
        <Fact
          icon={<Calendar size={11} />}
          label="SSA"
          value={line.ssa.total}
          onClick={cellClick("SSA")}
          tone="amber"
        />
        <Fact
          icon={<GraduationCap size={11} />}
          label="Trainings"
          value={line.clusterTraining.total + line.groupTrainings.total}
          onClick={cellClick("ClusterTraining")}
          tone="violet"
        />
      </div>

      {/* Weekly meal strip */}
      {line.mealsTotal > 0 && (
        <div className="mt-2 rounded-lg bg-emerald-50/60 border border-emerald-200/60 px-2 py-1.5">
          <div className="flex items-center justify-between mb-1">
            <span className="text-[10px] font-extrabold uppercase tracking-wide text-emerald-700">Meals by week</span>
            <span className="text-[10.5px] font-extrabold tabular text-emerald-700">
              {line.mealsTotal.toLocaleString()}
            </span>
          </div>
          <div className="grid grid-cols-5 gap-1">
            {([1, 2, 3, 4, 5] as const).map((w) => {
              const amt = line.mealsByWeek[`w${w}` as `w${1 | 2 | 3 | 4 | 5}`];
              return (
                <button
                  key={w}
                  type="button"
                  onClick={amt > 0 ? cellClick("Meals", w) : undefined}
                  disabled={amt === 0}
                  className={cn(
                    "px-1.5 py-1 rounded-md text-[10px] font-bold tabular text-center",
                    amt > 0
                      ? "bg-white text-slate-800 hover:bg-emerald-100 cursor-pointer"
                      : "bg-transparent text-slate-300 cursor-default",
                  )}
                >
                  <div className="text-[8.5px] muted font-semibold">W{w}</div>
                  <div>{amt > 0 ? (amt / 1000).toFixed(0) + "k" : "—"}</div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Transport strip */}
      {line.transportAllocation > 0 && (
        <button
          type="button"
          onClick={cellClick("Transport")}
          className="mt-2 w-full rounded-lg bg-orange-50 border border-orange-200/70 px-2.5 py-1.5 flex items-center justify-between hover:bg-orange-100/60"
        >
          <span className="text-[10.5px] font-extrabold text-orange-700">Transport allocation</span>
          <span className="text-[11.5px] font-extrabold tabular text-orange-800">
            {line.transportAllocation.toLocaleString()}
          </span>
        </button>
      )}
    </li>
  );
}

function Fact({
  icon,
  label,
  value,
  onClick,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  onClick?: () => void;
  tone: "slate" | "blue" | "amber" | "violet";
}) {
  const TONE: Record<typeof tone, string> = {
    slate:  "bg-slate-50  text-slate-700  border-slate-200",
    blue:   "bg-sky-50    text-sky-700    border-sky-200",
    amber:  "bg-amber-50  text-amber-700  border-amber-200",
    violet: "bg-violet-50 text-violet-700 border-violet-200",
  };
  const disabled = value === 0;
  return (
    <button
      type="button"
      onClick={!disabled ? onClick : undefined}
      disabled={disabled}
      className={cn(
        "rounded-lg border px-2 py-1.5 text-left transition-colors",
        TONE[tone],
        disabled && "opacity-50 cursor-default",
        !disabled && onClick && "hover:brightness-95 cursor-pointer",
      )}
    >
      <div className="text-[9px] font-extrabold uppercase tracking-wide inline-flex items-center gap-1">
        {icon} {label}
      </div>
      <div className="text-[12px] font-extrabold tabular mt-0.5">
        {value > 0 ? value.toLocaleString() : "—"}
      </div>
    </button>
  );
}

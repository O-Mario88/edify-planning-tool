"use client";

// Monthly Fund Request — staff / team filter bar.
//
// Sits above the weekly totals strip. Three controls:
//
//   1. Team quick-picks — one chip per team (East / North / West /
//      Central / Partners / Special Projects). Tapping a chip
//      toggles the entire team in / out of the selection.
//   2. Staff dropdown — searchable multi-select with checkboxes. The
//      list mirrors the active lines in alphabetical order.
//   3. Selection summary — chips listing each selected staff/partner.
//      Each chip has a small "×" to remove just that selection.
//
// When the selection is non-empty, every downstream view (weekly
// strip, Activity × Week summary, detail matrix, mobile cards) re-
// renders against the filtered line set so the cash-flow story
// instantly answers "for this slice of the team, what does this
// month look like?".

import { useMemo, useRef, useState } from "react";
import { Filter, Search, Users, X } from "lucide-react";
import type {
  MfrLine,
  MonthlyFundRequest,
} from "@/lib/funds/monthly-fund-request-types";
import { cn } from "@/lib/utils";

export function MfrStaffFilter({
  mfr,
  selectedIds,
  onChange,
}: {
  mfr: MonthlyFundRequest;
  selectedIds: string[];
  onChange: (ids: string[]) => void;
}) {
  const [search, setSearch] = useState("");
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerRef = useRef<HTMLDivElement>(null);

  // Group lines for the team quick-picks
  const teams = useMemo(() => {
    const TEAM_ORDER = [
      "Team East", "Team North", "Team West", "Team Central",
      "Partners", "Special Projects",
    ];
    return TEAM_ORDER
      .map((t) => ({
        team: t,
        lines: mfr.lines.filter((l) => bucketTeam(l) === t),
      }))
      .filter((g) => g.lines.length > 0);
  }, [mfr.lines]);

  // Searchable, sorted line list
  const searchableLines = useMemo(() => {
    const lower = search.trim().toLowerCase();
    return mfr.lines
      .filter((l) => {
        if (!lower) return true;
        const name = (l.staffName ?? l.partnerName ?? "").toLowerCase();
        const team = (l.team ?? "").toLowerCase();
        const region = (l.region ?? "").toLowerCase();
        return name.includes(lower) || team.includes(lower) || region.includes(lower);
      })
      .sort((a, b) => (a.staffName ?? a.partnerName ?? "").localeCompare(b.staffName ?? b.partnerName ?? ""));
  }, [mfr.lines, search]);

  const selectedSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const teamSelectionState = (lines: MfrLine[]): "none" | "some" | "all" => {
    const ids = lines.map((l) => l.id);
    const hit = ids.filter((id) => selectedSet.has(id)).length;
    if (hit === 0) return "none";
    if (hit === ids.length) return "all";
    return "some";
  };

  const toggleStaff = (id: string) => {
    if (selectedSet.has(id)) {
      onChange(selectedIds.filter((x) => x !== id));
    } else {
      onChange([...selectedIds, id]);
    }
  };
  const toggleTeam = (lines: MfrLine[]) => {
    const ids = lines.map((l) => l.id);
    const state = teamSelectionState(lines);
    if (state === "all") {
      // Remove every team member from the selection
      onChange(selectedIds.filter((x) => !ids.includes(x)));
    } else {
      // Add every team member (dedup)
      const next = new Set(selectedIds);
      for (const id of ids) next.add(id);
      onChange(Array.from(next));
    }
  };
  const clearAll = () => {
    onChange([]);
    setSearch("");
  };

  const selectedLines = selectedIds
    .map((id) => mfr.lines.find((l) => l.id === id))
    .filter((l): l is MfrLine => l != null);

  const totalLines = mfr.lines.length;
  const active = selectedIds.length > 0;

  return (
    <section
      className={cn(
        "card p-3 lg:p-3.5 flex flex-col gap-2.5",
        active && "ring-1 ring-emerald-200/70",
      )}
    >
      {/* Top row — team quick-picks + dropdown trigger + clear */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10.5px] font-extrabold uppercase tracking-wide inline-flex items-center gap-1 muted shrink-0">
          <Filter size={11} className="text-emerald-600" />
          Filter
        </span>

        <div className="flex items-center gap-1.5 flex-wrap">
          {teams.map((g) => {
            const state = teamSelectionState(g.lines);
            return (
              <button
                key={g.team}
                type="button"
                onClick={() => toggleTeam(g.lines)}
                aria-pressed={state === "all"}
                className={cn(
                  "mfr-team-chip inline-flex items-center gap-1.5 h-7 px-2.5 rounded-full text-[11px] font-extrabold border transition-colors",
                  state === "all"  && "bg-slate-900 text-white border-slate-900",
                  state === "some" && "bg-emerald-50 text-emerald-700 border-emerald-200",
                  state === "none" && "bg-white text-slate-700 border-[var(--color-edify-border)] hover:bg-slate-50",
                )}
                title={state === "all" ? `Remove ${g.team}` : `Add ${g.team}`}
              >
                {g.team}
                <span className={cn(
                  "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded text-[9.5px] tabular",
                  state === "all"  && "bg-white/15 text-white",
                  state === "some" && "bg-emerald-200/60 text-emerald-700",
                  state === "none" && "bg-slate-100 text-slate-600",
                )}>
                  {g.lines.length}
                </span>
              </button>
            );
          })}
        </div>

        <div className="flex items-center gap-2 ml-auto">
          <div className="relative" ref={pickerRef}>
            <button
              type="button"
              onClick={() => setPickerOpen((v) => !v)}
              aria-expanded={pickerOpen}
              className="inline-flex items-center gap-1.5 h-8 px-3 rounded-lg bg-white border border-[var(--color-edify-border)] text-[11.5px] font-extrabold text-slate-700 hover:bg-slate-50"
            >
              <Users size={11} className="text-slate-500" />
              Pick staff
              {selectedIds.length > 0 && (
                <span className="inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded bg-emerald-100 text-emerald-700 text-[9.5px] tabular">
                  {selectedIds.length}
                </span>
              )}
            </button>

            {pickerOpen && (
              <div className="absolute right-0 mt-1.5 w-[320px] z-30 rounded-xl border border-[var(--color-edify-border)] bg-white shadow-[0_18px_44px_-16px_rgba(15,23,32,0.45)] overflow-hidden">
                <div className="p-2 border-b border-[var(--color-edify-border)]">
                  <div className="relative">
                    <Search size={11} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                    <input
                      autoFocus
                      type="text"
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search staff, partner, team…"
                      className="w-full h-8 pl-7 pr-2 rounded-md border border-[var(--color-edify-border)] bg-white text-[12px] outline-none focus:ring-2 focus:ring-emerald-300"
                    />
                  </div>
                </div>
                <ul className="max-h-[280px] overflow-y-auto py-1">
                  {searchableLines.length === 0 && (
                    <li className="px-3 py-4 text-center text-[12px] muted italic">No staff match.</li>
                  )}
                  {searchableLines.map((line) => {
                    const checked = selectedSet.has(line.id);
                    const label = line.staffName ?? line.partnerName ?? "—";
                    return (
                      <li key={line.id}>
                        <label className="flex items-center gap-2 px-3 py-1.5 cursor-pointer hover:bg-slate-50">
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleStaff(line.id)}
                            className="accent-emerald-600"
                          />
                          <span className="min-w-0 flex-1">
                            <span className="block text-[12px] font-extrabold text-slate-900 truncate">{label}</span>
                            <span className="block text-[10px] muted leading-tight">
                              {line.team} · {line.region}
                            </span>
                          </span>
                          <span className="text-[10px] muted tabular shrink-0">
                            UGX {(line.totalMonthlyAllocation / 1_000_000).toFixed(1)}M
                          </span>
                        </label>
                      </li>
                    );
                  })}
                </ul>
                <div className="border-t border-[var(--color-edify-border)] p-1.5 flex items-center justify-between gap-2">
                  <button
                    type="button"
                    onClick={() => onChange(searchableLines.map((l) => l.id))}
                    className="text-[11px] font-semibold text-slate-600 hover:text-emerald-700"
                  >
                    Select shown
                  </button>
                  <button
                    type="button"
                    onClick={() => setPickerOpen(false)}
                    className="text-[11px] font-extrabold text-slate-700 px-2 py-1 rounded-md hover:bg-slate-50"
                  >
                    Done
                  </button>
                </div>
              </div>
            )}
          </div>

          {active && (
            <button
              type="button"
              onClick={clearAll}
              className="inline-flex items-center gap-1 h-8 px-2.5 rounded-lg border border-rose-200 bg-rose-50 hover:bg-rose-100 text-rose-700 text-[11.5px] font-extrabold"
            >
              <X size={11} />
              Clear
            </button>
          )}
        </div>
      </div>

      {/* Selection summary */}
      <div className="flex items-center gap-2 flex-wrap text-[11px] muted">
        {active ? (
          <>
            <span className="font-extrabold text-slate-700">
              Showing {selectedIds.length} of {totalLines} {totalLines === 1 ? "line" : "lines"}
            </span>
            <span>·</span>
            <div className="flex items-center gap-1 flex-wrap">
              {selectedLines.slice(0, 6).map((line) => {
                const label = line.staffName ?? line.partnerName ?? "—";
                return (
                  <span
                    key={line.id}
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-700"
                  >
                    {label}
                    <button
                      type="button"
                      onClick={() => toggleStaff(line.id)}
                      aria-label={`Remove ${label}`}
                      className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full hover:bg-emerald-100"
                    >
                      <X size={9} />
                    </button>
                  </span>
                );
              })}
              {selectedLines.length > 6 && (
                <span className="px-1.5 py-0.5 rounded-md bg-slate-100 text-slate-700 font-semibold">
                  +{selectedLines.length - 6} more
                </span>
              )}
            </div>
          </>
        ) : (
          <span>Showing all {totalLines} staff/partner/special-project lines</span>
        )}
      </div>
    </section>
  );
}

function bucketTeam(line: MfrLine): string {
  if (line.kind === "partner")         return "Partners";
  if (line.kind === "special_project") return "Special Projects";
  return line.team;
}

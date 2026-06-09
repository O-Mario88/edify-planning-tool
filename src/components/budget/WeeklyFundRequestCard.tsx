"use client";

// Weekly fund request — the operational money view for CCEO/PL. "This is what
// you need, based on your approved schedule." Each line is a scheduled activity
// auto-costed from the CD rate card; the user never adds it up by hand.

import { useEffect, useState } from "react";
import { Receipt, AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeBudgetWeekly, BeBudgetWeeklyLine } from "@/lib/api/surfaces";

type Data = Omit<BeBudgetWeekly, "live">;

const ugx = (n: number) =>
  n >= 1_000_000 ? `UGX ${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `UGX ${Math.round(n / 1_000)}K` : `UGX ${Math.round(n)}`;
const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const titleCase = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export function WeeklyFundRequestCard() {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [openWeek, setOpenWeek] = useState<string | null>(null);

  const load = () => {
    setLoading(true); setError(null);
    fetch("/api/budget/weekly", { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setData(j as Data); else setError(j.error || "Could not load the fund request"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const linesByWeek = (key: string): BeBudgetWeeklyLine[] =>
    (data?.lines ?? []).filter((l) => `${l.month ?? 0}-${l.week ?? 0}` === key);

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Receipt size={14} /> Weekly fund request</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · from schedule</span>
      </header>

      {loading ? (
        <LoadingState compact />
      ) : error ? (
        <ErrorState compact message={error} onRetry={load} />
      ) : !data || data.count === 0 ? (
        <EmptyState compact title="Nothing scheduled to fund" message="Schedule activities and the fund request appears automatically — already costed." />
      ) : (
        <>
          <div className="flex items-end justify-between gap-3 mb-3">
            <div>
              <div className="text-[24px] font-extrabold tabular leading-none">{ugx(data.total)}</div>
              <div className="text-[11px] muted mt-1">{data.count} activities across {data.weeks.length} week(s)</div>
            </div>
            {data.costMissingCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-lg border border-rose-200 bg-rose-50 text-rose-700 px-2 py-1 text-[10.5px] font-bold">
                <AlertTriangle size={12} /> {data.costMissingCount} blocked
              </span>
            )}
          </div>

          <div className="space-y-1">
            {data.weeks.map((w) => {
              const key = w.key;
              const open = openWeek === key;
              return (
                <div key={key} className="rounded-lg border border-[var(--color-edify-divider)] overflow-hidden">
                  <button onClick={() => setOpenWeek(open ? null : key)} className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 hover:bg-[var(--surface-3)] text-left">
                    <span className="inline-flex items-center gap-1.5 text-[11.5px] font-bold">
                      {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                      {w.month ? MONTHS[w.month] : "Unscheduled"}{w.week ? ` · Week ${w.week}` : ""}
                      <span className="muted font-normal">· {w.count} activities</span>
                    </span>
                    <span className="font-extrabold tabular text-[12px]">{ugx(w.amount)}</span>
                  </button>
                  {open && (
                    <ul className="divide-y divide-[var(--color-edify-divider)] border-t border-[var(--color-edify-divider)]">
                      {linesByWeek(key).map((l) => (
                        <li key={l.id} className="px-2.5 py-1.5 flex items-center justify-between gap-2 text-[11px]">
                          <span className="min-w-0">
                            <span className="font-semibold">{titleCase(l.activityType)}</span>
                            <span className={cn("ml-1.5 px-1 py-px rounded text-[8.5px] font-bold uppercase", l.deliveryType === "partner" ? "bg-violet-100 text-violet-700" : "bg-sky-100 text-sky-700")}>{l.deliveryType}</span>
                            <span className="block muted truncate">{l.place}{l.district ? ` · ${l.district}` : ""}</span>
                          </span>
                          <span className={cn("font-bold tabular shrink-0", l.costMissing && "text-rose-600")}>{l.costMissing ? "—" : ugx(l.amount)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}

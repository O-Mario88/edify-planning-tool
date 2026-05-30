"use client";

// PartnerPaymentLedger — per-activity payment ledger. Sits below the
// 7-state pipeline card and lets the partner see exactly which
// activities are at which payment stage, with the amount and the
// gating step. No internal Edify finance.

import { useMemo, useState } from "react";
import { Building2, Search } from "lucide-react";
import { cn } from "@/lib/utils";

type LedgerStatus =
  | "Not eligible"
  | "Awaiting CCEO"
  | "Awaiting PL"
  | "Sent to accountant"
  | "Paid"
  | "Returned"
  | "On hold";

type LedgerRow = {
  id: string;
  school: string;
  district: "Mukono" | "Kayunga";
  activity: string;
  amountUgx: number;
  status: LedgerStatus;
  blockingStep?: string;
  expectedClearance?: string;
  paidOn?: string;
  paidRef?: string;
};

const ROWS: LedgerRow[] = [
  { id: "PMT-001", school: "Hope Primary School",     district: "Mukono",  activity: "Follow-Up coaching visit",  amountUgx: 350_000, status: "Awaiting PL",        blockingStep: "PL approval", expectedClearance: "May 22, 2026" },
  { id: "PMT-002", school: "Kireka Primary School",   district: "Mukono",  activity: "Teacher training debrief",  amountUgx: 280_000, status: "Awaiting CCEO",      blockingStep: "CCEO confirmation", expectedClearance: "May 19, 2026" },
  { id: "PMT-003", school: "Namilyango Primary",      district: "Mukono",  activity: "Classroom observation",     amountUgx: 220_000, status: "Awaiting CCEO",      blockingStep: "CCEO confirmation", expectedClearance: "May 19, 2026" },
  { id: "PMT-004", school: "St. Mary's Primary",      district: "Kayunga", activity: "Leadership support visit",  amountUgx: 320_000, status: "Sent to accountant", blockingStep: "Accountant clearance", expectedClearance: "May 21, 2026" },
  { id: "PMT-005", school: "Eden Foundation School",  district: "Mukono",  activity: "P3 teacher coaching",       amountUgx: 380_000, status: "Sent to accountant", blockingStep: "Accountant clearance", expectedClearance: "May 21, 2026" },
  { id: "PMT-006", school: "Grace Primary School",    district: "Mukono",  activity: "Numeracy training",         amountUgx: 410_000, status: "Paid", paidOn: "May 14, 2026", paidRef: "BANK-2026-04891" },
  { id: "PMT-007", school: "Bright Future PS",        district: "Mukono",  activity: "Resource delivery",         amountUgx: 180_000, status: "Paid", paidOn: "May 13, 2026", paidRef: "BANK-2026-04877" },
  { id: "PMT-008", school: "Eastview Junior",         district: "Mukono",  activity: "Follow-Up visit",           amountUgx: 250_000, status: "Paid", paidOn: "May 12, 2026", paidRef: "BANK-2026-04864" },
  { id: "PMT-009", school: "Mukono Central PS",       district: "Mukono",  activity: "Classroom observation",     amountUgx: 220_000, status: "Paid", paidOn: "May 09, 2026", paidRef: "BANK-2026-04851" },
  { id: "PMT-010", school: "Maple Grove Primary",     district: "Kayunga", activity: "Literacy follow-up",        amountUgx: 0,       status: "Not eligible",       blockingStep: "Activity not delivered" },
  { id: "PMT-011", school: "Galiraaya Primary",       district: "Kayunga", activity: "Critical school follow-up", amountUgx: 0,       status: "Not eligible",       blockingStep: "Evidence missing" },
  { id: "PMT-012", school: "Lakeview Primary",        district: "Kayunga", activity: "Foundational literacy",     amountUgx: 290_000, status: "Returned",           blockingStep: "Report needs correction" },
  { id: "PMT-013", school: "Pope John PS",            district: "Mukono",  activity: "Lesson planning",           amountUgx: 240_000, status: "Returned",           blockingStep: "Attendance sheet unclear" },
  { id: "PMT-014", school: "Clover Primary School",   district: "Kayunga", activity: "Leadership support visit",  amountUgx: 270_000, status: "On hold",            blockingStep: "PL paused — scope review" },
];

const STATUS_TONE: Record<LedgerStatus, string> = {
  "Not eligible":       "bg-slate-100 text-slate-700",
  "Awaiting CCEO":      "bg-amber-50 text-amber-700",
  "Awaiting PL":        "bg-amber-50 text-amber-700",
  "Sent to accountant": "bg-blue-50 text-blue-700",
  "Paid":               "bg-emerald-50 text-emerald-700",
  "Returned":           "bg-rose-50 text-rose-700",
  "On hold":            "bg-rose-50 text-rose-700",
};

function fmtUgx(n: number): string {
  if (n === 0) return "—";
  if (n >= 1_000_000) return `UGX ${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `UGX ${(n / 1_000).toFixed(0)}K`;
  return `UGX ${n}`;
}

export function PartnerPaymentLedger() {
  const [filter, setFilter] = useState<"all" | LedgerStatus>("all");
  const [q, setQ] = useState("");

  const rows = useMemo(() => {
    return ROWS.filter((r) => {
      if (filter !== "all" && r.status !== filter) return false;
      if (q && !`${r.school} ${r.activity}`.toLowerCase().includes(q.toLowerCase())) return false;
      return true;
    });
  }, [filter, q]);

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3 flex-wrap">
        <div>
          <h3 className="text-[15px] font-extrabold tracking-tight">Payment ledger</h3>
          <p className="text-[12px] muted mt-1">
            Every activity, with its amount, payment status, and what's blocking it. Filter by stage to see what to chase.
          </p>
        </div>
        <div className="relative">
          <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]" />
          <input
            type="text"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search school or activity"
            className="h-8 pl-7 pr-2.5 w-[220px] rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          />
        </div>
      </header>

      {/* Filter chips */}
      <div className="flex items-center gap-1 flex-wrap mb-3">
        {(["all","Awaiting CCEO","Awaiting PL","Sent to accountant","Paid","Returned","On hold","Not eligible"] as const).map((f) => {
          const isActive = filter === f;
          const count = f === "all" ? ROWS.length : ROWS.filter((r) => r.status === f).length;
          return (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f as "all" | LedgerStatus)}
              className={cn(
                "inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md text-[11px] font-semibold transition-colors",
                isActive
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
              )}
            >
              {f === "all" ? "All" : f}
              <span className={cn(
                "inline-flex items-center justify-center min-w-[16px] h-[14px] px-1 rounded-md text-[9px] font-extrabold",
                isActive ? "bg-[var(--color-edify-primary)] text-white" : "bg-slate-100 text-slate-700",
              )}>
                {count}
              </span>
            </button>
          );
        })}
      </div>

      <div className="overflow-x-auto scrollbar -mx-1 px-1 rounded-md">
        <table className="w-full dtable">
          <thead className="bg-white">
            <tr>
              <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">School & activity</th>
              {/* District + Reference are secondary at tablet — they
                  starve the school-name column. Available at lg+ and
                  in the per-row drilldown. */}
              <th className="hidden lg:table-cell text-left text-[10px] uppercase tracking-wide font-bold muted">District</th>
              <th className="text-right text-[10px] uppercase tracking-wide font-bold muted">Amount</th>
              <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Status</th>
              <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Blocking step / paid</th>
              <th className="hidden lg:table-cell text-left text-[10px] uppercase tracking-wide font-bold muted">Reference / expected</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/40 transition-colors">
                <td>
                  <div className="flex items-center gap-2">
                    <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                      <Building2 size={11} />
                    </span>
                    <div className="min-w-0">
                      <div className="text-body font-extrabold leading-tight">{r.school}</div>
                      <div className="text-caption muted leading-tight mt-0.5">{r.activity}</div>
                    </div>
                  </div>
                </td>
                <td className="hidden lg:table-cell text-[12px]">{r.district}</td>
                <td className="text-right text-body font-extrabold tabular text-[var(--color-edify-text)] whitespace-nowrap">
                  {fmtUgx(r.amountUgx)}
                </td>
                <td>
                  <span className={cn("inline-flex items-center px-2 py-[3px] rounded-md text-caption font-bold whitespace-nowrap", STATUS_TONE[r.status])}>
                    {r.status}
                  </span>
                </td>
                <td className="text-[11.5px] text-[var(--color-edify-text)] leading-snug">
                  {r.paidOn
                    ? <span className="text-emerald-700 font-semibold">Paid on {r.paidOn}</span>
                    : <span>{r.blockingStep ?? "—"}</span>}
                </td>
                <td className="hidden lg:table-cell text-[11.5px] muted whitespace-nowrap">
                  {r.paidRef
                    ? <span className="font-mono text-caption">{r.paidRef}</span>
                    : r.expectedClearance
                      ? `Expected ${r.expectedClearance}`
                      : "—"}
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={6} className="text-center text-[12px] muted italic py-6">
                  No matching activities. Adjust the filter or search.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[12px] muted">
        Showing <span className="font-semibold text-[var(--color-edify-text)]">{rows.length}</span>{" "}
        of <span className="font-semibold text-[var(--color-edify-text)]">{ROWS.length}</span> activities
      </div>
    </section>
  );
}

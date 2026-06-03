"use client";

// Budget Ledger (Annual Detailed) — the activity-level plan that every budget
// figure traces back to. Filters + search + pagination, client-side.

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { fmtUgxShort } from "@/lib/funds/budget/budget-format";
import type { BudgetLedgerRow } from "@/lib/funds/budget/annual-rollup";

const FR_TONE: Record<string, "grey" | "amber" | "green" | "blue" | "violet"> = {
  Draft: "grey", "Under Review": "amber", Approved: "green", Released: "blue", Reconciled: "violet",
};
const AP_TONE: Record<string, "grey" | "amber" | "green" | "blue"> = {
  "Not Started": "grey", "In Progress": "amber", Approved: "green", Released: "blue",
};

function uniq(rows: BudgetLedgerRow[], sel: (r: BudgetLedgerRow) => string | undefined): string[] {
  return [...new Set(rows.map(sel).filter(Boolean) as string[])].sort();
}

export function BudgetLedgerTable({ rows }: { rows: BudgetLedgerRow[] }) {
  const [district, setDistrict] = useState("");
  const [activity, setActivity] = useState("");
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const pageSize = 25;

  const districts = useMemo(() => uniq(rows, (r) => r.district === "—" ? undefined : r.district), [rows]);
  const activities = useMemo(() => uniq(rows, (r) => r.activityType), [rows]);
  const statuses = ["Draft", "Under Review", "Approved", "Released", "Reconciled"];

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase();
    return rows.filter((r) => {
      if (district && r.district !== district) return false;
      if (activity && r.activityType !== activity) return false;
      if (status && r.fundRequestStatus !== status) return false;
      if (query && !(
        r.schoolOrCluster.toLowerCase().includes(query) ||
        r.district.toLowerCase().includes(query) ||
        (r.staff?.toLowerCase().includes(query) ?? false) ||
        (r.partner?.toLowerCase().includes(query) ?? false) ||
        r.activityType.toLowerCase().includes(query)
      )) return false;
      return true;
    });
  }, [rows, district, activity, status, q]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const shown = filtered.slice(safePage * pageSize, safePage * pageSize + pageSize);

  const selCls = "h-8 px-2 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px]";
  const reset = () => setPage(0);

  return (
    <SectionCard icon={<Search size={13} />} title="Budget Ledger (Annual Detailed)" subtitle={`${filtered.length.toLocaleString()} planned budget lines — every figure traces to an activity.`}>
      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-2.5">
        <select className={selCls} value={district} onChange={(e) => { setDistrict(e.target.value); reset(); }}>
          <option value="">All Districts</option>
          {districts.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <select className={selCls} value={activity} onChange={(e) => { setActivity(e.target.value); reset(); }}>
          <option value="">All Activity Types</option>
          {activities.map((a) => <option key={a} value={a}>{a}</option>)}
        </select>
        <select className={selCls} value={status} onChange={(e) => { setStatus(e.target.value); reset(); }}>
          <option value="">All Statuses</option>
          {statuses.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]" />
          <input value={q} onChange={(e) => { setQ(e.target.value); reset(); }} placeholder="Search ledger…"
            className="w-full h-8 pl-8 pr-3 text-[11.5px] rounded-lg bg-white border border-[var(--color-edify-border)] outline-none focus:outline-2 focus:outline-[var(--color-edify-primary)]" />
        </div>
      </div>

      <div className="overflow-x-auto scrollbar -mx-1 px-1">
        <table className="w-full dtable">
          <thead>
            <tr>
              <th className="text-left">FY</th><th className="text-left">Q</th><th className="text-left">Month</th><th className="text-left">Wk</th>
              <th className="text-left">Activity</th><th className="text-left">School/Cluster</th><th className="text-left">District</th>
              <th className="text-left">Staff/Partner</th><th className="text-left">Budget Line</th>
              <th className="text-right">Approved</th><th className="text-right">Requested</th><th className="text-right">Released</th>
              <th className="text-right">Spent</th><th className="text-right">Balance</th>
              <th className="text-left">Fund Req</th><th className="text-left">Approval</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((r) => (
              <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/40">
                <td className="text-[11px]">{r.fy.replace("FY ", "")}</td>
                <td className="text-[11px]">{r.quarter}</td>
                <td className="text-[11px]">{r.monthLabel}</td>
                <td className="text-[11px]">W{r.week}</td>
                <td className="text-[11px] capitalize">{r.activityType}</td>
                <td className="text-[11px] font-semibold">{r.schoolOrCluster}</td>
                <td className="text-[11px] muted">{r.district}</td>
                <td className="text-[11px] muted">{r.staff ?? r.partner ?? "—"}</td>
                <td className="text-[11px] muted">{r.budgetLine}</td>
                <td className="text-right text-[11px] tabular">{fmtUgxShort(r.approved)}</td>
                <td className="text-right text-[11px] tabular">{fmtUgxShort(r.requested)}</td>
                <td className="text-right text-[11px] tabular">{fmtUgxShort(r.released)}</td>
                <td className="text-right text-[11px] tabular">{fmtUgxShort(r.spent)}</td>
                <td className="text-right text-[11px] tabular font-semibold">{fmtUgxShort(r.balance)}</td>
                <td><StatusBadge tone={FR_TONE[r.fundRequestStatus]}>{r.fundRequestStatus}</StatusBadge></td>
                <td><StatusBadge tone={AP_TONE[r.approvalStatus]}>{r.approvalStatus}</StatusBadge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[var(--color-edify-divider)] flex items-center justify-between text-[12px]">
        <div className="muted">
          Showing {filtered.length === 0 ? 0 : safePage * pageSize + 1}–{Math.min(filtered.length, safePage * pageSize + pageSize)} of {filtered.length.toLocaleString()}
        </div>
        <div className="flex items-center gap-1.5">
          <button type="button" disabled={safePage === 0} onClick={() => setPage(safePage - 1)} className="h-7 px-2.5 rounded-lg border border-[var(--color-edify-border)] text-[11.5px] font-semibold disabled:opacity-40">Prev</button>
          <span className="text-[11.5px] muted tabular">{safePage + 1} / {pageCount}</span>
          <button type="button" disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)} className="h-7 px-2.5 rounded-lg border border-[var(--color-edify-border)] text-[11.5px] font-semibold disabled:opacity-40">Next</button>
        </div>
      </div>
    </SectionCard>
  );
}

// Smaller shared budget cards: risk alerts, fund-request status counts,
// recent fund requests, and the annual/quarterly/monthly snapshots.

import {
  AlertTriangle, AlertOctagon, Clock, FileText, CheckCircle2, Send, Layers,
  TrendingUp, CalendarRange, BarChart3,
} from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { fmtUgx, fmtUgxShort, fmtPct } from "@/lib/funds/budget/budget-format";
import type { AnnualBudgetRollup } from "@/lib/funds/budget/annual-rollup";

// Zone divider — segments the dashboard body into labeled groups so the page
// reads as ordered sections (Approval → Performance → Allocation) instead of a
// flat stack of equal-weight cards. Optional right-aligned note for context.
export function SectionEyebrow({ children, note }: { children: React.ReactNode; note?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 pt-1">
      <h2 className="text-[11px] font-bold uppercase tracking-[0.09em] text-[var(--color-edify-muted)] shrink-0">{children}</h2>
      <span className="flex-1 h-px bg-[var(--color-edify-border)]" />
      {note && <span className="text-[10.5px] muted shrink-0">{note}</span>}
    </div>
  );
}

export function BudgetRiskAlerts({ alerts, title = "Variance / Risk Alerts" }: {
  alerts: AnnualBudgetRollup["riskAlerts"];
  title?: string;
}) {
  const icon = (sev: string) => sev === "high" ? <AlertOctagon size={14} className="text-rose-600" />
    : sev === "medium" ? <AlertTriangle size={14} className="text-amber-500" />
    : <Clock size={14} className="text-sky-600" />;
  return (
    <SectionCard icon={<AlertTriangle size={13} />} title={title}>
      <ul className="space-y-2">
        {alerts.map((a) => (
          <li key={a.key} className="flex items-center justify-between gap-3 text-[12px]">
            <span className="inline-flex items-center gap-1.5">{icon(a.severity)} {a.label}</span>
            <span className="font-extrabold tabular">{a.count}</span>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

const FR_ICON: Record<string, React.ReactNode> = {
  Draft: <FileText size={15} className="text-slate-500" />,
  "Under Review": <Clock size={15} className="text-amber-500" />,
  Approved: <CheckCircle2 size={15} className="text-emerald-600" />,
  Released: <Send size={15} className="text-sky-600" />,
  Reconciled: <Layers size={15} className="text-violet-600" />,
};

export function FundRequestStatusRow({ counts }: { counts: AnnualBudgetRollup["fundRequestStatusCounts"] }) {
  return (
    <SectionCard icon={<FileText size={13} />} title="Fund Request Status">
      <div className="grid grid-cols-5 gap-2">
        {counts.map((c) => (
          <div key={c.status} className="rounded-lg border border-[var(--color-edify-border)] p-2.5 text-center">
            <div className="grid place-items-center mb-1">{FR_ICON[c.status]}</div>
            <div className="text-[11px] font-bold muted">{c.status}</div>
            <div className="text-[18px] font-extrabold tabular leading-none mt-1">{c.count}</div>
            <div className="text-[10px] muted mt-0.5">{fmtUgxShort(c.amount)}</div>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

export type RecentFundRequest = { id: string; name: string; region: string; status: string; date: string; tone: "green" | "amber" | "blue" | "grey" };

export function RecentFundRequestsCard({ requests }: { requests: RecentFundRequest[] }) {
  return (
    <SectionCard icon={<FileText size={13} />} title="Recent Fund Requests">
      <ul className="space-y-2.5">
        {requests.map((r) => (
          <li key={r.id} className="flex items-start justify-between gap-2">
            <div className="min-w-0">
              <div className="text-[12px] font-bold">{r.id}</div>
              <div className="text-[11px] muted truncate">{r.name} · {r.region}</div>
              <div className="text-[10px] muted">{r.date}</div>
            </div>
            <StatusBadge tone={r.tone}>{r.status}</StatusBadge>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}

export function BudgetSnapshots({ rollup }: { rollup: AnnualBudgetRollup }) {
  const q = rollup.byQuarter;
  return (
    <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
      <SectionCard icon={<TrendingUp size={13} />} title="Annual Snapshot">
        <dl className="space-y-2 text-[12px]">
          <Row label="Budget Utilization" value={fmtPct(rollup.utilizationPct)} />
          <Row label="Released vs Approved" value={fmtPct(rollup.utilizationPct)} />
          <Row label="Remaining Balance" value={fmtUgxShort(rollup.remaining)} />
          <Row label="Health Score" value={`${rollup.healthScore} / 100`} />
        </dl>
      </SectionCard>
      <SectionCard icon={<CalendarRange size={13} />} title="Quarterly Snapshot">
        <div className="grid grid-cols-4 gap-1.5 text-center">
          {q.map((x) => {
            const util = x.approved ? Math.round((x.released / x.approved) * 100) : 0;
            return (
              <div key={x.quarter} className="rounded-lg border border-[var(--color-edify-border)] p-2">
                <div className="text-[11px] font-bold muted">{x.quarter}</div>
                <div className="text-[14px] font-extrabold tabular">{util}%</div>
                <div className="text-[9.5px] muted">{fmtUgxShort(x.released)}</div>
              </div>
            );
          })}
        </div>
      </SectionCard>
      <SectionCard icon={<BarChart3 size={13} />} title="Monthly Snapshot" subtitle={MONTH_NAME(rollup.currentMonthIso)}>
        <dl className="space-y-2 text-[12px]">
          <Row label="Burn Rate" value={fmtPct(rollup.burnRatePct)} />
          <Row label="Released" value={fmtUgxShort(rollup.released)} />
          <Row label="Spent" value={fmtUgxShort(rollup.spent)} />
        </dl>
      </SectionCard>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="muted">{label}</dt>
      <dd className="font-extrabold tabular">{value}</dd>
    </div>
  );
}

function MONTH_NAME(iso: string): string {
  const names: Record<string, string> = {
    "01": "January", "02": "February", "03": "March", "04": "April", "05": "May", "06": "June",
    "07": "July", "08": "August", "09": "September", "10": "October", "11": "November", "12": "December",
  };
  const [y, m] = iso.split("-");
  return `${names[m] ?? m} ${y}`;
}

export { fmtUgx };

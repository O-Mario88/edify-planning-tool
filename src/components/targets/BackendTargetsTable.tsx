import { cn } from "@/lib/utils";
import type { BeTargets, BeTargetCell } from "@/lib/api/surfaces";

// Targets by Time Period — staff vs partner, cumulative. Backend-driven, scoped.
// Targets prove EXECUTION (work distributed + reached on time), distinct from
// SSA impact (school improvement).

const STATUS_TONE: Record<string, string> = {
  Ahead: "bg-emerald-100 text-emerald-700",
  "On Track": "bg-emerald-50 text-emerald-700",
  "Slightly Behind": "bg-amber-50 text-amber-700",
  Behind: "bg-amber-100 text-amber-700",
  Critical: "bg-rose-100 text-rose-700",
  "No Target": "bg-slate-100 text-slate-500",
};

function Cell({ c }: { c: BeTargetCell }) {
  return (
    <span className="tabular">
      <b>{c.achieved}</b><span className="muted">/{c.target}</span>
      {c.pct != null && <span className={cn("ml-1 text-[10px] font-bold", c.pct >= 100 ? "text-emerald-600" : c.pct >= 75 ? "text-amber-600" : "text-rose-600")}>{c.pct}%</span>}
    </span>
  );
}

export function BackendTargetsTable({ targets, title = "Targets by time period" }: { targets: BeTargets; title?: string }) {
  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <h2 className="text-[13px] font-extrabold tracking-tight">{title}</h2>
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10px] font-bold border border-emerald-200">Live · scoped · FY{targets.fy}</span>
      </header>

      <div className="text-[11px] muted mb-2">
        Portfolio <b className="text-[var(--color-edify-text)]">{targets.totalPortfolio}</b> · Staff target <b className="text-[var(--color-edify-text)]">{targets.annual.staffTarget}</b> · Partner target <b className="text-[var(--color-edify-text)]">{targets.annual.partnerTarget}</b>
      </div>

      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-[11.5px] px-1">
          <thead>
            <tr className="text-left text-caption muted font-bold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
              <th className="py-1.5 pr-2">Period</th>
              <th className="py-1.5 px-1.5 text-right">Staff</th>
              <th className="py-1.5 px-1.5 text-right">Partner</th>
              <th className="py-1.5 px-1.5 text-right">Total</th>
              <th className="py-1.5 px-1.5 text-right">Gap</th>
              <th className="py-1.5 pl-1.5">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {targets.rows.map((r) => {
              const milestone = r.period === "Mid-Year" || r.period === "End of Year";
              return (
                <tr key={r.period} className={cn(milestone && "bg-[var(--color-edify-soft)]/30")}>
                  <td className={cn("py-1.5 pr-2", milestone && "font-extrabold")}>{r.period}</td>
                  <td className="py-1.5 px-1.5 text-right"><Cell c={r.staff} /></td>
                  <td className="py-1.5 px-1.5 text-right">{r.partner.target > 0 ? <Cell c={r.partner} /> : <span className="muted">—</span>}</td>
                  <td className="py-1.5 px-1.5 text-right"><Cell c={r.total} /></td>
                  <td className="py-1.5 px-1.5 text-right tabular muted">{r.gap}</td>
                  <td className="py-1.5 pl-1.5"><span className={cn("text-[10px] font-bold px-1.5 py-[2px] rounded-full whitespace-nowrap", STATUS_TONE[r.status] ?? "bg-slate-100 text-slate-500")}>{r.status}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {targets.dataQuality.length > 0 && (
        <p className="mt-2 text-[11px] text-amber-700">{targets.dataQuality.join(" · ")}</p>
      )}
    </section>
  );
}

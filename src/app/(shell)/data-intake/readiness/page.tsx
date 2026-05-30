import Link from "next/link";
import { AlertTriangle, CheckCircle2, ShieldCheck } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  planningDataReadiness,
  dataReadinessForCountry,
  blockOrLimitPlanningFromReadiness,
} from "@/lib/data-intake-mock";
import { activeFinancialYear } from "@/lib/fy-engine";
import { cn } from "@/lib/utils";

export default function PlanningDataReadinessPage() {
  const fy   = activeFinancialYear();
  const r    = planningDataReadiness();
  const summary = dataReadinessForCountry();
  const verdict = blockOrLimitPlanningFromReadiness();

  return (
    <StubPage
      title="Planning Data Readiness"
      subtitle={`The Annual Operating Cycle checks readiness before opening a new FY, generating Gateway training, producing SSA-informed recommendations, building annual budgets, or activating monthly funding plans. ${fy.label}.`}
    >
      {/* Verdict */}
      <section className={cn(
        "card p-3.5 flex items-start gap-3",
        verdict.limit === "full"         && "border-emerald-200 bg-emerald-50",
        verdict.limit === "limited"      && "border-amber-200 bg-amber-50",
        verdict.limit === "gateway-only" && "border-rose-200 bg-rose-50",
      )}>
        <span className={cn(
          "h-10 w-10 rounded-xl grid place-items-center shrink-0",
          verdict.limit === "full"         && "bg-emerald-100 text-emerald-700",
          verdict.limit === "limited"      && "bg-amber-100   text-amber-700",
          verdict.limit === "gateway-only" && "bg-rose-100    text-rose-700",
        )}>
          {verdict.limit === "full" ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
        </span>
        <div className="flex-1 min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight">
            Planning engine: {verdict.limit === "full" ? "Full Planning Mode unlocked" : verdict.limit === "limited" ? "Limited Planning — some areas still need data" : "Gateway-only — full planning is BLOCKED"}
          </h2>
          <p className="text-[11.5px] muted">{verdict.reason}</p>
        </div>
      </section>

      {/* Per-area readiness */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-3">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <ShieldCheck size={14} className="text-[var(--color-edify-primary)]" />
            Required data — {summary.country} · {summary.financialYear}
          </h2>
          <span className="text-caption muted">{r.rows.length} checks</span>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {r.rows.map((row) => (
            <li key={row.area} className="py-2.5 flex items-center gap-3">
              <Dot status={row.status} />
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight">{row.area}</div>
                <div className="text-caption muted truncate">{row.note}</div>
              </div>
              <span className="text-caption muted shrink-0">{row.latestBatchStatus}</span>
              <span className={cn(
                "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0",
                row.status === "Ready"           && "bg-emerald-100 text-emerald-700",
                row.status === "Needs Attention" && "bg-amber-100   text-amber-700",
                row.status === "Blocked"         && "bg-rose-100    text-rose-700",
              )}>{row.status}</span>
            </li>
          ))}
        </ul>
      </section>

      {/* Blocking issues */}
      {r.blockingIssues.length > 0 && (
        <section className="card p-3.5 border-rose-200 bg-rose-50/40">
          <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-2">
            <AlertTriangle size={13} className="text-rose-700" />
            Blocking issues
          </h2>
          <ul className="mt-2 space-y-1 text-[12px]">
            {r.blockingIssues.map((b) => <li key={b}>• {b}</li>)}
          </ul>
        </section>
      )}

      {/* Recommended actions */}
      {summary.recommendedActions.length > 0 && (
        <section className="card p-3.5">
          <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Recommended actions</h2>
          <ol className="space-y-1.5 text-[12px] list-decimal list-inside">
            {summary.recommendedActions.map((a, i) => <li key={i}>{a}</li>)}
          </ol>
          <div className="mt-3 inline-flex items-center gap-2">
            <Link href="/data-intake/upload" className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold inline-flex items-center gap-1.5 hover:brightness-110">
              Open Upload Center
            </Link>
            <Link href="/data-intake/queue" className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] text-body font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60">
              Review Queue
            </Link>
          </div>
        </section>
      )}

      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Contract: </span>
        If critical data is missing, the system blocks or limits planning. Missing school assignments block
        staff planning. Missing current-FY SSA limits full recommendations. Missing cost settings block budget
        approval.
      </section>
    </StubPage>
  );
}

function Dot({ status }: { status: "Ready" | "Needs Attention" | "Blocked" }) {
  const c = status === "Ready" ? "#10b981" : status === "Needs Attention" ? "#f59e0b" : "#ef4444";
  return <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: c }} />;
}

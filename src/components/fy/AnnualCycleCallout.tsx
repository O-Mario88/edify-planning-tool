import Link from "next/link";
import {
  CalendarRange,
  GraduationCap,
  Activity,
  Wallet,
  Upload,
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import {
  activeFinancialYear,
  schoolFinancialYearSummaries,
} from "@/lib/fy-engine";
import { annualBudgetTotal, calculateBudgetVariance } from "@/lib/budget-mock";
import { validateCountryCostSettings, formatUgxBig } from "@/lib/cost-settings-mock";
import { planningDataReadiness } from "@/lib/data-intake-mock";
import { cn } from "@/lib/utils";

// Surfaces the Annual Operating Cycle posture on leadership dashboards.
// Variant tweaks the title; logic is identical (data is country-scoped).
export function AnnualCycleCallout({
  variant = "director",
}: {
  variant?: "director" | "rvp" | "cpl";
}) {
  const fy        = activeFinancialYear();
  const costCheck = validateCountryCostSettings();
  const readiness = planningDataReadiness();
  const v         = calculateBudgetVariance();

  const total       = schoolFinancialYearSummaries.length;
  const fullPlanning= schoolFinancialYearSummaries.filter((s) => s.planningMode === "Full Planning Mode").length;
  const gatewayDone = schoolFinancialYearSummaries.filter((s) => s.gatewayStatus === "Gateway Completed").length;

  const blockingCount = readiness.blockingIssues.length;
  const overallTone =
    blockingCount > 0 || !costCheck.ready ? "amber" :
    readiness.overall === "Ready"          ? "green" :
                                              "amber";

  const TITLE = {
    director: "Annual Operating Cycle — Country",
    rvp:      "Annual Operating Cycle — Region",
    cpl:      "Annual Operating Cycle — My Team",
  }[variant];

  return (
    <article id="annual-cycle" className="card p-3.5">
      <header className="flex items-baseline justify-between gap-2 mb-3">
        <div className="min-w-0">
          <h2 className="text-body-lg lg:text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
            <CalendarRange size={14} className="text-[var(--color-edify-primary)]" />
            {TITLE}
          </h2>
          <p className="text-[11.5px] muted leading-snug mt-0.5">
            {fy.label} · {fy.startDate} → {fy.endDate}. School Improvement Training → SSA → Plans → Budget.
          </p>
        </div>
        <Link
          href="/fy"
          className="hidden md:inline-flex h-9 px-3 rounded-xl border border-[var(--color-edify-border)] text-[11.5px] font-semibold items-center gap-1 hover:bg-[var(--color-edify-soft)]/60 shrink-0"
        >
          Open Annual Cycle
          <ChevronRight size={12} />
        </Link>
      </header>

      {/* 5 status tiles */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2.5">
        <Tile
          Icon={GraduationCap}
          label="Gateway Training"
          value={`${gatewayDone}/${total}`}
          sub="School Improvement Training"
          tone={gatewayDone === total ? "green" : "amber"}
          href="/fy/gateway"
        />
        <Tile
          Icon={Activity}
          label="Full Planning Mode"
          value={`${fullPlanning}/${total}`}
          sub="Gateway + SSA verified"
          tone={fullPlanning > total * 0.4 ? "green" : "amber"}
          href="/fy/ssa-comparison"
        />
        <Tile
          Icon={Wallet}
          label="Annual budget"
          value={formatUgxBig(annualBudgetTotal)}
          sub={`${v.pctSpent}% spent`}
          tone="edify"
          href="/budget"
        />
        <Tile
          Icon={CheckCircle2}
          label="Cost settings"
          value={costCheck.ready ? "All Active" : `${costCheck.missing.length} draft`}
          sub={costCheck.ready ? "Budget approval unblocked" : "Budget approval BLOCKED"}
          tone={costCheck.ready ? "green" : "rose"}
          href="/cost-settings"
        />
        <Tile
          Icon={Upload}
          label="Data readiness"
          value={readiness.overall}
          sub={`${readiness.rows.filter((r) => r.status === "Blocked").length} blocked`}
          tone={readiness.overall === "Ready" ? "green" : readiness.overall === "Needs Attention" ? "amber" : "rose"}
          href="/data-intake/readiness"
        />
      </div>

      {/* Blocking banner */}
      {(blockingCount > 0 || !costCheck.ready) && (
        <div className={cn(
          "mt-3 rounded-lg px-3 py-2 flex items-start gap-2 text-[11.5px]",
          overallTone === "amber" ? "border border-amber-200 bg-amber-50 text-amber-800" : "border border-rose-200 bg-rose-50 text-rose-800",
        )}>
          <AlertTriangle size={12} className="mt-0.5 shrink-0" />
          <span>
            <span className="font-extrabold">FY opening risk: </span>
            {!costCheck.ready && `${costCheck.missing.length} cost settings still Draft. `}
            {blockingCount > 0 && `${blockingCount} data area(s) blocked. `}
            <Link href="/fy/readiness" className="font-extrabold underline">Open Readiness Center →</Link>
          </span>
        </div>
      )}
    </article>
  );
}

function Tile({
  Icon, label, value, sub, tone, href,
}: {
  Icon: typeof CalendarRange;
  label: string;
  value: string;
  sub: string;
  tone: "edify" | "green" | "amber" | "rose";
  href: string;
}) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  return (
    <Link
      href={href}
      className="rounded-xl border border-[var(--color-edify-border)] p-3 flex flex-col gap-1.5 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <span className={cn("w-8 h-8 rounded-full grid place-items-center shrink-0", TONE[tone])}>
          <Icon size={13} />
        </span>
        <span className="text-caption muted font-semibold text-right leading-tight line-clamp-2">{label}</span>
      </div>
      <div className="text-[16px] font-extrabold tabular leading-none">{value}</div>
      <div className="text-[10px] muted leading-tight line-clamp-2">{sub}</div>
    </Link>
  );
}

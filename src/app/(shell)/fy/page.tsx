import Link from "next/link";
import {
  CalendarRange,
  ShieldCheck,
  GraduationCap,
  TrendingUp,
  ListChecks,
  ChevronRight,
  AlertTriangle,
  CheckCircle2,
  Lock,
} from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import {
  activeFinancialYear,
  previousFinancialYear,
  nextFinancialYear,
  schoolFinancialYearSummaries,
  generateWhatChangedFromLastYear,
} from "@/lib/fy-engine";
import { planningDataReadiness } from "@/lib/data-intake-mock";
import { validateCountryCostSettings } from "@/lib/cost-settings-mock";
import { cn } from "@/lib/utils";

export default function AnnualOperatingCyclePage() {
  const active   = activeFinancialYear();
  const previous = previousFinancialYear();
  const next     = nextFinancialYear();

  const gatewayDone = schoolFinancialYearSummaries.filter((s) => s.gatewayStatus === "Gateway Completed").length;
  const ssaVerified = schoolFinancialYearSummaries.filter((s) => s.ssaVerified).length;
  const inFull      = schoolFinancialYearSummaries.filter((s) => s.planningMode === "Full Planning Mode").length;
  const total       = schoolFinancialYearSummaries.length;

  const readiness  = planningDataReadiness();
  const costCheck  = validateCountryCostSettings();
  const changed    = generateWhatChangedFromLastYear();

  return (
    <StubPage
      title="Annual Operating Cycle"
      subtitle="The Edify financial year runs October 1 – September 30. This is the yearly operating backbone — FY status, Gateway training, SSA freshness, planning lock levels, cost settings, and budget readiness."
    >
      {/* FY status row */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <FyCard fy={previous} subtitle="Previous FY — locked for historical reporting" tone="slate" />
        <FyCard fy={active}   subtitle="Active FY — counters reset Oct 1; history preserved" tone="emerald" highlight />
        <FyCard fy={next}     subtitle="Next FY — Draft Setup; opens Oct 1, 2026" tone="violet" />
      </section>

      {/* Active FY headline KPIs */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Schools in Active FY"     value={String(total)}        sub="counters reset Oct 1, history preserved" />
        <Kpi label="Gateway Training done"    value={`${gatewayDone}/${total}`} sub="School Improvement Training completed" tone={gatewayDone === total ? "green" : "amber"} />
        <Kpi label="Current FY SSA Verified"  value={`${ssaVerified}/${total}`} sub="SSA verified for FY 2025/26" tone={ssaVerified > total * 0.5 ? "green" : "amber"} />
        <Kpi label="Full Planning Mode"       value={`${inFull}/${total}`} sub="Gateway + SSA Verified" tone={inFull > total * 0.4 ? "green" : "amber"} />
      </section>

      {/* Readiness + cost-settings traffic lights */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-3">
          <h2 className="text-body-lg font-extrabold tracking-tight">FY opening posture</h2>
          <Link href="/fy/readiness" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
            Open Readiness center →
          </Link>
        </header>
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {readiness.rows.map((r) => (
            <li key={r.area} className="flex items-center gap-3 px-3 py-2 rounded-md bg-[var(--color-edify-soft)]/40">
              <Dot status={r.status} />
              <div className="flex-1 min-w-0">
                <div className="text-[12px] font-extrabold tracking-tight">{r.area}</div>
                <div className="text-caption muted truncate">{r.note}</div>
              </div>
              <span className="text-caption muted shrink-0">{r.latestBatchStatus}</span>
            </li>
          ))}
        </ul>
        {!costCheck.ready && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 inline-flex items-center gap-2 text-[11.5px] text-amber-800">
            <AlertTriangle size={12} />
            <span><span className="font-extrabold">FY Opening Risk —</span> {costCheck.missing.length} cost settings still in Draft. Country Director must activate them before final budget approval.</span>
          </div>
        )}
      </section>

      {/* What changed from last FY */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-3">
          <h2 className="text-body-lg font-extrabold tracking-tight">What changed from last FY?</h2>
          <Link href="/fy/whats-changed" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
            Full report →
          </Link>
        </header>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-[12px]">
          <Change label="Schools added"        value={changed.schoolsAdded}        tone="emerald" />
          <Change label="Schools removed"      value={changed.schoolsRemoved}      tone="rose" />
          <Change label="Inactive"             value={changed.schoolsInactive}     tone="slate" />
          <Change label="Client → Core"        value={changed.clientToCore}        tone="violet" />
          <Change label="Champion candidates"  value={changed.championCandidates}  tone="amber" />
          <Change label="Districts improving"  value={changed.districtsImproving}  tone="emerald" />
          <Change label="Districts declining"  value={changed.districtsDeclining}  tone="rose" />
          <Change label="Cost changes"         value={changed.costChanges}         tone="slate" />
          <Change label="Target changes"       value={changed.targetChanges}       tone="slate" />
          <Change label="Budget changes"       value={changed.budgetChanges}       tone="slate" />
        </div>
      </section>

      {/* Section nav */}
      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        <Tile href="/fy/readiness"      Icon={ListChecks}    title="New FY Readiness Center" body="Traffic-light readiness for opening the next FY." />
        <Tile href="/fy/gateway"        Icon={GraduationCap} title="School Improvement Training Gateway" body="Every active school's annual gateway status." />
        <Tile href="/fy/ssa-comparison" Icon={TrendingUp}    title="Yearly SSA Performance Comparison" body="District, cluster, and 8-intervention YoY analysis." />
        <Tile href="/fy/timeline"       Icon={CalendarRange} title="Annual Planning Timeline"      body="The Aug-to-Sept cycle with decision gates." />
        <Tile href="/cost-settings"     Icon={ShieldCheck}   title="Country Cost Settings"        body="CD-controlled unit costs for the active FY." />
        <Tile href="/budget"            Icon={CheckCircle2}  title="Annual Budget Builder"        body="Generated from schools + service rules + costs." />
      </section>
    </StubPage>
  );
}

function FyCard({
  fy, subtitle, tone, highlight,
}: {
  fy?: ReturnType<typeof activeFinancialYear>; subtitle: string;
  tone: "slate" | "emerald" | "violet"; highlight?: boolean;
}) {
  if (!fy) return null;
  const Icon = fy.status === "Active" ? CheckCircle2 : fy.status === "Locked" ? Lock : CalendarRange;
  const TONE = {
    slate:   "bg-slate-100   text-slate-700",
    emerald: "bg-emerald-100 text-emerald-700",
    violet:  "bg-violet-100  text-violet-700",
  } as const;
  return (
    <div className={cn(
      "card p-3.5 flex items-start gap-3",
      highlight && "ring-1 ring-emerald-300",
    )}>
      <span className={cn("h-10 w-10 rounded-xl grid place-items-center shrink-0", TONE[tone])}>
        <Icon size={18} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-body-lg font-extrabold tracking-tight">{fy.label}</h2>
          <span className="text-caption muted">{fy.status}</span>
        </div>
        <p className="text-[11px] muted leading-snug mt-0.5">{subtitle}</p>
        <p className="text-caption muted mt-1.5">{fy.startDate} → {fy.endDate}</p>
      </div>
    </div>
  );
}

function Kpi({ label, value, sub, tone = "edify" }: { label: string; value: string; sub: string; tone?: "edify" | "green" | "amber" | "rose" }) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
    rose:  "bg-rose-100    text-rose-700",
  } as const;
  return (
    <div className="card p-3.5">
      <div className={cn("text-[11.5px] font-semibold inline-flex items-center px-2 py-[2px] rounded-md", TONE[tone])}>{label}</div>
      <div className="text-[24px] font-extrabold tabular leading-none mt-2">{value}</div>
      <div className="text-caption muted mt-1">{sub}</div>
    </div>
  );
}

function Dot({ status }: { status: "Ready" | "Needs Attention" | "Blocked" }) {
  const c = status === "Ready" ? "#10b981" : status === "Needs Attention" ? "#f59e0b" : "#ef4444";
  return <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: c }} />;
}

function Change({ label, value, tone }: { label: string; value: number; tone: "emerald" | "rose" | "slate" | "violet" | "amber" }) {
  const TONE = {
    emerald: "text-emerald-700",
    rose:    "text-rose-700",
    slate:   "text-slate-700",
    violet:  "text-violet-700",
    amber:   "text-amber-700",
  } as const;
  return (
    <div className="rounded-xl border border-[var(--color-edify-border)] p-2.5">
      <div className="text-caption muted font-semibold leading-tight">{label}</div>
      <div className={cn("text-[20px] font-extrabold tabular leading-none mt-1", TONE[tone])}>{value}</div>
    </div>
  );
}

function Tile({ href, Icon, title, body }: { href: string; Icon: typeof CalendarRange; title: string; body: string }) {
  return (
    <Link href={href} className="card p-3.5 flex items-start gap-3 hover:bg-[var(--color-edify-soft)]/40 transition-colors">
      <span className="h-10 w-10 rounded-xl bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
        <Icon size={18} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[13.5px] font-extrabold tracking-tight">{title}</h3>
          <ChevronRight size={13} className="text-[var(--color-edify-muted)]" />
        </div>
        <p className="text-[11.5px] muted leading-snug mt-0.5">{body}</p>
      </div>
    </Link>
  );
}

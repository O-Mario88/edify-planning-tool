import Link from "next/link";
import { AlertTriangle, CheckCircle2, ShieldCheck, AlertCircle } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { runDataQualityScan } from "@/lib/intake/data-quality-mock";
import { CountryDataQualityCard } from "@/components/intake/CountryDataQualityCard";
import { activeFinancialYear } from "@/lib/fy-engine";
import { getCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { cn } from "@/lib/utils";

export default async function DataQualityCenterPage() {
  const me = await getCurrentUser();
  const fy = activeFinancialYear();
  const allowed = ["ImpactAssessment", "Admin"].includes(me.role);

  // The integrity scan + country confidence card run off hand-mocked fixtures
  // (data-quality-mock, country-data-quality) — no live data-quality backend.
  // Never render fabricated quality scores in production.
  if (!isMockAllowed()) {
    return (
      <StubPage
        title="Data Quality Center"
        subtitle={`Every school feeding the planning engine is scanned for the integrity issues that would poison targets, leaderboards, and donor reports. ${fy.label}.`}
      >
        {!allowed && (
          <section className="card p-3.5 border-amber-200 bg-amber-50/60">
            <h2 className="text-[13px] font-extrabold tracking-tight">Data quality is an Impact Assessment view</h2>
            <p className="text-[11.5px] muted">Only Impact Assessment and Admin own data quality.</p>
          </section>
        )}
        <InsufficientData surface="the data quality center" detail="Integrity scores and issue logs are withheld until the data-quality backend is wired — no fabricated quality figures are shown." />
      </StubPage>
    );
  }

  const r = runDataQualityScan();

  const verdict = r.errors > 0 ? "Errors" : r.warnings > 0 ? "Warnings" : "Clean";

  return (
    <StubPage
      title="Data Quality Center"
      subtitle={`Every school feeding the planning engine is scanned for the integrity issues that would poison targets, leaderboards, and donor reports. ${fy.label}.`}
    >
      {!allowed && (
        <section className="card p-3.5 border-amber-200 bg-amber-50/60">
          <h2 className="text-[13px] font-extrabold tracking-tight">Data quality is an Impact Assessment view</h2>
          <p className="text-[11.5px] muted">
            Only Impact Assessment and Admin own data quality. You can see the scorecard, but resolving issues is done
            through the data-intake workflows.
          </p>
        </section>
      )}

      {/* Country data quality — workflow-aware confidence score (spec layer #10). */}
      <CountryDataQualityCard />

      {/* School master-data integrity scan (below the country headline). */}
      <section className={cn(
        "card p-3.5 flex items-start gap-3",
        verdict === "Clean"    && "border-emerald-200 bg-emerald-50",
        verdict === "Warnings" && "border-amber-200 bg-amber-50",
        verdict === "Errors"   && "border-rose-200 bg-rose-50",
      )}>
        <span className={cn(
          "h-10 w-10 rounded-xl grid place-items-center shrink-0",
          verdict === "Clean"    && "bg-emerald-100 text-emerald-700",
          verdict === "Warnings" && "bg-amber-100   text-amber-700",
          verdict === "Errors"   && "bg-rose-100    text-rose-700",
        )}>
          {verdict === "Clean" ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
        </span>
        <div className="flex-1 min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight">
            Data quality: {r.qualityScore}% clean
          </h2>
          <p className="text-[11.5px] muted">
            {r.cleanSchools} of {r.totalSchools} schools have no integrity issue. {r.errors} error{r.errors === 1 ? "" : "s"} and{" "}
            {r.warnings} warning{r.warnings === 1 ? "" : "s"} found. Errors block a school from rolling up; warnings degrade its data.
          </p>
        </div>
        <div className="text-right shrink-0">
          <div className={cn(
            "text-[28px] font-extrabold tabular leading-none",
            r.qualityScore >= 90 ? "text-emerald-600" : r.qualityScore >= 70 ? "text-amber-600" : "text-rose-600",
          )}>{r.qualityScore}%</div>
          <div className="text-caption muted mt-1">quality score</div>
        </div>
      </section>

      {/* KPIs */}
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Kpi label="Schools scanned"  value={String(r.totalSchools)}  sub="Analytics spine + intake" />
        <Kpi label="Clean schools"    value={String(r.cleanSchools)}  sub="No issues at all" tone="green" />
        <Kpi label="Errors"           value={String(r.errors)}        sub="Block roll-up" tone={r.errors > 0 ? "rose" : "green"} />
        <Kpi label="Warnings"         value={String(r.warnings)}      sub="Degrade data" tone={r.warnings > 0 ? "amber" : "green"} />
      </section>

      {/* By category */}
      <section className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Issues by category</h2>
        {r.byCategory.length === 0 ? (
          <p className="text-[11.5px] muted">No issues found — every school is clean.</p>
        ) : (
          <ul className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {r.byCategory.map((c) => (
              <li key={c.category} className="flex items-center gap-3 rounded-lg border border-[var(--color-edify-divider)] px-3 py-2">
                <span className={cn(
                  "h-8 w-8 rounded-lg grid place-items-center shrink-0",
                  c.severity === "Error" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700",
                )}>
                  {c.severity === "Error" ? <AlertCircle size={15} /> : <AlertTriangle size={15} />}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[12.5px] font-extrabold tracking-tight">{c.category}</div>
                  <div className="text-caption muted">{c.severity}</div>
                </div>
                <span className="text-[18px] font-extrabold tabular">{c.count}</span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Issue list */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight">Issue log</h2>
          <Link href="/data-intake" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
            Back to Data Intake →
          </Link>
        </header>
        {r.issues.length === 0 ? (
          <div className="flex items-center gap-2 py-4 text-[12px] text-emerald-700">
            <ShieldCheck size={16} /> All scanned schools passed every integrity check.
          </div>
        ) : (
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {r.issues.slice(0, 40).map((i, idx) => (
              <li key={`${i.schoolId}-${i.category}-${idx}`} className="py-2.5 flex items-center gap-3">
                <span className={cn(
                  "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0",
                  i.severity === "Error" ? "bg-rose-100 text-rose-700" : "bg-amber-100 text-amber-700",
                )}>{i.severity}</span>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-extrabold tracking-tight truncate">{i.schoolName} · {i.category}</div>
                  <div className="text-caption muted truncate">{i.detail}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
        {r.issues.length > 40 && (
          <p className="text-caption muted mt-2">Showing the first 40 of {r.issues.length} issues.</p>
        )}
      </section>
    </StubPage>
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

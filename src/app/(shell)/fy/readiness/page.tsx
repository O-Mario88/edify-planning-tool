import Link from "next/link";
import { AlertTriangle, CheckCircle2, ListChecks } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { activeFinancialYear, nextFinancialYear } from "@/lib/fy-engine";
import { planningDataReadiness } from "@/lib/data-intake-mock";
import { validateCountryCostSettings } from "@/lib/cost-settings-mock";
import { cn } from "@/lib/utils";

type ReadinessItem = {
  area:    string;
  status:  "Ready" | "Needs Attention" | "Blocked";
  detail:  string;
  action?: { label: string; href: string };
  critical:boolean;
};

export default function NewFyReadinessCenterPage() {
  const active = activeFinancialYear();
  const next   = nextFinancialYear();
  const r      = planningDataReadiness();
  const cs     = validateCountryCostSettings();

  // Compose the full readiness check list — pulled from spec's required
  // items + the live readiness check.
  const ITEMS: ReadinessItem[] = [
    { area: "School register ready",          status: r.rows.find((x) => x.area === "School Register")?.status ?? "Blocked",  detail: r.rows.find((x) => x.area === "School Register")?.note ?? "—", critical: true,  action: { label: "Open Data Intake", href: "/data-intake" } },
    { area: "Staff assignments complete",     status: r.rows.find((x) => x.area === "Staff Register")?.status ?? "Blocked",   detail: r.rows.find((x) => x.area === "Staff Register")?.note ?? "—",  critical: true,  action: { label: "Open Data Intake", href: "/data-intake" } },
    { area: "Partner assignments complete",   status: r.rows.find((x) => x.area === "Partner Register")?.status ?? "Blocked", detail: r.rows.find((x) => x.area === "Partner Register")?.note ?? "—", critical: false, action: { label: "Open Data Intake", href: "/data-intake" } },
    { area: "Cost settings approved",         status: cs.ready ? "Ready" : "Needs Attention", detail: cs.ready ? `All ${cs.total} items Active` : `${cs.missing.length} of ${cs.total} still Draft`, critical: true,  action: { label: "Country Cost Settings", href: "/cost-settings" } },
    { area: "Public holidays loaded",         status: r.rows.find((x) => x.area === "Public Holidays")?.status ?? "Blocked",  detail: r.rows.find((x) => x.area === "Public Holidays")?.note ?? "—", critical: false, action: { label: "Open Data Intake", href: "/data-intake" } },
    { area: "Leave & blackout calendar",      status: "Needs Attention", detail: "Conference week + Q1 blackouts not yet uploaded", critical: false, action: { label: "Open Data Intake", href: "/data-intake" } },
    { area: "Training clusters drafted",      status: "Ready",          detail: "Cluster names + 12-school groupings recommended by engine", critical: true },
    { area: "School Improvement Training dates", status: "Needs Attention", detail: "Staff to confirm cluster dates by Sep 30",                critical: true,  action: { label: "Open Gateway", href: "/fy/gateway" } },
    { area: "SSA tools ready",                status: "Ready",          detail: "8-intervention rubric + verification rules deployed",       critical: true },
    { area: "Targets approved",               status: r.rows.find((x) => x.area === "Target Settings")?.status ?? "Blocked", detail: r.rows.find((x) => x.area === "Target Settings")?.note ?? "—", critical: true,  action: { label: "Open Data Intake", href: "/data-intake" } },
    { area: "Budget baseline generated",      status: "Ready",          detail: "Annual budget template generated from service rules",       critical: true,  action: { label: "Open Budget Builder", href: "/budget" } },
    { area: "Core School package rules",      status: "Ready",          detail: "4 visits + 4 trainings per Core school confirmed",          critical: false },
    { area: "Special project targets",        status: "Needs Attention", detail: "EdTech + UCU partner targets pending CD sign-off",         critical: false, action: { label: "Open Data Intake", href: "/data-intake" } },
  ];

  const criticalBlocked = ITEMS.filter((i) => i.critical && i.status === "Blocked").length;
  const criticalAttention = ITEMS.filter((i) => i.critical && i.status === "Needs Attention").length;
  const verdict =
    criticalBlocked > 0   ? { label: "Blocked",        tone: "rose"   as const, note: "Critical items must be resolved before opening the next FY." } :
    criticalAttention > 0 ? { label: "Needs Attention", tone: "amber"  as const, note: "Some critical items still need sign-off." } :
                            { label: "Ready to Open",   tone: "green"  as const, note: "Every critical area is green. The new FY can be opened." };

  return (
    <StubPage
      title="New FY Readiness Center"
      subtitle={`Are we ready to open ${next?.label ?? "the next FY"}? Each row is a traffic-light check from the system. Critical items (marked) must all be green before the FY opens.`}
    >
      {/* Headline verdict */}
      <section className={cn(
        "card p-3.5 flex items-start gap-3",
        verdict.tone === "rose"  && "border-rose-200 bg-rose-50",
        verdict.tone === "amber" && "border-amber-200 bg-amber-50",
        verdict.tone === "green" && "border-emerald-200 bg-emerald-50",
      )}>
        <span className={cn(
          "h-10 w-10 rounded-xl grid place-items-center shrink-0",
          verdict.tone === "rose"  && "bg-rose-100 text-rose-700",
          verdict.tone === "amber" && "bg-amber-100 text-amber-700",
          verdict.tone === "green" && "bg-emerald-100 text-emerald-700",
        )}>
          {verdict.tone === "green" ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
        </span>
        <div className="flex-1 min-w-0">
          <h2 className="text-[15px] font-extrabold tracking-tight">FY Opening Status: {verdict.label}</h2>
          <p className="text-[12px] muted">{verdict.note}</p>
          <div className="mt-2 inline-flex items-center gap-3 text-caption muted">
            <span>Active FY: <span className="font-extrabold text-[var(--color-edify-text)]">{active.label}</span></span>
            {next && <span>Next FY: <span className="font-extrabold text-[var(--color-edify-text)]">{next.label}</span></span>}
          </div>
        </div>
      </section>

      {/* Checks */}
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <ListChecks size={14} className="text-[var(--color-edify-primary)]" />
            Readiness checks
          </h2>
          <span className="text-caption muted">{ITEMS.length} checks · {ITEMS.filter((i) => i.critical).length} critical</span>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {ITEMS.map((i) => (
            <li key={i.area} className="py-2.5 flex items-center gap-3">
              <Dot status={i.status} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-body font-extrabold tracking-tight truncate">{i.area}</span>
                  {i.critical && <span className="text-[9.5px] font-extrabold uppercase tracking-wide muted">Critical</span>}
                </div>
                <div className="text-caption muted truncate">{i.detail}</div>
              </div>
              <span className={cn(
                "inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap shrink-0",
                i.status === "Ready"           && "bg-emerald-100 text-emerald-700",
                i.status === "Needs Attention" && "bg-amber-100   text-amber-700",
                i.status === "Blocked"         && "bg-rose-100    text-rose-700",
              )}>
                {i.status}
              </span>
              {i.action && (
                <Link
                  href={i.action.href}
                  className="text-caption font-semibold text-[var(--color-edify-primary)] hover:underline shrink-0"
                >
                  {i.action.label} →
                </Link>
              )}
            </li>
          ))}
        </ul>
      </section>

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
    </StubPage>
  );
}

function Dot({ status }: { status: "Ready" | "Needs Attention" | "Blocked" }) {
  const c = status === "Ready" ? "#10b981" : status === "Needs Attention" ? "#f59e0b" : "#ef4444";
  return <span className="h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: c }} />;
}

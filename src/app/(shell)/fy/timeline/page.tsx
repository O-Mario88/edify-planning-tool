import { CalendarRange, CheckCircle2, AlertTriangle, Clock } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { activeFinancialYear, previousFinancialYear } from "@/lib/fy-engine";
import { cn } from "@/lib/utils";

type Phase = {
  months: string;
  title:  string;
  body:   string;
  status: "Done" | "In Progress" | "Upcoming";
  gate?:  string;
};

const PHASES: Phase[] = [
  { months: "Aug – Sep",  title: "FY Setup + Cost Settings",                        body: "Country Director sets cost settings. School + staff + partner registers verified. Readiness center turns green.",         status: "Done",         gate: "Gate 1: FY Setup Ready" },
  { months: "Oct",        title: "School Improvement Training Gateway",            body: "Every active school enters Gateway Required. Cluster trainings scheduled (staff edits cluster name + date only).",     status: "Done",         gate: "Gate 2: Gateway Training Complete" },
  { months: "Nov",        title: "SSA Completion + Verification",                  body: "Once gateway is done, SSA becomes due. SSAs run, then Impact Assessment verifies. Outdated SSAs trigger SSA Needed.",   status: "In Progress",  gate: "Gate 3: SSA Ready" },
  { months: "Dec",        title: "SSA Analysis + Annual Planning",                 body: "SSA-informed annual plans generated. Planning Lock flips from Limited → Full once verified SSA exists.",                 status: "Upcoming",     gate: "Gate 4: Annual Plan Ready" },
  { months: "Jan – Mar",  title: "Q2 Implementation",                              body: "Plans execute. Monthly funding flows. Field debriefs roll up. Salesforce IDs verified.",                                  status: "Upcoming" },
  { months: "Apr – Jun",  title: "Q3 Mid-Year Review + Catch-Up",                  body: "Mid-year detector + support reviews. Recovery focus for under-performing staff. PIP gates open only after support.",   status: "Upcoming" },
  { months: "Jul – Sep",  title: "Final push, verification, closure",              body: "Year-end exam results, enrollment updates, MSC stories. Yearly comparison ready by Sep 30. FY locks at midnight.",      status: "Upcoming",     gate: "Gate 5: Annual Budget Ready (next FY)" },
];

export default function AnnualPlanningTimelinePage() {
  const active = activeFinancialYear();
  const prev   = previousFinancialYear();

  return (
    <StubPage
      title="Annual Planning Timeline"
      subtitle={`The Edify FY runs October 1 – September 30. ${prev?.label} is Locked; ${active.label} is Active. Each phase carries a Decision Gate that must be signed off before the next phase opens.`}
    >
      <section className="card p-3.5">
        <ol className="relative ml-3 border-l border-[var(--color-edify-border)]">
          {PHASES.map((p, i) => {
            const Icon = p.status === "Done" ? CheckCircle2 : p.status === "In Progress" ? Clock : CalendarRange;
            const tone =
              p.status === "Done"        ? "bg-emerald-100 text-emerald-700" :
              p.status === "In Progress" ? "bg-amber-100   text-amber-700"   :
                                            "bg-slate-100   text-slate-700";
            return (
              <li key={i} className="ml-5 pb-5 relative">
                <span className={cn(
                  "absolute -left-[28px] top-0 h-6 w-6 rounded-full grid place-items-center ring-2 ring-white",
                  tone,
                )}>
                  <Icon size={11} />
                </span>
                <div className="flex items-baseline justify-between gap-2">
                  <div className="text-caption muted font-extrabold uppercase tracking-wide">{p.months}</div>
                  <span className={cn(
                    "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                    p.status === "Done"        && "bg-emerald-100 text-emerald-700",
                    p.status === "In Progress" && "bg-amber-100   text-amber-700",
                    p.status === "Upcoming"    && "bg-slate-100   text-slate-700",
                  )}>{p.status}</span>
                </div>
                <h3 className="text-body-lg font-extrabold tracking-tight mt-0.5">{p.title}</h3>
                <p className="text-[12px] muted leading-snug">{p.body}</p>
                {p.gate && (
                  <div className="mt-1.5 inline-flex items-center gap-1.5 text-caption font-extrabold text-[var(--color-edify-primary)] bg-[var(--color-edify-soft)]/80 px-2 py-[2px] rounded-md">
                    <AlertTriangle size={10} />
                    {p.gate}
                  </div>
                )}
              </li>
            );
          })}
        </ol>
      </section>
    </StubPage>
  );
}

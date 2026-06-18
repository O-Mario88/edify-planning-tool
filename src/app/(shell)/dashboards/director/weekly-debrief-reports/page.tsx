import Link from "next/link";
import { redirect } from "next/navigation";
import {
  FileText,
  Download,
  AlertTriangle,
  Sparkles,
  Globe,
  ChevronRight,
  ChevronDown,
  Clock,
} from "lucide-react";
import { ActionButton } from "@/components/ui/ActionButton";
import { PageHeader } from "@/components/ui/PageHeader";
import { getCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import {
  programLeadWeeklyFieldReports,
  countryWeeklyFieldIntelligence,
} from "@/lib/field-intelligence-mock";
import { cn } from "@/lib/utils";

// SLA: Program Leads should submit their weekly report by Saturday 23:59
// of the reporting week. After that, the report is flagged as late.
function isReportLate(submittedAt: string | undefined, weekEnd: string): boolean {
  if (!submittedAt) return true;
  const submitted = new Date(submittedAt);
  const cutoff    = new Date(`${weekEnd}T23:59:00`); // Saturday EOD
  // The mock week ends Saturday; allow same-day submission.
  return submitted.getTime() > cutoff.getTime();
}

// CD Weekly Debrief Report Center.
//
// Per visibility rule, only the Country Director (and the Admin masquerading
// as CD) sees this list of Program Lead Weekly Field Reports. RVPs are
// pointed at the Country Weekly Field Intelligence Report instead.

const ALLOWED = new Set(["CountryDirector", "Admin"]);

const STATUS_TONE: Record<string, string> = {
  "Generated":                "bg-slate-100   text-slate-700",
  "PL Editing":               "bg-amber-100   text-amber-700",
  "Submitted to CD":          "bg-emerald-100 text-emerald-700",
  "Returned for Clarification":"bg-rose-100   text-rose-700",
  "Resubmitted":              "bg-violet-100  text-violet-700",
  "Reviewed by CD":           "bg-sky-100     text-sky-700",
  "Closed":                   "bg-slate-100   text-slate-500",
};

export default async function WeeklyDebriefReportCenterPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) {
    redirect("/dashboard");
  }

  // The country rollup card and the per-PL weekly reports (named staff, achievement
  // figures, decisions) are entirely hand-mocked — no live weekly-report backend.
  // Never render fabricated leadership reports the CD would act on.
  if (!isMockAllowed()) {
    return (
      <>
        <PageHeader
          title="CD Weekly Debrief Report Center"
          subtitle="One report per Program Lead. Daily debriefs stay with Program Leads — only weekly compiled reports surface here."
        />
        <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6">
          <InsufficientData surface="the weekly debrief report center" detail="Program-Lead weekly field reports and the country rollup are withheld until the weekly-report backend is wired — no fabricated named reports or achievement figures are shown." />
        </div>
      </>
    );
  }

  const reports = programLeadWeeklyFieldReports;
  const country = countryWeeklyFieldIntelligence;
  const totalDecisions = reports.reduce((a, r) => a + r.decisionsRequiredFromCD.length, 0);

  return (
    <>
      {/* Canonical page chrome — title + search + identity cluster. The week
          selector rides the `actions` slot (demo shows the current week only;
          the chip stays visible to set the expectation that prior weeks live
          here). NOTE: PageHeader is a Client Component — pass only
          strings/ReactNode from this server page, never icon components. */}
      <PageHeader
        title="CD Weekly Debrief Report Center"
        subtitle="One report per Program Lead. Daily debriefs stay with Program Leads — only weekly compiled reports surface here. Use the week selector to scan prior weeks."
        actions={
          <button
            type="button"
            className="h-10 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white inline-flex items-center gap-2 text-[12px] font-bold whitespace-nowrap"
          >
            <Clock size={13} className="text-[var(--color-edify-primary)]" />
            <span>{country.weekLabel}</span>
            <ChevronDown size={12} className="text-[var(--color-edify-muted)]" />
          </button>
        }
      />

        <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6 space-y-4">
          {/* Country rollup card */}
          <section className="card p-3.5 space-y-3 border-[var(--color-edify-primary)]/30 bg-[var(--color-edify-soft)]/30">
            <header className="flex items-baseline justify-between gap-2 flex-wrap">
              <h2 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
                <Globe size={14} className="text-[var(--color-edify-primary)]" />
                Country Weekly Field Intelligence Report
              </h2>
              <div className="flex items-center gap-2 flex-wrap">
                <span className={cn("inline-flex items-center px-2.5 py-[3px] rounded-md text-[11px] font-extrabold whitespace-nowrap bg-emerald-100 text-emerald-700")}>
                  {country.status}
                </span>
                <ActionButton
                  icon="Download"
                  label="Download PDF"
                  className="h-8 px-2.5 rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] font-extrabold"
                  toast={{
                    tone: "info",
                    title: "Generating PDF…",
                    body: "Country weekly field intelligence report will download shortly.",
                  }}
                />
              </div>
            </header>

            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
              <Stat label="PL reports"             value={`${country.submittedProgramLeadReports}/${country.totalProgramLeadReports}`} />
              <Stat label="Country planned"        value={country.countryPlannedActivities} />
              <Stat label="Country completed"      value={country.countryCompletedActivities} tone="green" />
              <Stat label="Raw achievement"        value={`${country.countryRawAchievementPercent}%`} />
              <Stat label="Context-adjusted"       value={`${country.countryContextAdjustedAchievementPercent}%`} tone="green" />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3">
                <div className="text-[10px] font-bold uppercase tracking-wide muted mb-1.5 inline-flex items-center gap-1.5">
                  <AlertTriangle size={11} className="text-amber-600" /> Top country barriers
                </div>
                <ul className="space-y-1">
                  {country.topCountryBarriers.map((b, i) => (
                    <li key={i} className="text-[12px] flex items-baseline justify-between gap-2">
                      <span>· {b.category} <span className="muted text-caption">({b.regions.join(", ")})</span></span>
                      <span className="font-extrabold tabular">{b.count}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-3">
                <div className="text-[10px] font-bold uppercase tracking-wide text-rose-800 mb-1.5 inline-flex items-center gap-1.5">
                  <Sparkles size={11} /> Country decisions required
                </div>
                <ul className="space-y-1">
                  {country.decisionsRequired.map((d, i) => (
                    <li key={i} className="text-[12px] text-rose-900 leading-snug">· {d}</li>
                  ))}
                </ul>
              </div>
            </div>
          </section>

          {/* Per-PL reports */}
          <section className="card p-3.5 space-y-3">
            <header className="flex items-baseline justify-between gap-2 flex-wrap">
              <h2 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
                <FileText size={14} className="text-[var(--color-edify-primary)]" />
                Program Lead Weekly Field Reports
              </h2>
              <div className="text-caption muted">
                {reports.length} reports · <span className="font-extrabold text-rose-700">{totalDecisions}</span> decision{totalDecisions === 1 ? "" : "s"} awaiting you
              </div>
            </header>

            <ul className="space-y-2">
              {reports.map((r) => {
                const decisions = r.decisionsRequiredFromCD.length;
                const late      = isReportLate(r.submittedAt, r.weekEnd);
                return (
                  <li key={r.id} className={cn(
                    "rounded-xl border bg-white p-4",
                    late ? "border-amber-300 ring-1 ring-amber-200" : "border-[var(--color-edify-border)]",
                  )}>
                    <div className="flex items-start justify-between gap-3 flex-wrap">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-baseline gap-2 flex-wrap">
                          <div className="text-body-lg font-extrabold tracking-tight">{r.programLeadName}</div>
                          <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", STATUS_TONE[r.status])}>
                            {r.status}
                          </span>
                          {decisions > 0 && (
                            <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-rose-100 text-rose-700 whitespace-nowrap">
                              <Sparkles size={9} />
                              {decisions} decision{decisions === 1 ? "" : "s"}
                            </span>
                          )}
                          {late && (
                            <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold bg-amber-100 text-amber-800 whitespace-nowrap" title="Submitted after Saturday EOD SLA">
                              <AlertTriangle size={9} />
                              Late submission
                            </span>
                          )}
                        </div>
                        <div className="text-[11.5px] muted mt-0.5">
                          {r.team} · {r.region} · Debriefs <span className="font-extrabold text-[var(--color-edify-text)]">{r.submittedDebriefs}/{r.expectedDebriefs}</span> ({r.debriefSubmissionRate}%) · Raw <span className="font-extrabold text-[var(--color-edify-text)]">{r.rawAchievementPercent}%</span> · Adjusted <span className="font-extrabold text-emerald-700">{r.contextAdjustedAchievementPercent}%</span>
                        </div>
                        {r.topBarriers[0] && (
                          <div className="text-[11.5px] muted mt-1">
                            Top barrier:{" "}
                            <span className="font-extrabold text-amber-800">{r.topBarriers[0].category}</span>
                            <span className="text-caption"> — {r.topBarriers[0].recommendedAction}</span>
                          </div>
                        )}
                      </div>
                      <div className="flex items-center gap-2 flex-wrap shrink-0">
                        <Link
                          href={`/dashboards/director/weekly-debrief-reports/${r.id}`}
                          className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white inline-flex items-center gap-1.5 text-[12px] font-extrabold hover:brightness-110"
                        >
                          View report <ChevronRight size={11} />
                        </Link>
                        <a
                          href={r.downloadablePdfUrl ?? "#"}
                          className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] bg-white inline-flex items-center gap-1.5 text-[12px] font-extrabold"
                        >
                          <Download size={11} /> PDF
                        </a>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>

            <p className="text-caption muted leading-snug pt-2 border-t border-[var(--color-edify-border)]">
              Daily debriefs stay close to the field. Each Program Lead reviews their team daily; the system compiles this weekly report for your decisions — not for daily reading.
            </p>
          </section>
        </div>
      </>
  );
}

function Stat({ label, value, tone }: { label: string; value: number | string; tone?: "edify" | "green" }) {
  const tones = { edify: "bg-white border-[var(--color-edify-border)]", green: "bg-emerald-50 border-emerald-200" } as const;
  return (
    <div className={cn("rounded-xl border px-3 py-2", tones[tone ?? "edify"])}>
      <div className="text-[10px] muted font-bold uppercase tracking-wide truncate">{label}</div>
      <div className="text-[16px] font-extrabold tabular leading-tight">{value}</div>
    </div>
  );
}

// Weekly Field Debrief Reports — Country Director surface.
//
// Per visibility rule: the CD never sees raw daily CCEO debriefs. Each row
// is one Program Lead's compiled Weekly Field Report. Columns mirror the
// product spec: PL · team · submission rate · raw % · context-adj % · top
// barrier · status · View / Download.

import Link from "next/link";
import { FileText, AlertTriangle, ChevronRight, Download } from "lucide-react";
import { programLeadWeeklyFieldReports } from "@/lib/field-intelligence-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE: Record<string, string> = {
  "Generated":                "bg-slate-100   text-slate-700",
  "PL Editing":               "bg-amber-100   text-amber-700",
  "Submitted to CD":          "bg-emerald-100 text-emerald-700",
  "Returned for Clarification":"bg-rose-100   text-rose-700",
  "Resubmitted":              "bg-violet-100  text-violet-700",
  "Reviewed by CD":           "bg-sky-100     text-sky-700",
  "Closed":                   "bg-slate-100   text-slate-500",
};

export function WeeklyDebriefReportsCard() {
  const reports = programLeadWeeklyFieldReports;
  const totalSubmitted = reports.filter((r) => r.status !== "Generated" && r.status !== "PL Editing").length;

  return (
    <section className="card p-3.5 space-y-3">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <h3 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-2">
            <FileText size={14} className="text-[var(--color-edify-primary)]" />
            Weekly Field Debrief Reports
          </h3>
          <p className="text-caption muted mt-0.5">
            One report per Program Lead. Daily debriefs roll up here — you decide, not journal.
          </p>
        </div>
        <Link
          href="/dashboards/director/weekly-debrief-reports"
          className="text-[11px] font-extrabold text-[var(--color-edify-primary)] inline-flex items-center gap-1 hover:underline"
        >
          Open report center <ChevronRight size={11} />
        </Link>
      </header>

      <div className="text-caption muted">
        {totalSubmitted}/{reports.length} Program Lead reports submitted · Week {reports[0]?.weekLabel ?? ""}
      </div>

      <div className="overflow-x-auto -mx-2 px-2">
        <table className="w-full text-[12px] min-w-[760px]">
          <thead>
            <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
              <th scope="col" className="py-2 pr-2">Program Lead</th>
              <th scope="col" className="py-2 px-2">Debriefs</th>
              <th scope="col" className="py-2 px-2 text-right">Raw</th>
              <th scope="col" className="py-2 px-2 text-right">Adjusted</th>
              <th scope="col" className="py-2 px-2">Top barrier</th>
              <th scope="col" className="py-2 px-2 text-right">Decisions</th>
              <th scope="col" className="py-2 px-2">Status</th>
              <th scope="col" className="py-2 pl-2 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-edify-border)]">
            {reports.map((r) => (
              <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/30">
                <td className="py-2.5 pr-2">
                  <div className="font-extrabold tracking-tight truncate">{r.programLeadName}</div>
                  <div className="text-caption muted truncate">{r.team} · {r.region}</div>
                </td>
                <td className="py-2.5 px-2 tabular whitespace-nowrap">
                  {r.submittedDebriefs}/{r.expectedDebriefs}
                  <span className="text-caption muted ml-1">({r.debriefSubmissionRate}%)</span>
                </td>
                <td className="py-2.5 px-2 text-right font-extrabold tabular">{r.rawAchievementPercent}%</td>
                <td className="py-2.5 px-2 text-right font-extrabold tabular text-emerald-700">{r.contextAdjustedAchievementPercent}%</td>
                <td className="py-2.5 px-2">
                  {r.topBarriers[0] ? (
                    <span className="inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-caption font-extrabold bg-amber-100 text-amber-800 whitespace-nowrap">
                      <AlertTriangle size={9} />
                      {r.topBarriers[0].category}
                    </span>
                  ) : <span className="muted text-caption">—</span>}
                </td>
                <td className="py-2.5 px-2 text-right font-extrabold tabular">{r.decisionsRequiredFromCD.length}</td>
                <td className="py-2.5 px-2">
                  <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap", STATUS_TONE[r.status] ?? "bg-slate-100 text-slate-700")}>
                    {r.status}
                  </span>
                </td>
                <td className="py-2.5 pl-2 text-right whitespace-nowrap">
                  <Link
                    href={`/dashboards/director/weekly-debrief-reports/${r.id}`}
                    className="text-[11px] font-extrabold text-[var(--color-edify-primary)] hover:underline"
                  >
                    View report
                  </Link>
                  <a
                    href={r.downloadablePdfUrl ?? "#"}
                    className="ml-2 inline-flex items-center gap-1 text-caption font-extrabold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"
                    aria-label={`Download ${r.programLeadName} report PDF`}
                  >
                    <Download size={11} /> PDF
                  </a>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-caption muted leading-snug pt-2 border-t border-[var(--color-edify-border)]">
        Country Weekly Field Intelligence Report aggregates all PL reports — open it from the report center to share with the RVP.
      </div>
    </section>
  );
}

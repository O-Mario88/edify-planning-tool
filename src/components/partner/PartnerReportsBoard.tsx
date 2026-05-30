"use client";

// PartnerReportsBoard — two stacked cards:
//   1. Pending submissions — what's due this week, with a CTA
//   2. Reports library — past submissions, downloadable
//
// Reports are the partner's structured narrative to leadership. The
// data shape is intentionally simple — title, period, status, download.

import { FileText, Download, ArrowRight, AlertTriangle, CheckCircle2, Calendar } from "lucide-react";
import { cn } from "@/lib/utils";

type ReportStatus = "Draft" | "Due" | "Submitted" | "Approved";

type ReportRow = {
  id: string;
  title: string;
  period: string;
  type: "Weekly" | "Monthly" | "Quarterly" | "Special";
  status: ReportStatus;
  submittedOn?: string;
  dueOn?: string;
};

const PENDING: ReportRow[] = [
  { id: "R-P1", title: "Weekly Partner Update — Wk 22", period: "May 12 - May 18, 2026", type: "Weekly",  status: "Due",   dueOn: "Mon, May 19" },
  { id: "R-P2", title: "Monthly Impact Summary — May",  period: "May 2026",              type: "Monthly", status: "Draft", dueOn: "Fri, May 31" },
];

const LIBRARY: ReportRow[] = [
  { id: "R1", title: "Weekly Partner Update — Wk 21",    period: "May 5 - May 11, 2026",  type: "Weekly",    status: "Approved",  submittedOn: "May 12, 2026" },
  { id: "R2", title: "Weekly Partner Update — Wk 20",    period: "Apr 28 - May 4, 2026",  type: "Weekly",    status: "Approved",  submittedOn: "May 05, 2026" },
  { id: "R3", title: "Monthly Impact Summary — April",   period: "April 2026",            type: "Monthly",   status: "Approved",  submittedOn: "May 02, 2026" },
  { id: "R4", title: "Q1 Performance Review",            period: "Jan - Mar 2026",        type: "Quarterly", status: "Approved",  submittedOn: "Apr 10, 2026" },
  { id: "R5", title: "Special Report — Maple Grove Incident", period: "Mar 28, 2026",     type: "Special",   status: "Submitted", submittedOn: "Mar 31, 2026" },
  { id: "R6", title: "Weekly Partner Update — Wk 19",    period: "Apr 21 - Apr 27, 2026", type: "Weekly",    status: "Approved",  submittedOn: "Apr 28, 2026" },
  { id: "R7", title: "Monthly Impact Summary — March",   period: "March 2026",            type: "Monthly",   status: "Approved",  submittedOn: "Apr 02, 2026" },
];

const STATUS_TONE: Record<ReportStatus, string> = {
  "Draft":     "bg-amber-50 text-amber-700",
  "Due":       "bg-rose-50 text-rose-700",
  "Submitted": "bg-blue-50 text-blue-700",
  "Approved":  "bg-emerald-50 text-emerald-700",
};

const TYPE_TONE: Record<ReportRow["type"], string> = {
  "Weekly":     "bg-slate-100 text-slate-700",
  "Monthly":    "bg-violet-50 text-violet-700",
  "Quarterly":  "bg-amber-50 text-amber-700",
  "Special":    "bg-rose-50 text-rose-700",
};

export function PartnerReportsBoard() {
  return (
    <div className="space-y-4">
      {/* Pending — calls to action */}
      <section className="card p-3.5">
        <header className="flex items-start justify-between gap-3 mb-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="grid place-items-center h-7 w-7 rounded-md bg-amber-100 text-amber-700">
                <AlertTriangle size={14} />
              </span>
              <h3 className="text-[15px] font-extrabold tracking-tight">Pending submissions</h3>
            </div>
            <p className="text-[12px] muted mt-1">
              Reports waiting on you. Submit on time to keep your on-time rate clean.
            </p>
          </div>
          <span className="text-caption uppercase tracking-wide font-bold text-amber-700">
            {PENDING.length} pending
          </span>
        </header>
        <ul className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
          {PENDING.map((r) => (
            <li key={r.id} className="rounded-xl border border-amber-200 bg-amber-50/40 p-3.5">
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide", TYPE_TONE[r.type])}>
                  {r.type}
                </span>
                <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide", STATUS_TONE[r.status])}>
                  {r.status}
                </span>
              </div>
              <h4 className="text-[13.5px] font-extrabold tracking-tight">{r.title}</h4>
              <p className="text-[11px] muted leading-tight mt-0.5 inline-flex items-center gap-1">
                <Calendar size={10} /> {r.period}
              </p>
              <div className="mt-3 flex items-center justify-between gap-2">
                <span className="text-caption muted font-bold">
                  Due {r.dueOn}
                </span>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-amber-500 text-white text-[11.5px] font-extrabold hover:bg-amber-600"
                >
                  {r.status === "Draft" ? "Continue draft" : "Submit report"} <ArrowRight size={11} />
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {/* Library — past submissions */}
      <section className="card p-3.5">
        <header className="flex items-start justify-between gap-3 mb-3">
          <div>
            <div className="flex items-center gap-2">
              <span className="grid place-items-center h-7 w-7 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
                <FileText size={14} />
              </span>
              <h3 className="text-[15px] font-extrabold tracking-tight">Reports library</h3>
            </div>
            <p className="text-[12px] muted mt-1">
              Past submissions, downloadable. All reports shared with Edify leadership are listed here.
            </p>
          </div>
        </header>
        <div className="overflow-auto scrollbar -mx-1 px-1 max-h-[480px] rounded-md">
          <table className="w-full dtable">
            <thead className="sticky top-0 z-10 bg-white">
              <tr>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Report</th>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Type</th>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Period</th>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Submitted</th>
                <th className="text-left text-[10px] uppercase tracking-wide font-bold muted">Status</th>
                <th className="text-right text-[10px] uppercase tracking-wide font-bold muted">Action</th>
              </tr>
            </thead>
            <tbody>
              {LIBRARY.map((r) => (
                <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/40 transition-colors">
                  <td className="text-body font-semibold">{r.title}</td>
                  <td>
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide", TYPE_TONE[r.type])}>
                      {r.type}
                    </span>
                  </td>
                  <td className="text-[11.5px] muted">{r.period}</td>
                  <td className="text-[11.5px] muted">{r.submittedOn ?? "—"}</td>
                  <td>
                    <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold uppercase tracking-wide", STATUS_TONE[r.status])}>
                      {r.status === "Approved" && <CheckCircle2 size={10} className="mr-0.5" />}
                      {r.status}
                    </span>
                  </td>
                  <td className="text-right">
                    <button
                      type="button"
                      className="inline-flex items-center gap-1 h-8 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[11.5px] font-semibold hover:bg-[var(--color-edify-soft)]/60"
                    >
                      <Download size={11} /> Download
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

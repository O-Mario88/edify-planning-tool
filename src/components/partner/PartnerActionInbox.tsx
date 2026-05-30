"use client";

// PartnerActionInbox — the master list of every assigned activity, in
// one place, sortable through a strip of status tabs. The active tab
// drives which rows render. Each row shows the activity, school,
// district, due date, facilitator, three status chips (evidence /
// report / verification), and a context-aware action button.

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type {
  PartnerInboxRow,
  PartnerInboxTab,
  PartnerInboxTabKey,
  EvidenceStatus,
  ReportStatus,
  VerificationStatus,
  PartnerPriority,
  ActionLabel,
} from "@/lib/partner/partner-dashboard-mock";
import { PartnerScheduleDrawer, type ScheduleOutcome } from "@/components/partner/PartnerScheduleDrawer";

const PRIORITY_TONE: Record<PartnerPriority, { dot: string; text: string }> = {
  High:   { dot: "bg-rose-500",   text: "text-rose-700"  },
  Medium: { dot: "bg-amber-500",  text: "text-amber-700" },
  Low:    { dot: "bg-emerald-500", text: "text-emerald-700" },
};

const EVIDENCE_PILL: Record<EvidenceStatus, string> = {
  Missing:   "bg-rose-50 text-rose-700",
  Complete:  "bg-emerald-50 text-emerald-700",
  Submitted: "bg-emerald-50 text-emerald-700",
};

const REPORT_PILL: Record<ReportStatus, string> = {
  "Not Submitted": "bg-rose-50 text-rose-700",
  "Draft":         "bg-amber-50 text-amber-700",
  "Returned":      "bg-amber-50 text-amber-700",
  "Submitted":     "bg-blue-50 text-blue-700",
};

const VERIFICATION_PILL: Record<VerificationStatus, string> = {
  "Not Started":   "bg-slate-100 text-slate-600",
  "Returned":      "bg-amber-50 text-amber-700",
  "Edify Review":  "bg-blue-50 text-blue-700",
  "M&E Verified":  "bg-emerald-50 text-emerald-700",
};

const ACTION_STYLE: Record<ActionLabel, string> = {
  "Schedule Activity": "bg-emerald-500 text-white hover:bg-emerald-600",
  "Upload Evidence":  "bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]",
  "Start Visit":      "bg-[var(--color-edify-primary)] text-white hover:bg-[var(--color-edify-dark)]",
  "Correct Report":   "bg-amber-500 text-white hover:bg-amber-600",
  "View Status":      "border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
  "View Details":     "border border-[var(--color-edify-border)] bg-white text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
};

export function PartnerActionInbox({
  tabs,
  rows,
}: {
  tabs: PartnerInboxTab[];
  rows: PartnerInboxRow[];
}) {
  const [active, setActive] = useState<PartnerInboxTabKey>("assigned");
  const [scheduling, setScheduling] = useState<PartnerInboxRow | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [lastActive, setLastActive] = useState(active);

  // Pagination — 10 rows per page is the right density for a card
  // this size: dense enough that you can see the spread, sparse
  // enough that each row breathes. Tab change resets to page 0 so
  // the user never lands on an empty page. We adjust state during
  // render (the React 19 idiom for "prop/state-derived reset")
  // rather than using a useEffect.
  const PAGE_SIZE = 10;
  if (active !== lastActive) {
    setLastActive(active);
    setPage(0);
  }

  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const pageStart = safePage * PAGE_SIZE;
  const pageEnd = Math.min(pageStart + PAGE_SIZE, rows.length);
  const pageRows = useMemo(() => rows.slice(pageStart, pageEnd), [rows, pageStart, pageEnd]);
  const pageList = buildPageList(safePage, totalPages);

  function handleRowAction(row: PartnerInboxRow) {
    if (row.actionLabel === "Schedule Activity") {
      setScheduling(row);
    }
  }

  function handleScheduleSubmit(outcome: ScheduleOutcome) {
    if (outcome.kind === "scheduled") {
      setToast(`Scheduled — your CCEO now sees this in their monitoring queue.`);
    } else if (outcome.kind === "request_change") {
      setToast(`Date-change request sent to your CCEO.`);
    } else {
      setToast(`Returned to CCEO for reassignment.`);
    }
    setTimeout(() => setToast(null), 4000);
  }

  return (
    <section className="card p-3.5">
      <div className="mb-3">
        <h3 className="text-[15px] font-extrabold tracking-tight">Partner Action Inbox</h3>
        <p className="text-[12px] muted mt-0.5">All your partner actions and requests in one place.</p>
      </div>

      {/* Tab strip — phone uses a native select so all tabs are one
          tap away instead of buried in a horizontal scroller; tablet+
          keeps the pill row. */}
      <div className="md:hidden mb-2">
        <label className="block relative">
          <span className="sr-only">Inbox filter</span>
          <select
            value={active}
            onChange={(e) => setActive(e.target.value as typeof active)}
            className="w-full h-10 pl-3 pr-9 rounded-lg bg-[var(--color-edify-soft)] border border-[var(--color-edify-border)] text-body font-extrabold text-[var(--color-edify-text)] appearance-none focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          >
            {tabs.map((t) => (
              <option key={t.key} value={t.key}>
                {t.label}{t.count > 0 ? ` (${t.count})` : ""}
              </option>
            ))}
          </select>
          <svg className="absolute right-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)] pointer-events-none" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </label>
      </div>
      <div className="hidden md:flex items-center gap-1 overflow-x-auto scrollbar -mx-1 px-1 pb-1.5 border-b border-[var(--color-edify-divider)]">
        {tabs.map((t) => {
          const isActive = active === t.key;
          return (
            <button
              key={t.key}
              type="button"
              onClick={() => setActive(t.key)}
              className={cn(
                "inline-flex items-center gap-1.5 h-8 px-3 rounded-md text-[11.5px] font-semibold whitespace-nowrap transition-colors",
                isActive
                  ? "bg-[var(--color-edify-soft)] text-[var(--color-edify-text)] border border-[var(--color-edify-border)]"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/50",
              )}
            >
              {t.label}
              {t.count > 0 && (
                <span
                  className={cn(
                    "inline-flex items-center justify-center min-w-[18px] h-[16px] px-1 rounded-md text-[9.5px] font-extrabold",
                    isActive ? "bg-[var(--color-edify-primary)] text-white" : "bg-slate-100 text-slate-700",
                  )}
                >
                  {t.count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Table — pagination (not scroll) so every assigned school
          is reachable. Card sizes naturally to its 10 rows. Wide
          columns scroll horizontally inside the card on narrow
          viewports without capping height. */}
      <div className="overflow-x-auto scrollbar -mx-1 px-1 mt-3 rounded-md">
        <table className="w-full dtable">
          <thead className="bg-white">
            <tr>
              <th className="text-left text-[11px] font-semibold muted">Priority</th>
              <th className="text-left text-[11px] font-semibold muted">Activity</th>
              <th className="text-left text-[11px] font-semibold muted">School</th>
              <th className="text-left text-[11px] font-semibold muted">District</th>
              <th className="text-left text-[11px] font-semibold muted">Due Date</th>
              <th className="text-left text-[11px] font-semibold muted">Facilitator</th>
              <th className="text-left text-[11px] font-semibold muted">Evidence</th>
              <th className="text-left text-[11px] font-semibold muted">Report</th>
              <th className="text-left text-[11px] font-semibold muted">Verification</th>
              <th className="text-right text-[11px] font-semibold muted">Action</th>
            </tr>
          </thead>
          <tbody>
            {pageRows.map((r) => {
              const p = PRIORITY_TONE[r.priority];
              return (
                <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/40 transition-colors">
                  <td>
                    <span className={cn("inline-flex items-center gap-1.5 text-[12px] font-semibold", p.text)}>
                      <span className={cn("w-1.5 h-1.5 rounded-full", p.dot)} />
                      {r.priority}
                    </span>
                  </td>
                  <td>
                    <div className="text-body font-semibold leading-tight">{r.activity}</div>
                    <div className="text-[11px] muted leading-tight mt-0.5">{r.activitySub}</div>
                  </td>
                  <td className="text-[12px]">{r.school}</td>
                  <td className="text-[12px] muted">{r.district}</td>
                  <td>
                    <div className="text-[12px] font-semibold leading-tight whitespace-nowrap">{r.dueDateLabel}</div>
                    <div className="text-caption muted leading-tight mt-0.5 whitespace-nowrap">{r.dueDateSub}</div>
                  </td>
                  <td className="text-[12px]">{r.facilitator}</td>
                  <td>
                    <Pill cls={EVIDENCE_PILL[r.evidence]}>{r.evidence}</Pill>
                  </td>
                  <td>
                    <Pill cls={REPORT_PILL[r.report]}>{r.report}</Pill>
                  </td>
                  <td>
                    <Pill cls={VERIFICATION_PILL[r.verification]}>{r.verification}</Pill>
                  </td>
                  <td className="text-right">
                    <button
                      type="button"
                      onClick={() => handleRowAction(r)}
                      className={cn(
                        // Resized: was h-8 / text-[11.5px] / extrabold —
                        // too heavy next to a 12px row body. Premium
                        // row-buttons are smaller + semibold so the
                        // row's data still reads first.
                        "inline-flex items-center justify-center h-7 px-2.5 rounded-md text-caption font-semibold transition-colors whitespace-nowrap",
                        ACTION_STYLE[r.actionLabel],
                      )}
                    >
                      {r.actionLabel}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer — pagination. Page numbers + Prev/Next so every
          assigned school is reachable from this single card. */}
      <div className="mt-3 pt-3 border-t border-[#eef2f4] flex items-center justify-between gap-3 flex-wrap">
        <div className="text-[12px] muted">
          Showing <span className="font-semibold text-[var(--color-edify-text)]">{rows.length === 0 ? 0 : pageStart + 1}–{pageEnd}</span>{" "}
          of <span className="font-semibold text-[var(--color-edify-text)]">{rows.length}</span>{" "}
          activities across {tabs.find((t) => t.key === "completed")?.count != null ? "all your assigned schools" : "your portfolio"}
        </div>
        {totalPages > 1 && (
          <div className="flex items-center gap-1">
            <button
              type="button"
              aria-label="Previous page"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={safePage === 0}
              className={cn(
                "h-8 w-8 grid place-items-center rounded-md border border-[var(--color-edify-border)] bg-white transition-colors",
                safePage === 0
                  ? "text-[var(--color-edify-muted)]/60 cursor-not-allowed"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/60",
              )}
            >
              <ChevronLeft size={13} />
            </button>
            {pageList.map((p, i) => {
              const isEllipsis = p === "…";
              const isActive = p === safePage;
              return (
                <button
                  key={`${p}-${i}`}
                  type="button"
                  disabled={isEllipsis}
                  onClick={() => !isEllipsis && setPage(p as number)}
                  className={cn(
                    "h-8 min-w-8 px-2 rounded-md text-[12px] font-semibold transition-colors border",
                    isActive
                      ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)] shadow-sm"
                      : isEllipsis
                        ? "border-transparent text-[var(--color-edify-muted)] cursor-default"
                        : "bg-white border-[var(--color-edify-border)] text-[var(--color-edify-text)] hover:bg-[var(--color-edify-soft)]/60",
                  )}
                >
                  {isEllipsis ? "…" : (p as number) + 1}
                </button>
              );
            })}
            <button
              type="button"
              aria-label="Next page"
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={safePage >= totalPages - 1}
              className={cn(
                "h-8 w-8 grid place-items-center rounded-md border border-[var(--color-edify-border)] bg-white transition-colors",
                safePage >= totalPages - 1
                  ? "text-[var(--color-edify-muted)]/60 cursor-not-allowed"
                  : "text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/60",
              )}
            >
              <ChevronRight size={13} />
            </button>
          </div>
        )}
      </div>

      {/* Schedule drawer */}
      <PartnerScheduleDrawer
        open={!!scheduling}
        activityLabel={scheduling ? `${scheduling.activity} — ${scheduling.activitySub}` : ""}
        schoolName={scheduling?.school ?? ""}
        urgency={scheduling?.priority === "High" ? "High" : scheduling?.priority === "Medium" ? "Medium" : "Low"}
        onClose={() => setScheduling(null)}
        onSubmit={handleScheduleSubmit}
      />

      {/* Toast — confirms transitions to the partner. */}
      {toast && (
        <div className="fixed bottom-6 right-6 z-50 rounded-xl shadow-lg bg-emerald-600 text-white text-body font-semibold px-4 py-3 max-w-[360px]">
          {toast}
        </div>
      )}
    </section>
  );
}

function Pill({ cls, children }: { cls: string; children: React.ReactNode }) {
  // Premium status chip. Previously `text-caption font-bold` —
  // looked like a headline next to the 12px row body. Title case +
  // tiny + semibold keeps the chip readable in narrow columns
  // (avoids "NOT SUBM…" truncation) while still letting status
  // colour do the work.
  return (
    <span className={cn("inline-flex items-center h-[20px] px-1.5 rounded-md text-caption font-semibold whitespace-nowrap", cls)}>
      {children}
    </span>
  );
}

// Page-number list with ellipses for long sequences. Matches the
// pattern used in the planning + funds queues.
function buildPageList(current: number, total: number): (number | "…")[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i);
  const pages: (number | "…")[] = [0];
  if (current > 2) pages.push("…");
  const start = Math.max(1, current - 1);
  const end = Math.min(total - 2, current + 1);
  for (let i = start; i <= end; i++) pages.push(i);
  if (current < total - 3) pages.push("…");
  pages.push(total - 1);
  return pages;
}

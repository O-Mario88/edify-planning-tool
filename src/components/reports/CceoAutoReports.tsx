"use client";

// CceoAutoReports — the CCEO view of /reports (spec §21).
//
// Seven auto-generated reports assembled from the records the CCEO already
// produces (plans, completions, evidence, SSA, partner work, cluster
// meetings, targets) — the CCEO never writes a report by hand. Each card
// shows: what feeds it (auto-generated-from line), freshness, a key-numbers
// preview, and View (inline expandable detail) / Export (CSV of the
// assembled numbers; print view linked where an existing one fits).

import { useState } from "react";
import Link from "next/link";
import {
  CalendarRange,
  ChevronDown,
  ExternalLink,
  FileText,
  GraduationCap,
  Handshake,
  Network,
  Printer,
  School,
  ShieldCheck,
  Target,
  type LucideIcon,
} from "lucide-react";
import { cceoAutoReports, type CceoAutoReport } from "@/lib/reports-types";
import { ExportButton } from "@/components/ui/ExportButton";
import { cn } from "@/lib/utils";

const REPORT_ICON: Record<string, { Icon: LucideIcon; bg: string; text: string }> = {
  "weekly-update":              { Icon: CalendarRange, bg: "bg-sky-100",     text: "text-sky-700"     },
  "monthly-update":             { Icon: FileText,      bg: "bg-violet-100",  text: "text-violet-700"  },
  "core-school-report":         { Icon: School,        bg: "bg-emerald-100", text: "text-emerald-700" },
  "partner-work-summary":       { Icon: Handshake,     bg: "bg-amber-100",   text: "text-amber-700"   },
  "cluster-fellowship-report":  { Icon: Network,       bg: "bg-indigo-100",  text: "text-indigo-700"  },
  "ssa-improvement-summary":    { Icon: ShieldCheck,   bg: "bg-rose-100",    text: "text-rose-700"    },
  "target-progress-report":     { Icon: Target,        bg: "bg-yellow-100",  text: "text-yellow-700"  },
};

function exportRows(r: CceoAutoReport): Record<string, unknown>[] {
  return [
    ...r.keyNumbers.map((k) => ({ Report: r.title, Section: "Key numbers", Item: k.label, Detail: k.value })),
    ...r.sections.flatMap((s) => s.lines.map((line) => ({ Report: r.title, Section: s.heading, Item: "", Detail: line }))),
  ];
}

export function CceoAutoReports() {
  const [openId, setOpenId] = useState<string | null>(null);

  return (
    <section className="space-y-3">
      <div className="card px-3.5 py-2.5 flex items-center gap-2.5">
        <span className="h-8 w-8 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0">
          <GraduationCap size={14} />
        </span>
        <p className="text-[11.5px] muted leading-snug">
          These reports write themselves from your workflow records — plans, completions, evidence,
          SSA uploads, partner work, cluster meetings and targets. Nothing here is typed up by hand.
        </p>
      </div>

      {cceoAutoReports.length === 0 && (
        <div className="card p-6 text-center">
          <p className="text-[12px] muted leading-snug">
            Auto-generated reports will appear here once you have field activity to summarise — plans,
            completed visits, evidence, SSA uploads, partner work, cluster meetings and target progress.
            Reports assemble themselves from those records.
          </p>
        </div>
      )}

      <div className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        {cceoAutoReports.map((r) => {
          const visual = REPORT_ICON[r.id] ?? { Icon: FileText, bg: "bg-[var(--color-edify-soft)]", text: "text-[var(--color-edify-primary)]" };
          const open = openId === r.id;
          return (
            <article
              key={r.id}
              className={cn(
                "card p-3.5 col-span-12 md:col-span-6 xl:col-span-4 transition-colors",
                open && "ring-1 ring-[var(--color-edify-primary)]/20",
              )}
            >
              <header className="flex items-start gap-3">
                <span className={cn("h-10 w-10 rounded-xl grid place-items-center shrink-0", visual.bg, visual.text)}>
                  <visual.Icon size={18} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2">
                    <h2 className="text-body-lg font-extrabold tracking-tight truncate">{r.title}</h2>
                    <span className="inline-flex items-center px-1.5 py-[2px] rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] text-[10px] font-extrabold whitespace-nowrap shrink-0">
                      {r.cadence}
                    </span>
                  </div>
                  <p className="text-[11.5px] muted leading-snug mt-0.5">{r.description}</p>
                </div>
              </header>

              {/* Auto-generated-from + freshness */}
              <div className="mt-2.5 space-y-1">
                <p className="text-[10.5px] leading-snug">
                  <span className="font-bold uppercase tracking-wide text-[10px] muted">Auto-generated from</span>{" "}
                  <span className="text-[var(--text-secondary)]">{r.generatedFrom.join(" · ")}</span>
                </p>
                <p className="text-[10.5px] muted tabular">{r.freshness}</p>
              </div>

              {/* Key numbers preview */}
              <dl className="mt-2.5 grid grid-cols-2 gap-x-3 gap-y-1.5">
                {r.keyNumbers.map((k) => (
                  <div key={k.label} className="min-w-0">
                    <dt className="text-[10px] muted font-bold uppercase tracking-wide truncate">{k.label}</dt>
                    <dd className="text-[14px] font-extrabold tabular tracking-tight">{k.value}</dd>
                  </div>
                ))}
              </dl>

              {/* Expandable detail */}
              {open && (
                <div className="mt-3 pt-3 border-t border-[var(--color-edify-divider)] space-y-2.5">
                  {r.sections.map((s) => (
                    <div key={s.heading}>
                      <h3 className="text-[10px] uppercase tracking-wide muted font-bold mb-1">{s.heading}</h3>
                      <ul className="space-y-1">
                        {s.lines.map((line) => (
                          <li key={line} className="flex items-start gap-2 text-[11.5px] leading-snug">
                            <span className="mt-[5px] h-1 w-1 rounded-full bg-[var(--color-edify-primary)] shrink-0" />
                            <span>{line}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ))}
                  <Link
                    href={r.liveHref}
                    className="inline-flex items-center gap-1 text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline"
                  >
                    Open the live data
                    <ExternalLink size={10} />
                  </Link>
                </div>
              )}

              {/* Actions */}
              <footer className="mt-3 pt-2.5 border-t border-[var(--color-edify-divider)] flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => setOpenId(open ? null : r.id)}
                  aria-expanded={open}
                  className="h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] text-[11.5px] font-semibold inline-flex items-center gap-1 hover:bg-[var(--color-edify-soft)]/50"
                >
                  <ChevronDown size={12} className={cn("transition-transform", open && "rotate-180")} />
                  {open ? "Hide detail" : "View"}
                </button>
                <ExportButton
                  rows={exportRows(r)}
                  filename={`cceo-${r.id}`}
                  label="Export"
                  className="!h-8 !px-2.5 !rounded-lg !text-[11.5px]"
                />
                {r.printHref && (
                  <Link
                    href={r.printHref}
                    target="_blank"
                    className="h-8 px-2.5 rounded-lg border border-[var(--color-edify-border)] text-[11.5px] font-semibold inline-flex items-center gap-1 hover:bg-[var(--color-edify-soft)]/50 ml-auto"
                  >
                    <Printer size={12} />
                    Print view
                  </Link>
                )}
              </footer>
            </article>
          );
        })}
      </div>
    </section>
  );
}

"use client";

import { useEffect, useState } from "react";
import { FileText, Loader2, Sparkles, ChevronDown } from "lucide-react";

// ReportsLive — generated, PERSISTED program reports straight from the backend.
// "Generate" computes a snapshot from live program data (school counts, activity
// pipeline, SSA averages) and stores it as a dated Report row. Renders nothing
// when the backend is off, so the page keeps its catalog cards.

type ReportRow = { id: string; title: string; type: string; fy: string; scope: string; createdAt: string };
type ReportFull = ReportRow & { summaryJson: Record<string, unknown> };

const GENERATORS: { type: string; label: string }[] = [
  { type: "program_summary", label: "Program Summary" },
  { type: "activity_pipeline", label: "Activity Pipeline" },
  { type: "ssa_performance", label: "SSA Performance" },
];

const TYPE_TONE: Record<string, string> = {
  program_summary: "bg-emerald-100 text-emerald-700",
  activity_pipeline: "bg-sky-100 text-sky-700",
  ssa_performance: "bg-violet-100 text-violet-700",
};

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function SummaryChips({ summary }: { summary: Record<string, unknown> }) {
  const entries: { k: string; v: string }[] = [];
  for (const [k, v] of Object.entries(summary)) {
    if (v == null) continue;
    if (Array.isArray(v)) {
      for (const item of v as Record<string, unknown>[]) {
        const label = (item.status ?? item.intervention ?? "") as string;
        const num = (item.count ?? item.average ?? item.n) as number | undefined;
        if (label) entries.push({ k: String(label).replace(/_/g, " "), v: num != null ? String(num) : "—" });
      }
    } else if (typeof v === "number" || typeof v === "string") {
      entries.push({ k: k.replace(/([A-Z])/g, " $1").replace(/_/g, " "), v: String(v) });
    }
  }
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {entries.map((e, i) => (
        <span key={`${e.k}-${i}`} className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md bg-[var(--color-edify-soft)]/60 text-[11px] font-semibold capitalize">
          {e.k} <span className="tabular font-extrabold text-[var(--color-edify-primary)]">{e.v}</span>
        </span>
      ))}
    </div>
  );
}

export function ReportsLive() {
  const [reports, setReports] = useState<ReportRow[]>([]);
  const [details, setDetails] = useState<Record<string, Record<string, unknown>>>({});
  const [open, setOpen] = useState<string | null>(null);
  const [live, setLive] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/reports")
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        setLive(!!d.live);
        if (d.live) setReports(d.reports ?? []);
      })
      .catch(() => !cancelled && setLive(false));
    return () => { cancelled = true; };
  }, []);

  async function generate(type: string) {
    setBusy(type);
    try {
      const res = await fetch("/api/reports", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ type, fy: "2026" }),
      });
      const d = await res.json();
      if (d.live && d.report) {
        const rep = d.report as ReportFull;
        setReports((prev) => [{ id: rep.id, title: rep.title, type: rep.type, fy: rep.fy, scope: rep.scope, createdAt: rep.createdAt }, ...prev]);
        setDetails((prev) => ({ ...prev, [rep.id]: rep.summaryJson }));
        setOpen(rep.id);
      }
    } finally {
      setBusy(null);
    }
  }

  async function toggle(id: string) {
    if (open === id) { setOpen(null); return; }
    setOpen(id);
    if (!details[id]) {
      const d = await fetch(`/api/reports/${id}`).then((r) => r.json()).catch(() => null);
      if (d?.live && d.report?.summaryJson) {
        setDetails((prev) => ({ ...prev, [id]: d.report.summaryJson }));
      }
    }
  }

  if (live === false) return null; // backend off → page keeps its catalog

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-3 flex-wrap">
        <div>
          <h2 className="text-body-lg font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Sparkles size={15} className="text-[var(--color-edify-primary)]" /> Generated reports
          </h2>
          <p className="text-[11.5px] muted">Snapshot live program data into a dated, persisted report.</p>
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>

      <div className="flex flex-wrap gap-2 mb-3">
        {GENERATORS.map((g) => (
          <button
            key={g.type}
            type="button"
            onClick={() => generate(g.type)}
            disabled={busy != null}
            className="h-9 px-3 rounded-xl border border-[var(--color-edify-border)] text-body font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60 disabled:opacity-50"
          >
            {busy === g.type ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
            Generate {g.label}
          </button>
        ))}
      </div>

      {reports.length === 0 ? (
        <p className="text-[12px] muted py-4 text-center">No reports generated yet — use a button above to snapshot the current numbers.</p>
      ) : (
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {reports.map((r) => (
            <li key={r.id} className="py-2.5">
              <button type="button" onClick={() => toggle(r.id)} className="w-full flex items-center gap-3 text-left">
                <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                  <FileText size={14} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-body font-extrabold tracking-tight truncate">{r.title}</div>
                  <div className="text-caption muted truncate">{fmtDate(r.createdAt)} · {r.scope}</div>
                </div>
                <span className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap capitalize ${TYPE_TONE[r.type] ?? "bg-[var(--color-edify-soft)]"}`}>
                  {r.type.replace(/_/g, " ")}
                </span>
                <ChevronDown size={14} className={`text-[var(--color-edify-muted)] shrink-0 transition-transform ${open === r.id ? "rotate-180" : ""}`} />
              </button>
              {open === r.id && details[r.id] && <SummaryChips summary={details[r.id]} />}
              {open === r.id && !details[r.id] && (
                <p className="text-[11px] muted mt-2">Open this report from the list to view its snapshot, or re-generate to see the detail inline.</p>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

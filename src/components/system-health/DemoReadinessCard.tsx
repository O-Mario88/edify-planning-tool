// Demo Readiness Score surface (spec layer #3). Server component — a single
// score with the band, the blockers to fix before the demo, and a per-check
// breakdown that says exactly where each gap is.

import Link from "next/link";
import { CheckCircle2, XCircle, AlertTriangle } from "lucide-react";
import { Pill, type PillTone } from "@/components/ui/Pill";
import { demoReadiness, type DemoReadinessBand, type DemoCheckCategory } from "@/lib/health/demo-readiness";
import { cn } from "@/lib/utils";

const BAND_TONE: Record<DemoReadinessBand, PillTone> = {
  "Ready": "success",
  "Nearly ready": "warning",
  "Not ready": "danger",
};

const BAND_BAR: Record<DemoReadinessBand, string> = {
  "Ready": "bg-emerald-500",
  "Nearly ready": "bg-amber-500",
  "Not ready": "bg-rose-500",
};

const CATEGORIES: DemoCheckCategory[] = ["Data", "Workflow", "Safety"];

export function DemoReadinessCard() {
  const r = demoReadiness();

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Demo Readiness</h2>
          <p className="text-xs text-slate-500">
            Can the contract demo run end-to-end right now? Scored from live data, workflow integrity, and production safety.
          </p>
        </div>
        <div className="text-right">
          <div className="text-3xl font-bold leading-none text-slate-900 dark:text-white">{r.score}%</div>
          <div className="mt-1">
            <Pill tone={BAND_TONE[r.band]} dot>{r.band}</Pill>
          </div>
        </div>
      </header>

      <div className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
        <div className={cn("h-full rounded-full transition-all", BAND_BAR[r.band])} style={{ width: `${r.score}%` }} />
      </div>
      <p className="mt-1 text-[11px] text-slate-400">{r.passed} of {r.total} checks passing.</p>

      {r.blockers.length > 0 && (
        <div className="mt-3 rounded-xl border border-rose-200 bg-rose-50/60 p-3 dark:border-rose-500/30 dark:bg-rose-500/5">
          <p className="flex items-center gap-1.5 text-xs font-semibold text-rose-700 dark:text-rose-300">
            <AlertTriangle size={13} /> Fix before demo
          </p>
          <ul className="mt-1.5 space-y-1">
            {r.blockers.map((b) => (
              <li key={b.id} className="flex items-center justify-between gap-3 text-xs">
                <span className="text-slate-600 dark:text-slate-300">{b.label} — <span className="text-slate-400">{b.detail}</span></span>
                {b.fixHref && (
                  <Link href={b.fixHref} className="shrink-0 font-medium text-rose-600 no-underline hover:underline">Fix →</Link>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {CATEGORIES.map((cat) => {
          const items = r.checks.filter((c) => c.category === cat);
          return (
            <div key={cat} className="rounded-xl border border-slate-200 p-3 dark:border-slate-800">
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-slate-400">{cat}</p>
              <ul className="space-y-1.5">
                {items.map((c) => (
                  <li key={c.id} className="flex items-start gap-1.5 text-xs">
                    {c.pass ? (
                      <CheckCircle2 size={13} className="mt-0.5 shrink-0 text-emerald-500" />
                    ) : (
                      <XCircle size={13} className="mt-0.5 shrink-0 text-rose-500" />
                    )}
                    <span className={cn("min-w-0", c.pass ? "text-slate-600 dark:text-slate-300" : "text-slate-700 dark:text-slate-200")}>
                      {c.fixHref && !c.pass ? (
                        <Link href={c.fixHref} className="no-underline hover:underline">{c.label}</Link>
                      ) : (
                        c.label
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}

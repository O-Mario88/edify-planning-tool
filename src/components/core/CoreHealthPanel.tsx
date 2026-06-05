// Core health panel — renders the integrity report (src/lib/core/core-health).
// Presentational; the engine does the checking. Used as a full panel on the
// health page and as a compact banner on the directory.

import Link from "next/link";
import { ShieldCheck, ShieldAlert, AlertTriangle, Info } from "lucide-react";
import { cn } from "@/lib/utils";
import type { CoreHealthReport, CoreHealthFinding } from "@/lib/core/core-health";

export function CoreHealthBanner({ report }: { report: CoreHealthReport }) {
  if (report.ok && report.warnings === 0) {
    return (
      <Link href="/core-schools/health" className="card px-3.5 py-2.5 flex items-center gap-2 hover:bg-[var(--color-edify-soft)]/30">
        <ShieldCheck size={16} className="text-emerald-600" />
        <span className="text-[12px] font-bold">Core data integrity: all {report.checkedPlans} plans · {report.checkedSlots} slots pass.</span>
      </Link>
    );
  }
  return (
    <Link href="/core-schools/health" className={cn("card px-3.5 py-2.5 flex items-center gap-2 hover:opacity-90", report.errors > 0 ? "border-l-4 border-l-rose-500" : "border-l-4 border-l-amber-500")}>
      <ShieldAlert size={16} className={report.errors > 0 ? "text-rose-600" : "text-amber-600"} />
      <span className="text-[12px] font-bold">
        {report.errors > 0 && <span className="text-rose-700">{report.errors} integrity {report.errors === 1 ? "error" : "errors"}</span>}
        {report.errors > 0 && report.warnings > 0 && " · "}
        {report.warnings > 0 && <span className="text-amber-700">{report.warnings} {report.warnings === 1 ? "warning" : "warnings"}</span>}
      </span>
      <span className="text-[11px] muted ml-auto">View health →</span>
    </Link>
  );
}

const ICON = { error: AlertTriangle, warning: AlertTriangle, info: Info } as const;
const TONE = { error: "text-rose-600", warning: "text-amber-600", info: "text-sky-600" } as const;

export function CoreHealthPanel({ report }: { report: CoreHealthReport }) {
  const groups: { sev: CoreHealthFinding["severity"]; items: CoreHealthFinding[] }[] = (["error", "warning", "info"] as const)
    .map((sev) => ({ sev, items: report.findings.filter((f) => f.severity === sev) }))
    .filter((g) => g.items.length > 0);

  return (
    <div className="space-y-3">
      <section className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <Stat label="Plans checked" value={report.checkedPlans} />
        <Stat label="Slots checked" value={report.checkedSlots} />
        <Stat label="Errors" value={report.errors} tone={report.errors > 0 ? "text-rose-700" : undefined} />
        <Stat label="Warnings" value={report.warnings} tone={report.warnings > 0 ? "text-amber-700" : undefined} />
      </section>

      {report.seedActive && (
        <p className="text-[11px] muted card px-3 py-2"><Info size={11} className="inline -mt-0.5 mr-1" />Dev/demo seed is active. In production this is gated off unless <code className="tabular">EDIFY_SEED_CORE=1</code>.</p>
      )}

      {groups.length === 0 ? (
        <section className="card p-8 text-center">
          <ShieldCheck className="mx-auto text-emerald-600" size={26} />
          <h2 className="text-[13px] font-extrabold mt-2">Lifecycle is sound</h2>
          <p className="text-[11.5px] muted mt-1">Every core record satisfies the one-schoolId integrity rules.</p>
        </section>
      ) : groups.map((g) => (
        <section key={g.sev} className="card p-3.5">
          <h2 className="text-[12px] font-extrabold tracking-tight mb-2 capitalize">{g.sev}s ({g.items.length})</h2>
          <ul className="space-y-1.5">
            {g.items.map((f) => {
              const Icon = ICON[f.severity];
              return (
                <li key={f.id} className="flex items-start gap-2 rounded-lg border border-[var(--color-edify-divider)] px-2.5 py-2">
                  <Icon size={13} className={cn("mt-0.5 shrink-0", TONE[f.severity])} />
                  <div className="min-w-0">
                    <div className="text-[11.5px] font-bold">{f.message}</div>
                    <div className="text-[10px] muted">
                      <code className="tabular">{f.rule}</code>
                      {f.schoolId && <> · school {f.schoolId}</>}
                      {f.slotId && <> · slot {f.slotId}</>}
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: number; tone?: string }) {
  return (
    <div className="card px-3 py-2.5">
      <div className="text-[10px] font-semibold muted leading-tight">{label}</div>
      <div className={cn("text-[18px] font-extrabold tabular leading-none mt-1", tone)}>{value}</div>
    </div>
  );
}

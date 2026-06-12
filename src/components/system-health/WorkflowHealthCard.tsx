// Workflow Health Monitor surface (spec layer #2). Server component — renders the
// ten stuck-workflow checks with counts and the offending records, each linked
// to where it's fixed.

import Link from "next/link";
import { AlertTriangle, CheckCircle2, ChevronRight } from "lucide-react";
import { Pill, type PillTone } from "@/components/ui/Pill";
import { workflowHealth, type HealthSeverity } from "@/lib/health/workflow-health";

const SEV_TONE: Record<HealthSeverity, PillTone> = {
  critical: "danger",
  warning: "warning",
  info: "info",
};

export function WorkflowHealthCard() {
  const report = workflowHealth();
  const firing = report.checks.filter((c) => c.count > 0);
  const clean = report.totalIssues === 0;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Workflow Health Monitor</h2>
          <p className="text-xs text-slate-500">
            Ten checks for stuck work across the school → activity → evidence → IA → payment chain.
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          {clean ? (
            <Pill tone="success" icon={CheckCircle2}>All clear</Pill>
          ) : (
            <>
              {report.criticalCount > 0 && <Pill tone="danger" icon={AlertTriangle}>{report.criticalCount} critical</Pill>}
              {report.warningCount > 0 && <Pill tone="warning">{report.warningCount} warning</Pill>}
            </>
          )}
        </div>
      </header>

      {clean ? (
        <p className="mt-3 text-sm text-emerald-600">No stuck workflows detected. The pipeline is flowing end-to-end.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {firing.map((c) => (
            <li key={c.id} className="rounded-xl border border-slate-200 dark:border-slate-800">
              <details>
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 p-3">
                  <span className="flex min-w-0 items-center gap-2">
                    <Pill tone={SEV_TONE[c.severity]} size="xs">{c.count}</Pill>
                    <span className="truncate text-sm font-medium text-slate-700 dark:text-slate-200">{c.label}</span>
                  </span>
                  <ChevronRight size={15} className="shrink-0 text-slate-400" />
                </summary>
                <div className="border-t border-slate-100 px-3 pb-3 pt-2 dark:border-slate-800">
                  <p className="mb-2 text-xs text-slate-500">{c.description}</p>
                  <ul className="space-y-1">
                    {c.issues.slice(0, 12).map((i) => (
                      <li key={`${i.check}-${i.entityId}`} className="flex items-center justify-between gap-3 text-xs">
                        <span className="min-w-0">
                          <span className="font-medium text-slate-700 dark:text-slate-200">{i.entityLabel}</span>
                          <span className="text-slate-400"> — {i.detail}</span>
                        </span>
                        {i.href && (
                          <Link href={i.href} className="shrink-0 font-medium text-blue-600 no-underline hover:underline">
                            Fix →
                          </Link>
                        )}
                      </li>
                    ))}
                    {c.issues.length > 12 && (
                      <li className="text-xs text-slate-400">+ {c.issues.length - 12} more…</li>
                    )}
                  </ul>
                </div>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

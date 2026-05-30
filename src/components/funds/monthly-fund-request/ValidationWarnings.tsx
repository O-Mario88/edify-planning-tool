"use client";

// Validation warnings panel.
//
// Lists every MfrValidationIssue attached to the request, grouped by
// severity (critical → warning → info). CD cannot approve while
// critical issues remain. Warnings can be acknowledged with a note;
// info is informational only.

import { AlertOctagon, AlertTriangle, Info } from "lucide-react";
import type { MfrValidationIssue } from "@/lib/funds/monthly-fund-request-types";
import { cn } from "@/lib/utils";

export function ValidationWarnings({
  issues,
}: {
  issues: MfrValidationIssue[];
}) {
  if (issues.length === 0) {
    return (
      <section className="card p-4 flex items-center gap-2 text-[12px]">
        <span className="inline-flex items-center gap-1.5 text-emerald-700 font-bold">
          <AlertOctagon size={13} className="rotate-180" />
          All checks passed.
        </span>
        <span className="muted">No critical issues detected in the generated request.</span>
      </section>
    );
  }

  const critical = issues.filter((i) => i.severity === "critical");
  const warning  = issues.filter((i) => i.severity === "warning");
  const info     = issues.filter((i) => i.severity === "info");

  return (
    <section className="card p-4 flex flex-col gap-2">
      <header className="flex items-center justify-between gap-3 mb-1">
        <h3 className="text-[14px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <AlertTriangle size={13} className="text-amber-600" />
          Validation
          <span className="text-[10.5px] muted font-semibold">
            ({critical.length} critical · {warning.length} warning · {info.length} info)
          </span>
        </h3>
      </header>
      <ul className="flex flex-col gap-1.5">
        {[...critical, ...warning, ...info].map((issue) => (
          <li
            key={issue.id}
            className={cn(
              "rounded-lg border px-3 py-2 flex items-start gap-2.5",
              issue.severity === "critical" && "bg-rose-50 border-rose-200",
              issue.severity === "warning"  && "bg-amber-50 border-amber-200",
              issue.severity === "info"     && "bg-sky-50 border-sky-200",
            )}
          >
            <span className={cn(
              "shrink-0 mt-0.5",
              issue.severity === "critical" && "text-rose-700",
              issue.severity === "warning"  && "text-amber-700",
              issue.severity === "info"     && "text-sky-700",
            )}>
              {issue.severity === "critical" ? <AlertOctagon size={12} /> :
               issue.severity === "warning"  ? <AlertTriangle size={12} /> :
                                               <Info size={12} />}
            </span>
            <div className="min-w-0 flex-1">
              <div className={cn(
                "text-[12px] font-semibold leading-snug",
                issue.severity === "critical" && "text-rose-800",
                issue.severity === "warning"  && "text-amber-800",
                issue.severity === "info"     && "text-sky-800",
              )}>
                {issue.message}
              </div>
              <div className="mt-0.5 text-[10px] muted font-semibold tracking-wide uppercase">
                {issue.code}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// Quality-gate notices (spec layer #5). Renders hard blocks (rose) and soft
// warnings (amber) for an entity. Soft gates inform without stopping work; hard
// gates are shown as the reason an action is unavailable. Server-safe.

import { AlertOctagon, AlertTriangle } from "lucide-react";
import type { GateEvaluation } from "@/lib/gates/quality-gates";

export function QualityGateNotices({ evaluation, className }: { evaluation: GateEvaluation; className?: string }) {
  if (evaluation.blocks.length === 0 && evaluation.warnings.length === 0) return null;

  return (
    <div className={className}>
      {evaluation.blocks.map((b) => (
        <div
          key={b.code}
          className="mb-1.5 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50/70 px-3 py-2 text-[12px] text-rose-800 dark:border-rose-500/30 dark:bg-rose-500/10 dark:text-rose-200"
        >
          <AlertOctagon size={14} className="mt-0.5 shrink-0" />
          <span><span className="font-semibold">Blocked:</span> {b.message}</span>
        </div>
      ))}
      {evaluation.warnings.map((w) => (
        <div
          key={w.code}
          className="mb-1.5 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/70 px-3 py-2 text-[12px] text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-200"
        >
          <AlertTriangle size={14} className="mt-0.5 shrink-0" />
          <span><span className="font-semibold">Warning:</span> {w.message}</span>
        </div>
      ))}
    </div>
  );
}

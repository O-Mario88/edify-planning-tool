// Budget & fund approval workflow stepper (Staff/CEO → PL → IA → Accountant →
// CD → RVP). Config-driven; reused by every budget dashboard.

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export type WorkflowStepStatus = "done" | "current" | "pending";
export type WorkflowStep = { label: string; status: WorkflowStepStatus; date?: string; statusLabel?: string };

export function ApprovalWorkflowStepper({ steps }: { steps: WorkflowStep[] }) {
  return (
    <div className="flex items-start">
      {steps.map((s, i) => {
        const isLast = i === steps.length - 1;
        return (
          <div key={s.label} className="flex-1 min-w-0">
            <div className="flex items-center">
              <span
                className={cn(
                  "h-8 w-8 rounded-full grid place-items-center text-[12px] font-extrabold shrink-0 border-2",
                  s.status === "done" && "bg-[var(--color-edify-primary)] border-[var(--color-edify-primary)] text-white",
                  s.status === "current" && "bg-white border-[var(--color-edify-orange,#ea8c2f)] text-[var(--color-edify-orange,#ea8c2f)]",
                  s.status === "pending" && "bg-white border-[var(--color-edify-border)] text-[var(--color-edify-muted)]",
                )}
              >
                {s.status === "done" ? <Check size={15} /> : i + 1}
              </span>
              {!isLast && (
                <span
                  className={cn(
                    "flex-1 h-[3px] mx-1 rounded-full",
                    s.status === "done" ? "bg-[var(--color-edify-primary)]" : "bg-[var(--color-edify-border)]",
                  )}
                />
              )}
            </div>
            <div className="mt-1.5 pr-2">
              <div className="text-[11.5px] font-bold leading-tight">{s.label}</div>
              <div className={cn(
                "text-[10.5px] font-semibold mt-0.5",
                s.status === "current" ? "text-[var(--color-edify-orange,#ea8c2f)]" : "muted",
              )}>
                {s.statusLabel ?? (s.status === "done" ? "Completed" : s.status === "current" ? "In Progress" : "Pending")}
              </div>
              {s.date && <div className="text-[10px] muted mt-0.5">{s.date}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

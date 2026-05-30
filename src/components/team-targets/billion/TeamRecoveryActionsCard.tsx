"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, CheckCircle2, Sparkles } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { teamRecoveryActions } from "@/lib/team-targets-billion-mock";
import { useDemoStore } from "@/components/demo/DemoStore";
import { cn } from "@/lib/utils";

// Team Recovery Actions — manager-level moves to recover the cohort.
// Each row is a Program Lead action with a scope chip (region or
// cohort segment) and a primary Action button that confirms.
export function TeamRecoveryActionsCard() {
  const { pushToast } = useDemoStore();
  const [submitted, setSubmitted] = useState<Record<string, true>>({});

  function handleAction(key: string, text: string) {
    setSubmitted((prev) => ({ ...prev, [key]: true }));
    pushToast({ tone: "success", title: "Team recovery action queued", body: text });
  }

  return (
    <SectionCard
      icon={<Sparkles size={13} className="text-amber-500" />}
      title="Team Recovery Actions"
      subtitle="Manager-level moves to recover team pace this week."
    >
      <ul className="space-y-2">
        {teamRecoveryActions.map((r) => {
          const done = !!submitted[r.key];
          return (
            <li
              key={r.key}
              className={cn(
                "rounded-xl border border-[var(--color-edify-border)] p-3 flex items-start gap-3 transition-colors",
                done ? "bg-emerald-50/40 border-emerald-200" : "bg-white",
              )}
            >
              <span className={cn(
                "w-8 h-8 rounded-lg grid place-items-center shrink-0",
                done ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700",
              )}>
                {done ? <CheckCircle2 size={14} /> : <Sparkles size={14} />}
              </span>
              <div className="min-w-0 flex-1">
                <div className="text-[12px] font-semibold text-slate-800 leading-snug">{r.text}</div>
                <div className="text-caption muted font-semibold mt-1 truncate">
                  {r.scope}
                </div>
              </div>
              <button
                type="button"
                disabled={done}
                onClick={() => !done && handleAction(r.key, r.text)}
                className={cn(
                  "btn btn-sm shrink-0 inline-flex items-center gap-1",
                  done ? "opacity-60" : "btn-primary",
                )}
              >
                {done ? "Queued" : "Action"}
                {!done && <ArrowRight size={11} />}
              </button>
            </li>
          );
        })}
      </ul>

      <Link
        href="/team-targets"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--color-edify-primary)] hover:underline"
      >
        View All recovery actions
        <ArrowUpRight size={11} />
      </Link>
    </SectionCard>
  );
}

"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, CheckCircle2, Sparkles } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { recoveryActions } from "@/lib/my-targets-billion-mock";
import { useDemoStore } from "@/components/demo/DemoStore";
import { cn } from "@/lib/utils";

// Recovery Actions — counterweight to the Needs Attention card. Each
// row is one suggested move with a primary "Action" button; tapping
// it confirms the action and flips the row to a Submitted state.
export function RecoveryActionsCard() {
  const { pushToast } = useDemoStore();
  const [submitted, setSubmitted] = useState<Record<string, true>>({});

  function handleAction(key: string, text: string) {
    setSubmitted((prev) => ({ ...prev, [key]: true }));
    pushToast({ tone: "success", title: "Recovery action queued", body: text });
  }

  return (
    <SectionCard
      icon={<Sparkles size={13} className="text-amber-500" />}
      title="Recovery Actions"
      subtitle="Four moves to recover monthly pace this week."
    >
      <ul className="space-y-2">
        {recoveryActions.map((r) => {
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
                {done ? "Submitted" : "Action"}
                {!done && <ArrowRight size={11} />}
              </button>
            </li>
          );
        })}
      </ul>

      <Link
        href="/planning"
        className="mt-3 inline-flex items-center gap-1 text-[11.5px] font-bold text-[var(--color-edify-primary)] hover:underline"
      >
        View All Recovery Actions
        <ArrowUpRight size={11} />
      </Link>
    </SectionCard>
  );
}

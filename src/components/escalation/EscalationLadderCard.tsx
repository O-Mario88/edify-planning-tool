// Escalation ladder surface (spec layer #8). Server component — shows open work
// grouped by escalation level (Day 1 notify → Day 5 CD risk), so ops can see
// what's aging and who it has escalated to.

import Link from "next/link";
import { Bell, BellRing, ArrowUpCircle, AlertOctagon } from "lucide-react";
import { escalations, LEVEL_LABEL, type EscalationLevel } from "@/lib/escalation/escalation-engine";

const LEVEL_ICON: Record<EscalationLevel, React.ComponentType<{ size?: number; className?: string }>> = {
  1: Bell, 2: BellRing, 3: ArrowUpCircle, 4: AlertOctagon,
};
const LEVEL_TONE: Record<EscalationLevel, string> = {
  1: "text-slate-500", 2: "text-blue-500", 3: "text-amber-500", 4: "text-rose-500",
};

export function EscalationLadderCard() {
  const items = escalations();
  if (items.length === 0) {
    return (
      <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Escalation ladder</h2>
        <p className="mt-1 text-sm text-emerald-600">Nothing is aging — no work has escalated.</p>
      </section>
    );
  }

  const levels: EscalationLevel[] = [4, 3, 2, 1];
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Escalation ladder</h2>
        <p className="text-xs text-slate-500">Ignored work escalates by age: notify → remind → supervisor → CD risk.</p>
      </header>
      <div className="space-y-3">
        {levels.map((lvl) => {
          const group = items.filter((i) => i.level === lvl);
          if (group.length === 0) return null;
          const Icon = LEVEL_ICON[lvl];
          return (
            <div key={lvl}>
              <p className={`mb-1 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide ${LEVEL_TONE[lvl]}`}>
                <Icon size={12} /> {LEVEL_LABEL[lvl]} · {group.length}
              </p>
              <ul className="space-y-1">
                {group.slice(0, 8).map((i) => (
                  <li key={i.id} className="flex items-center justify-between gap-3 text-xs">
                    <span className="min-w-0">
                      <span className="font-medium text-slate-700 dark:text-slate-200">{i.label}</span>
                      <span className="text-slate-400"> — {i.detail}</span>
                    </span>
                    {i.href && (
                      <Link href={i.href} className="shrink-0 font-medium text-blue-600 no-underline hover:underline">{i.action} →</Link>
                    )}
                  </li>
                ))}
                {group.length > 8 && <li className="text-[11px] text-slate-400">+ {group.length - 8} more…</li>}
              </ul>
            </div>
          );
        })}
      </div>
    </section>
  );
}

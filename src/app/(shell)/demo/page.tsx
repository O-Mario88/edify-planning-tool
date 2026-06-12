import Link from "next/link";
import { CheckCircle2, Circle, ArrowRight } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { DemoReadinessCard } from "@/components/system-health/DemoReadinessCard";
import { demoScript } from "@/lib/demo/demo-script";

// Demo Scenario Builder (spec layer #12) — the guided 14-step path for walking a
// contract approver through the system end-to-end, each step with a live status
// check and a deep link. Pairs with the Demo Readiness Score above it.
export default async function DemoPage() {
  const script = demoScript();

  return (
    <>
      <PageHeader
        title="Demo Walkthrough"
        subtitle="A controlled 14-step path through the whole system — upload → cluster → SSA → schedule → cost → partner → evidence → Salesforce → IA → payment → completed log → dashboards. Each step is checked against live data so nothing dead-ends in front of the approver."
      />
      <div className="px-4 sm:px-6 pt-2 pb-24 space-y-4">
        <DemoReadinessCard />

        <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
          <header className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Guided demo path</h2>
            <span className="text-xs font-semibold text-emerald-600">{script.doneCount}/{script.total} steps have live data</span>
          </header>
          <ol className="space-y-2">
            {script.steps.map((s) => (
              <li
                key={s.n}
                className="flex items-center gap-3 rounded-xl border border-slate-200 p-3 dark:border-slate-800"
              >
                <span className="shrink-0">
                  {s.status === "done" ? (
                    <CheckCircle2 size={18} className="text-emerald-500" />
                  ) : (
                    <Circle size={18} className="text-slate-300" />
                  )}
                </span>
                <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-slate-100 text-[11px] font-bold text-slate-500 dark:bg-slate-800">
                  {s.n}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{s.title}</p>
                  <p className="truncate text-xs text-slate-500">{s.description}</p>
                  <p className="text-[11px] text-slate-400">{s.note}</p>
                </div>
                <Link
                  href={s.href}
                  className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-slate-200 px-2.5 py-1.5 text-xs font-medium text-slate-600 no-underline hover:bg-slate-50 dark:border-slate-700 dark:text-slate-300 dark:hover:bg-slate-800"
                >
                  {s.linkLabel} <ArrowRight size={13} />
                </Link>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </>
  );
}

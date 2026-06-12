// Source-of-Truth Locks surface (spec layer #11). Server component — shows the
// one canonical source for each domain so the "no parallel data universes" rule
// is visible and auditable.

import { Lock, Unlock } from "lucide-react";
import { sourceOfTruthManifest } from "@/lib/source-of-truth/sources";

export function SourceOfTruthCard() {
  const locks = sourceOfTruthManifest();
  const lockedCount = locks.filter((l) => l.locked).length;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <header className="mb-3 flex items-center justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Source-of-Truth Locks</h2>
          <p className="text-xs text-slate-500">One canonical source per domain — no parallel data universes.</p>
        </div>
        <span className="text-xs font-semibold text-emerald-600">{lockedCount}/{locks.length} locked</span>
      </header>
      <ul className="divide-y divide-slate-100 dark:divide-slate-800">
        {locks.map((l) => (
          <li key={l.domain} className="flex items-start gap-3 py-2">
            <span className={l.locked ? "mt-0.5 text-emerald-500" : "mt-0.5 text-amber-500"}>
              {l.locked ? <Lock size={13} /> : <Unlock size={13} />}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {l.domain} <span className="text-slate-400">→ {l.canonicalSource}</span>
              </p>
              <p className="font-mono text-[11px] text-slate-400">{l.accessor}</p>
              {l.note && <p className="mt-0.5 text-[11px] text-slate-400">{l.note}</p>}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

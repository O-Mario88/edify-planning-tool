// Smart Grouping surface (spec layer #7). Server component — proposes efficient
// planning batches (same-sub-county and same-weak-area) so staff schedule in
// groups, not one school at a time.

import { Layers, MapPin, GraduationCap } from "lucide-react";
import { smartGroupingSuggestions } from "@/lib/planning/smart-grouping";

export function SmartGroupingCard({ assignedCceo }: { assignedCceo?: string }) {
  const suggestions = smartGroupingSuggestions({ assignedCceo });
  if (suggestions.length === 0) return null;

  return (
    <section className="rounded-2xl border border-violet-200 bg-violet-50/40 p-4 dark:border-violet-500/30 dark:bg-violet-500/5">
      <header className="mb-2 flex items-center gap-2">
        <Layers size={15} className="text-violet-600" />
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Smart grouping</h2>
        <span className="text-xs text-slate-500">— batch these instead of scheduling one at a time</span>
      </header>
      <ul className="space-y-2">
        {suggestions.slice(0, 5).map((s) => (
          <li
            key={s.id}
            className="flex items-start gap-2.5 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900/40"
          >
            <span className="mt-0.5 shrink-0 text-violet-500">
              {s.kind === "geographic" ? <MapPin size={14} /> : <GraduationCap size={14} />}
            </span>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{s.title}</p>
              <p className="text-xs text-slate-500">{s.recommendation}</p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// Operational Timeline surface (spec layer #4). Server component — renders a
// school's full chronological story as a vertical timeline. Drops onto any
// school profile.

import {
  Upload, ClipboardCheck, Network, Sparkles, CalendarDays,
  FileCheck2, Hash, ShieldCheck, BadgeDollarSign, TrendingUp,
} from "lucide-react";
import { schoolTimeline, type TimelineEventKind } from "@/lib/school-directory/school-timeline";
import { cn } from "@/lib/utils";

const ICON: Record<TimelineEventKind, React.ComponentType<{ size?: number; className?: string }>> = {
  uploaded: Upload,
  ssa_uploaded: ClipboardCheck,
  cluster_assigned: Network,
  recommendation: Sparkles,
  scheduled: CalendarDays,
  evidence: FileCheck2,
  salesforce: Hash,
  ia_verified: ShieldCheck,
  payment: BadgeDollarSign,
  ssa_improved: TrendingUp,
};

const TONE: Record<TimelineEventKind, string> = {
  uploaded: "text-slate-500 bg-slate-100 dark:bg-slate-800",
  ssa_uploaded: "text-blue-600 bg-blue-50 dark:bg-sky-500/10",
  cluster_assigned: "text-violet-600 bg-violet-50 dark:bg-violet-500/10",
  recommendation: "text-amber-600 bg-amber-50 dark:bg-amber-500/10",
  scheduled: "text-blue-600 bg-blue-50 dark:bg-sky-500/10",
  evidence: "text-emerald-600 bg-emerald-50 dark:bg-emerald-500/10",
  salesforce: "text-indigo-600 bg-indigo-50 dark:bg-indigo-500/10",
  ia_verified: "text-emerald-700 bg-emerald-50 dark:bg-emerald-500/10",
  payment: "text-emerald-700 bg-emerald-50 dark:bg-emerald-500/10",
  ssa_improved: "text-emerald-700 bg-emerald-100 dark:bg-emerald-500/15",
};

function fmt(date: string): string {
  const t = Date.parse(date);
  if (Number.isNaN(t)) return date;
  return new Date(t).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function SchoolTimeline({ schoolId }: { schoolId: string }) {
  const events = schoolTimeline(schoolId);
  if (events.length === 0) return null;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <header className="mb-3">
        <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Operational timeline</h2>
        <p className="text-xs text-slate-500">Every step in this school's story — upload to verified impact.</p>
      </header>
      <ol className="relative space-y-3">
        {events.map((e, i) => {
          const Icon = ICON[e.kind];
          return (
            <li key={`${e.kind}-${i}`} className="flex gap-3">
              <div className="flex flex-col items-center">
                <span className={cn("grid h-7 w-7 shrink-0 place-items-center rounded-full", TONE[e.kind])}>
                  <Icon size={13} />
                </span>
                {i < events.length - 1 && <span className="mt-1 w-px flex-1 bg-slate-200 dark:bg-slate-700" />}
              </div>
              <div className="min-w-0 pb-1">
                <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{fmt(e.date)}</p>
                <p className="text-sm font-medium text-slate-700 dark:text-slate-200">{e.title}</p>
                {e.detail && <p className="text-xs text-slate-400">{e.detail}</p>}
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

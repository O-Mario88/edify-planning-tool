// "Your next best action" section (spec layer #1) — a drop-in server component.
//
// Reads the Unified Activity model for one person and renders the single most
// pressing next step prominently, then the next few as tappable rows. Additive:
// drops onto My Plan, dashboards, or any server surface without touching that
// surface's existing item shapes.

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { unifiedActivitiesForAssignee } from "@/lib/activity/unified-activity-source";
import { isOpenActivity } from "@/lib/activity/unified-activity";
import { activityNextAction } from "@/lib/next-action/next-action";
import { NextActionCard, NextActionPill } from "./NextActionCard";

export function MyNextActions({
  assigneeId,
  limit = 4,
  heading = "Your next best action",
}: {
  assigneeId: string;
  limit?: number;
  heading?: string;
}) {
  const open = unifiedActivitiesForAssignee(assigneeId).filter(isOpenActivity);
  if (open.length === 0) return null;

  const ranked = open
    .map((a) => ({ a, action: activityNextAction(a) }))
    .sort((x, y) => y.action.urgency - x.action.urgency);

  const top = ranked[0];
  const rest = ranked.slice(1, limit);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white/60 p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <NextActionCard action={top.action} title={heading} />
      {rest.length > 0 && (
        <ul className="mt-2 divide-y divide-slate-100 dark:divide-slate-800">
          {rest.map(({ a, action }) => {
            const row = (
              <div className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-slate-700 dark:text-slate-200">{a.title}</p>
                  <p className="truncate text-xs text-slate-400">{action.reason}</p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <NextActionPill action={action} size="xs" />
                  {action.href && <ArrowRight size={13} className="text-slate-300" />}
                </div>
              </div>
            );
            return (
              <li key={a.id}>
                {action.href ? (
                  <Link href={action.href} className="block no-underline">
                    {row}
                  </Link>
                ) : (
                  row
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

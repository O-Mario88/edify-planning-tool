// Single-next-action renderers (spec layer #1).
//
// One look, used everywhere a record needs "what do I do now?": dashboards,
// My Plan, school/cluster/partner profiles, planning. Server-safe (just a link)
// so it drops into server components without a client boundary.

import Link from "next/link";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import { Pill, type PillTone } from "@/components/ui/Pill";
import type { NextAction } from "@/lib/next-action/next-action";
import { cn } from "@/lib/utils";

/** Map an action's urgency to the status ladder so colour = pressure. */
function toneFor(a: NextAction): PillTone {
  if (a.done) return "success";
  if (a.urgency >= 90) return "danger";
  if (a.urgency >= 60) return "warning";
  if (a.urgency >= 30) return "info";
  return "neutral";
}

const ACTOR_LABEL: Record<NextAction["actor"], string> = {
  owner: "You",
  reviewer: "Staff review",
  ia: "IA",
  accountant: "Accountant",
  none: "",
};

/** Inline pill — for dense rows/tables. Shows just the action label + tone. */
export function NextActionPill({ action, size = "sm" }: { action: NextAction; size?: "xs" | "sm" | "md" }) {
  return (
    <Pill tone={toneFor(action)} size={size} icon={action.done ? CheckCircle2 : undefined} dot={!action.done}>
      {action.label}
    </Pill>
  );
}

/**
 * Full card — for dashboards/profiles. Renders the one action as a tappable
 * row: label + why + who, linking to where it's done. A low-tech user can read
 * exactly one instruction and follow it.
 */
export function NextActionCard({
  action,
  title = "Next best action",
  className,
}: {
  action: NextAction;
  title?: string;
  className?: string;
}) {
  const tone = toneFor(action);
  const actor = ACTOR_LABEL[action.actor];
  const body = (
    <div
      className={cn(
        "flex items-center justify-between gap-3 rounded-xl border p-3 transition-colors",
        tone === "danger" && "border-rose-200 bg-rose-50/60 dark:border-rose-500/30 dark:bg-rose-500/5",
        tone === "warning" && "border-amber-200 bg-amber-50/60 dark:border-amber-500/30 dark:bg-amber-500/5",
        tone === "info" && "border-blue-200 bg-blue-50/50 dark:border-sky-500/30 dark:bg-sky-500/5",
        (tone === "neutral" || tone === "success") && "border-slate-200 bg-slate-50/60 dark:border-slate-700 dark:bg-slate-800/40",
        action.href && "hover:brightness-[0.99]",
        className,
      )}
    >
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-400">{title}</span>
          {actor && !action.done && (
            <Pill tone="neutral" size="xs" subtle>
              {actor}
            </Pill>
          )}
        </div>
        <p className="mt-0.5 truncate text-sm font-semibold text-slate-800 dark:text-slate-100">{action.label}</p>
        <p className="truncate text-xs text-slate-500">{action.reason}</p>
      </div>
      {action.href && !action.done && (
        <ArrowRight size={16} className="shrink-0 text-slate-400" />
      )}
    </div>
  );

  return action.href && !action.done ? (
    <Link href={action.href} className="block no-underline">
      {body}
    </Link>
  ) : (
    body
  );
}

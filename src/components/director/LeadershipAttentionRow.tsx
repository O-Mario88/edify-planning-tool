"use client";

import { AlertTriangle, Database, Wallet, ArrowRight, Bell } from "lucide-react";
import { leadershipAlerts, type LeadershipAlert } from "@/lib/director-mock";
import { cn } from "@/lib/utils";

const iconMap = {
  alertTriangle: AlertTriangle,
  database: Database,
  wallet: Wallet,
} as const;

// Tone classes — composed from the design system so both light and
// dark themes hit the right contrast. Light mode keeps the cream
// callout look; dark mode uses the same tone-overlay system as the
// rest of the app (low-alpha tinted fill, soft border, brighter text).
const toneFrame: Record<LeadershipAlert["tone"], string> = {
  amber: "bg-amber-50 border-amber-200 dark:bg-amber-500/[0.10] dark:border-amber-500/30",
  red:   "bg-rose-50  border-rose-200  dark:bg-rose-500/[0.10]  dark:border-rose-500/30",
  blue:  "bg-blue-50  border-blue-200  dark:bg-blue-500/[0.10]  dark:border-blue-500/30",
};
const toneIcon: Record<LeadershipAlert["tone"], string> = {
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300",
  red:   "bg-rose-100  text-rose-700  dark:bg-rose-500/20  dark:text-rose-300",
  blue:  "bg-blue-100  text-blue-800  dark:bg-blue-500/20  dark:text-blue-300",
};
const toneTitle: Record<LeadershipAlert["tone"], string> = {
  amber: "text-amber-900 dark:text-amber-100",
  red:   "text-rose-900  dark:text-rose-100",
  blue:  "text-blue-900  dark:text-blue-100",
};

export function LeadershipAttentionRow() {
  return (
    <section className="card p-2.5">
      <div className="flex items-center gap-2 mb-2 pl-0.5">
        <span className="w-5 h-5 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0">
          <Bell size={11} />
        </span>
        <h3 className="text-body font-bold">Leadership Attention</h3>
        <a className="ml-auto text-[11.5px] font-semibold text-[var(--color-edify-primary)]" href="#operational-risk">
          View All Alerts →
        </a>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        {leadershipAlerts.map((a) => {
          const Icon = iconMap[a.icon];
          return (
            <div
              key={a.id}
              className={cn("rounded-lg border px-2.5 py-2 flex items-start gap-2.5 overflow-hidden", toneFrame[a.tone])}
            >
              <span
                className={cn("w-7 h-7 rounded-md grid place-items-center mt-0.5 shrink-0", toneIcon[a.tone])}
              >
                <Icon size={13} />
              </span>
              <div className="flex-1 min-w-0">
                <div className={cn("text-[12px] font-bold leading-tight line-clamp-1", toneTitle[a.tone])}>{a.title}</div>
                <div className="text-[11px] muted mt-0.5 line-clamp-2">{a.body}</div>
                <a
                  href={a.href}
                  className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)] mt-1"
                >
                  {a.cta}
                  <ArrowRight size={10} />
                </a>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

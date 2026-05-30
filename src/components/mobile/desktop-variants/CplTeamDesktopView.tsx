import Link from "next/link";
import { Users, ChevronRight, Route } from "lucide-react";
import { MobileViewDesktopShell } from "@/components/mobile/MobileViewDesktopShell";
import { ProgressRing } from "@/components/ui/primitives";
import {
  cplMyTeam,
  cplTeamProgress,
  cplMyTargetsSummary,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const STATUS_TONE = {
  "On Track": "bg-emerald-100 text-emerald-700",
  "At Risk":  "bg-amber-100   text-amber-700",
  "Behind":   "bg-rose-100    text-rose-700",
} as const;

export function CplTeamDesktopView() {
  return (
    <MobileViewDesktopShell
      title="My Team"
      subtitle={`Direct supervision view — ${cplMyTeam.length} CCEOs. ${cplMyTargetsSummary.monthLabel}.`}
      asideRight={
        <>
          <div className="card p-3.5">
            <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">Team progress</h3>
            <div className="flex items-center gap-3">
              <ProgressRing
                pct={cplTeamProgress.donutPct}
                size={88}
                stroke={9}
                color="var(--color-edify-primary)"
                label={`${cplTeamProgress.donutPct}%`}
                sublabel="team"
              />
              <div className="text-[11.5px] muted leading-snug">
                {cplTeamProgress.monthLabel} achievement
              </div>
            </div>
          </div>
          <Link href="/dashboards/cpl" className="card p-3.5 flex items-center gap-2 hover:bg-[var(--color-edify-soft)]/40">
            <Users size={14} className="text-[var(--color-edify-primary)]" />
            <span className="text-body font-extrabold tracking-tight">CPL dashboard</span>
            <ChevronRight size={12} className="ml-auto text-[var(--color-edify-muted)]" />
          </Link>
          <Link href="/staff" className="card p-3.5 flex items-center gap-2 hover:bg-[var(--color-edify-soft)]/40">
            <Users size={14} className="text-[var(--color-edify-primary)]" />
            <span className="text-body font-extrabold tracking-tight">Full staff directory</span>
            <ChevronRight size={12} className="ml-auto text-[var(--color-edify-muted)]" />
          </Link>
        </>
      }
    >
      <section className="card p-3.5">
        <header className="flex items-baseline justify-between mb-2">
          <h2 className="text-body-lg font-extrabold tracking-tight">CCEOs under my supervision</h2>
          <span className="text-caption muted">{cplMyTeam.length} staff</span>
        </header>
        <ul className="divide-y divide-[var(--color-edify-divider)]">
          {cplMyTeam.map((m) => (
            <li key={m.id} className="py-3 flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-[var(--color-edify-primary)] text-white text-[12px] font-extrabold grid place-items-center shrink-0">
                {m.initials}
              </div>
              <div className="flex-1 min-w-0">
                <Link href={`/staff/${m.id}`} className="text-[13px] font-extrabold tracking-tight truncate hover:text-[var(--color-edify-primary)]">
                  {m.name}
                </Link>
                <div className="text-caption muted truncate">
                  {m.role} · Backlog {m.backlog}
                </div>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                <span className={cn(
                  "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                  STATUS_TONE[m.status],
                )}>
                  {m.status}
                </span>
                <span className={cn(
                  "inline-flex items-center gap-1 px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                  m.routeStatus === "High" ? "bg-rose-100 text-rose-700" : "bg-sky-100 text-sky-700",
                )}>
                  <Route size={10} />
                  {m.routeBadge}
                </span>
                <div className="text-body-lg font-extrabold tabular shrink-0 w-12 text-right">
                  {m.achievementPct}%
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </MobileViewDesktopShell>
  );
}

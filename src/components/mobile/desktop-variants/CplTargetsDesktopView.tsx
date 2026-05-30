import Link from "next/link";
import {
  ArrowUpRight,
  ArrowDownRight,
  Users,
  ClipboardList,
  UserCheck,
  Wallet,
  ChevronRight,
  type LucideIcon,
} from "lucide-react";
import { MobileViewDesktopShell } from "@/components/mobile/MobileViewDesktopShell";
import { ProgressRing } from "@/components/ui/primitives";
import {
  cplTargetRings,
  cplTargetTeamRows,
  cplMyTargetsSummary,
  personalOverall,
  type CplTargetRing,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const RING_ICON: Record<CplTargetRing["icon"], LucideIcon> = {
  users:         Users,
  clipboardList: ClipboardList,
  userCheck:     UserCheck,
  wallet:        Wallet,
};

export function CplTargetsDesktopView() {
  return (
    <MobileViewDesktopShell
      title="My Targets"
      subtitle={`Personal targets for ${cplMyTargetsSummary.monthLabel}. Quarterly + monthly progress with team breakdown.`}
      asideRight={
        <>
          <div className="card p-3.5">
            <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">Overall</h3>
            <div className="flex items-center gap-3">
              <ProgressRing
                pct={personalOverall.pct}
                size={88}
                stroke={9}
                color="var(--color-edify-primary)"
                label={`${personalOverall.pct}%`}
                sublabel="overall"
              />
              <div className="text-[11.5px] muted leading-snug">{personalOverall.trend}</div>
            </div>
          </div>
          <div className="card p-3.5">
            <h3 className="text-body font-extrabold tracking-tight uppercase muted mb-2">{cplMyTargetsSummary.monthLabel}</h3>
            <div className="grid grid-cols-2 gap-2 text-[11.5px]">
              <Stat label="Quarterly"  value={`${cplMyTargetsSummary.quarterly.pct}%`} sub={cplMyTargetsSummary.quarterly.status} tone="edify" />
              <Stat label="Monthly"    value={`${cplMyTargetsSummary.monthly.pct}%`}   sub={cplMyTargetsSummary.monthly.status}   tone="green" />
              <Stat label="Approvals"  value={`${cplMyTargetsSummary.approvals.count}`} sub={cplMyTargetsSummary.approvals.label} tone="amber" />
            </div>
          </div>
          <Link href="/dashboards/cpl" className="card p-3.5 flex items-center gap-2 hover:bg-[var(--color-edify-soft)]/40">
            <span className="text-body font-extrabold tracking-tight">Open CPL dashboard</span>
            <ChevronRight size={12} className="ml-auto text-[var(--color-edify-muted)]" />
          </Link>
        </>
      }
    >
      {/* Target rings grid */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {cplTargetRings.map((r) => {
          const Icon = RING_ICON[r.icon];
          return (
            <div key={r.key} className="card p-3.5 flex items-center gap-3">
              <ProgressRing
                pct={r.pct}
                size={72}
                stroke={8}
                color="var(--color-edify-primary)"
                label={`${r.pct}%`}
              />
              <div className="flex-1 min-w-0">
                <span className="inline-flex h-8 w-8 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] items-center justify-center mb-1">
                  <Icon size={14} />
                </span>
                <div className="text-body font-extrabold tracking-tight leading-snug">{r.label}</div>
                <div className="text-caption muted">{r.current} of {r.total} · {r.caption}</div>
              </div>
            </div>
          );
        })}
      </section>

      {/* Team contribution table */}
      <section className="card p-3.5 mt-4">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">My Team&apos;s contribution</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th scope="col" className="py-2 pr-2">Target</th>
                <th scope="col" className="py-2 px-2 text-right">On / Off</th>
                <th scope="col" className="py-2 px-2 text-right">Achievement</th>
                <th scope="col" className="py-2 pl-2">Trend</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {cplTargetTeamRows.map((row) => (
                <tr key={row.key} className="hover:bg-[var(--color-edify-soft)]/30">
                  <td className="py-2.5 pr-2">
                    <div className="text-body font-extrabold tracking-tight">{row.label}</div>
                    <div className="text-caption muted">{row.caption}</div>
                  </td>
                  <td className="py-2.5 px-2 text-right tabular">
                    <span className="text-emerald-700 font-extrabold">{row.on}</span> / <span className="text-rose-700">{row.off}</span>
                  </td>
                  <td className="py-2.5 px-2 text-right tabular font-extrabold">{row.achievedPct}%</td>
                  <td className="py-2.5 pl-2">
                    <span className={cn(
                      "inline-flex items-center gap-1 text-caption font-semibold",
                      row.trend === "up" ? "text-emerald-600" : "text-rose-600",
                    )}>
                      {row.trend === "up" ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                      {row.trend === "up" ? "Improving" : "Declining"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </MobileViewDesktopShell>
  );
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub: string; tone: "edify" | "green" | "amber" }) {
  const TONE = {
    edify: "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]",
    green: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100   text-amber-700",
  } as const;
  return (
    <div className={cn("rounded-xl p-2.5", TONE[tone])}>
      <div className="text-[10px] font-bold uppercase tracking-wide leading-tight opacity-90">{label}</div>
      <div className="text-[16px] font-extrabold tabular leading-none mt-1">{value}</div>
      <div className="text-[10px] opacity-80 mt-0.5">{sub}</div>
    </div>
  );
}

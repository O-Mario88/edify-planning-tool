"use client";

import Link from "next/link";
import {
  ArrowUpRight,
  ArrowDownRight,
  Users,
  ClipboardList,
  UserCheck,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { CplBottomNav } from "@/components/mobile/CplBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
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

export function CplTargetsView() {
  return (
    <MobileShell>
      <MobileTopBar title="My Targets" backHref="/dashboards/cpl" />

      <main className="flex-1 px-3 pt-3 pb-4 space-y-3 bg-[var(--color-page)]">
        {/* Overall hero */}
        <section
          className="rounded-2xl p-4 text-white flex items-center gap-3"
          style={{ backgroundImage: "linear-gradient(180deg, #0e1c2c 0%, #0a1623 100%)" }}
        >
          <div className="flex-1 min-w-0">
            <div className="text-[19px] leading-[1.15] font-extrabold tracking-tight">
              Stay on pace.
            </div>
            <p className="mt-1.5 text-[11.5px] text-white/65 leading-snug">
              Personal targets for {cplMyTargetsSummary.monthLabel} —
              {" "}{personalOverall.trend}.
            </p>
          </div>
          <div className="shrink-0 relative" style={{ width: 92, height: 92 }}>
            <ProgressRing
              pct={personalOverall.pct}
              size={92}
              stroke={9}
              color="#10d3a4"
              trackColor="rgba(255,255,255,0.12)"
            />
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <div className="text-[19px] font-extrabold tabular leading-none">
                {personalOverall.pct}%
              </div>
              <div className="text-[8.5px] text-white/70 mt-1">Overall</div>
            </div>
          </div>
        </section>

        {/* Target rings — 2x2 */}
        <section className="grid grid-cols-2 gap-2">
          {cplTargetRings.map((r) => {
            const Icon = RING_ICON[r.icon];
            return (
              <div
                key={r.key}
                className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 shadow-sm flex items-center gap-3"
              >
                <div className="relative shrink-0" style={{ width: 64, height: 64 }}>
                  <ProgressRing pct={r.pct} size={64} stroke={6} color="var(--color-edify-primary)" />
                  <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                    <div className="text-body font-extrabold tabular leading-none">{r.pct}%</div>
                  </div>
                </div>
                <div className="min-w-0">
                  <span className="w-7 h-7 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center mb-1">
                    <Icon size={13} />
                  </span>
                  <div className="text-caption muted font-semibold leading-tight line-clamp-2">
                    {r.label}
                  </div>
                  <div className="text-body font-extrabold tabular mt-0.5">
                    {r.current} / {r.total}
                  </div>
                  <div className="text-[10px] text-emerald-600 font-semibold mt-0.5 inline-flex items-center gap-0.5">
                    <ArrowUpRight size={10} />
                    {r.caption}
                  </div>
                </div>
              </div>
            );
          })}
        </section>

        {/* Team Targets — compact rows */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm">
          <div className="px-3 pt-3 pb-2 flex items-center justify-between">
            <h3 className="text-body font-extrabold tracking-tight">Team Targets</h3>
            <Link href="/team-targets" className="text-[11px] font-semibold text-emerald-600">
              Open full view
            </Link>
          </div>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {cplTargetTeamRows.map((row) => (
              <li key={row.key} className="px-3 py-2.5 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-[12px] font-extrabold tracking-tight truncate">{row.label}</div>
                  <div className="text-caption muted">{row.caption}</div>
                  <div className="mt-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                    <div
                      className="h-full bg-[var(--color-edify-primary)]"
                      style={{ width: `${row.achievedPct}%` }}
                    />
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-body-lg font-extrabold tabular leading-none">{row.achievedPct}%</div>
                  <div
                    className={cn(
                      "text-[10px] font-semibold mt-0.5 inline-flex items-center gap-0.5",
                      row.trend === "up" ? "text-emerald-600" : "text-rose-600",
                    )}
                  >
                    {row.trend === "up" ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                    {row.on} on / {row.off} off
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* Approvals quick stat */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 shadow-sm flex items-center gap-3">
          <div className="w-10 h-10 rounded-md bg-emerald-50 text-emerald-600 grid place-items-center shrink-0">
            <ClipboardList size={16} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[12px] font-extrabold tracking-tight">Approvals Completed</div>
            <div className="text-caption muted">{cplMyTargetsSummary.approvals.label}</div>
          </div>
          <div className="text-[20px] font-extrabold tabular shrink-0">
            {cplMyTargetsSummary.approvals.count}
          </div>
        </section>
      </main>

      <CplBottomNav />
    </MobileShell>
  );
}

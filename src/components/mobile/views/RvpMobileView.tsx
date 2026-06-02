"use client";

import Link from "next/link";
import {
  Globe,
  Wallet,
  Target,
  TrendingUp,
  AlertTriangle,
  ChevronRight,
  ArrowUpRight,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { MobileBottomNav } from "@/components/mobile/MobileBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { ProgressRing } from "@/components/ui/primitives";
import { countryRollups, specialProjects } from "@/lib/workflow-mock";
import { cn } from "@/lib/utils";

export function RvpMobileView() {
  const totalSchools     = countryRollups.reduce((a, c) => a + c.schools, 0);
  const totalCommitted   = countryRollups.reduce((a, c) => a + c.fundsCommittedUgxM, 0);
  const totalDisbursed   = countryRollups.reduce((a, c) => a + c.fundsDisbursedUgxM, 0);
  const avgTarget        = Math.round(countryRollups.reduce((a, c) => a + c.monthlyTargetPct, 0) / countryRollups.length);
  const avgValidVisit    = Math.round(countryRollups.reduce((a, c) => a + c.validVisitPct, 0)   / countryRollups.length);
  const avgSsa           = Math.round(countryRollups.reduce((a, c) => a + c.ssaCompletedPct, 0) / countryRollups.length);
  const utilizationPct   = Math.round((totalDisbursed / totalCommitted) * 100);

  return (
    <MobileShell>
      <MobileTopBar />
      <section
        className="text-white px-4 pt-3 pb-4"
        style={{ backgroundImage: "linear-gradient(180deg, #0e1c2c 0%, #0a1623 100%)" }}
      >
        <h2 className="text-[20px] leading-[1.15] font-extrabold tracking-tight">
          East Africa region.
        </h2>
        <p className="mt-1.5 text-[11.5px] text-white/65 leading-snug">
          {countryRollups.length} countries · {totalSchools} schools · UGX {totalCommitted}M committed
        </p>
      </section>

      <main className="flex-1 px-3 pt-3 pb-4 space-y-3 bg-[var(--color-page)]">
        {/* Region utilization hero */}
        <section
          className="rounded-2xl p-4 text-white flex items-center gap-3"
          style={{ backgroundImage: "linear-gradient(180deg, #0e1c2c 0%, #0a1623 100%)" }}
        >
          <div className="flex-1 min-w-0">
            <div className="text-[16px] leading-[1.2] font-extrabold tracking-tight">
              Funds Utilization
            </div>
            <p className="mt-1.5 text-[11.5px] text-white/65 leading-snug">
              UGX {totalDisbursed}M disbursed of {totalCommitted}M committed across the region.
            </p>
          </div>
          <div className="shrink-0 relative" style={{ width: 84, height: 84 }}>
            <ProgressRing pct={utilizationPct} size={84} stroke={8} color="#10d3a4" trackColor="rgba(255,255,255,0.12)" />
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <div className="text-[18px] font-extrabold tabular leading-none">{utilizationPct}%</div>
              <div className="text-[8.5px] text-white/70 mt-1">Utilization</div>
            </div>
          </div>
        </section>

        {/* KPI tiles */}
        <section className="grid grid-cols-2 gap-2">
          <KpiTile Icon={Globe}       label="Schools in Region" value={String(totalSchools)} caption={`${countryRollups.length} countries`} tone="edify" />
          <KpiTile Icon={Target}      label="Avg Monthly Target" value={`${avgTarget}%`}     caption="Region-weighted"   tone="amber" />
          <KpiTile Icon={TrendingUp}  label="Avg Valid Visit"    value={`${avgValidVisit}%`}  caption="Verified portion"  tone="green" />
          <KpiTile Icon={Wallet}      label="Avg SSA Done"       value={`${avgSsa}%`}         caption="Region"            tone="violet" />
        </section>

        {/* Country rollups */}
        <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm">
          <div className="px-3 pt-3 pb-2 flex items-center justify-between">
            <h3 className="text-body font-extrabold tracking-tight">Countries</h3>
            <Link href="/dashboards/rvp" className="text-[11px] font-semibold text-emerald-600 inline-flex items-center gap-0.5 lg:hidden">
              Open full dashboard
              <ChevronRight size={11} />
            </Link>
          </div>
          <ul className="divide-y divide-[var(--color-edify-divider)]">
            {countryRollups.map((c) => (
              <li key={c.country} className="px-3 py-2.5 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-body font-extrabold tracking-tight">{c.country}</div>
                  <div className="text-caption muted">
                    {c.director} · {c.schools} schools · UGX {c.fundsDisbursedUgxM}/{c.fundsCommittedUgxM}M
                  </div>
                  <div className="mt-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                    <div
                      className="h-full bg-[var(--color-edify-primary)]"
                      style={{ width: `${c.monthlyTargetPct}%` }}
                    />
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-body-lg font-extrabold tabular leading-none">{c.monthlyTargetPct}%</div>
                  <div className="text-[10px] text-emerald-600 font-semibold mt-0.5 inline-flex items-center gap-0.5">
                    <ArrowUpRight size={10} />
                    target
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* Special projects callout */}
        <Link
          href="/special-projects"
          className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm px-3 py-3 flex items-center gap-3 active:bg-[var(--color-edify-soft)]/40"
        >
          <span className="h-9 w-9 rounded-md bg-amber-100 text-amber-700 grid place-items-center shrink-0">
            <AlertTriangle size={15} />
          </span>
          <div className="flex-1 min-w-0">
            <div className="text-body font-extrabold tracking-tight">Special Projects</div>
            <div className="text-caption muted">{specialProjects.length} active across the region</div>
          </div>
          <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
        </Link>
      </main>

      <MobileBottomNav role="RVP" />
    </MobileShell>
  );
}

function KpiTile({
  Icon, label, value, caption, tone,
}: {
  Icon: LucideIcon;
  label: string;
  value: string;
  caption: string;
  tone: "edify" | "amber" | "green" | "violet";
}) {
  const t =
    tone === "edify"  ? "bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)]" :
    tone === "amber"  ? "bg-amber-100   text-amber-700" :
    tone === "green"  ? "bg-emerald-100 text-emerald-700" :
                        "bg-violet-100  text-violet-700";
  return (
    <div className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm p-3">
      <span className={cn("h-8 w-8 rounded-md grid place-items-center", t)}>
        <Icon size={14} />
      </span>
      <div className="text-caption muted font-semibold leading-tight mt-1.5 line-clamp-2">{label}</div>
      <div className="text-[20px] font-extrabold tabular leading-none mt-0.5">{value}</div>
      <div className="text-[10px] muted font-semibold mt-0.5">{caption}</div>
    </div>
  );
}

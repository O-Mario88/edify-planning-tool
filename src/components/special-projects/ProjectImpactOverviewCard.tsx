"use client";

import {
  Building2,
  Users,
  ShieldCheck,
  ArrowUpRight,
  BarChart3,
  type LucideIcon,
} from "lucide-react";
import { SectionCard, DonutChart } from "@/components/ui/primitives";
import {
  teachersImpactedByProject,
  projectStatusMix,
  impactSummaryCards,
} from "@/lib/special-projects-mock";

const iconMap: Record<"school" | "users" | "shield", LucideIcon> = {
  school: Building2,
  users:  Users,
  shield: ShieldCheck,
};

export function ProjectImpactOverviewCard() {
  const max = Math.max(...teachersImpactedByProject.map((d) => d.value), 1);
  const totalProjects = projectStatusMix.reduce((a, x) => a + x.count, 0);

  return (
    <SectionCard
      icon={<BarChart3 size={13} />}
      title="Project Impact Overview"
      actions={
        <a
          className="text-[12px] font-semibold text-[var(--color-edify-primary)]"
          href="/analytics"
        >
          View detailed impact →
        </a>
      }
    >
      <div className="grid grid-cols-12 gap-4">
        {/* LEFT — Teachers Impacted by Project (horizontal bars) */}
        <div className="col-span-12 md:col-span-5">
          <div className="text-[12px] font-bold mb-2">Teachers Impacted by Project</div>
          <div className="text-caption muted mb-3">(Actuals)</div>
          <div className="space-y-2.5">
            {teachersImpactedByProject.map((d) => (
              <div key={d.project} className="grid grid-cols-[110px_1fr_56px] items-center gap-2">
                <div className="text-[11.5px] font-semibold truncate">{d.project}</div>
                <div className="h-3 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div
                    className="h-full rounded-full"
                    style={{ width: `${(d.value / max) * 100}%`, background: d.color }}
                  />
                </div>
                <div className="text-[11.5px] tabular font-bold text-right">
                  {d.value.toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* MIDDLE — Project Status Mix (donut) */}
        <div className="col-span-12 md:col-span-3 flex flex-col items-center">
          <div className="text-[12px] font-bold mb-2 self-start">Project Status Mix</div>
          <div className="text-caption muted mb-2 self-start">(By count)</div>
          <DonutChart
            slices={projectStatusMix.map((s) => ({
              label: s.label,
              value: s.count,
              pct: s.pct,
              color: s.color,
            }))}
            size={120}
            thickness={14}
            centerLabel={totalProjects}
            centerSublabel="Total Projects"
          />
          <div className="mt-3 space-y-1 self-start text-[11px]">
            {projectStatusMix.map((s) => (
              <div key={s.label} className="flex items-center gap-1.5">
                <span
                  className="w-2 h-2 rounded-full inline-block"
                  style={{ background: s.color }}
                />
                <span className="font-semibold">{s.label}</span>
                <span className="muted ml-1">
                  {s.count} ({s.pct}%)
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* RIGHT — Summary mini cards */}
        <div className="col-span-12 md:col-span-4 space-y-3">
          {impactSummaryCards.map((c) => {
            const Icon = iconMap[c.icon];
            return (
              <div
                key={c.key}
                className="rounded-xl border border-[var(--color-edify-border)] bg-white p-3 flex items-center gap-3"
              >
                <span className="w-10 h-10 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                  <Icon size={16} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[11px] muted font-semibold leading-tight">{c.label}</div>
                  <div className="text-[20px] font-extrabold tabular leading-none mt-1">
                    {c.value}
                  </div>
                </div>
                <div className="text-[11px] font-semibold flex items-center gap-1 text-[var(--color-success)] shrink-0">
                  <ArrowUpRight size={11} />
                  {c.delta}
                  <span className="muted font-medium ml-1">vs Apr</span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </SectionCard>
  );
}

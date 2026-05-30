"use client";

import Link from "next/link";
import { Target, ArrowRight, ShieldCheck, AlertTriangle } from "lucide-react";
import {
  teamTargetRollupFor,
  notificationsForRole,
  countryTargetRollups,
} from "@/lib/team-targets-mock";
import type { CurrentUser } from "@/lib/schools-mock";
import { cn } from "@/lib/utils";

export function TeamTargetsCallout({
  user,
  variant,
}: {
  user: CurrentUser;
  variant: "cpl" | "cd" | "rvp";
}) {
  const r = teamTargetRollupFor(user);
  const role =
    variant === "cpl" ? "CountryProgramLead" :
    variant === "cd"  ? "CountryDirector"    :
                        "Admin"; // RVP demo
  const notes = notificationsForRole(role).slice(0, 2);

  const subtitle =
    variant === "cpl" ? "Early-warning + support-first review across your team" :
    variant === "cd"  ? "Country-level target risk with reviewed support reports" :
                        "Country comparison + escalations after support review";

  return (
    <section className="card p-3.5">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-7 h-7 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]">
          <Target size={14} />
        </span>
        <div className="leading-tight">
          <h3 className="text-[13px] font-bold">Team Targets · Early Warning</h3>
          <div className="text-caption muted">{subtitle}</div>
        </div>
        <Link
          href="/team-targets"
          className="ml-auto inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--color-edify-primary)]"
        >
          Open Team Targets
          <ArrowRight size={11} />
        </Link>
      </div>

      <div className="grid grid-cols-5 gap-2.5 mb-3">
        <Tile label="Staff visible"           value={r.totalStaff} />
        <Tile label="On track"                value={r.onTrack}       tone="emerald" />
        <Tile label="High risk"               value={r.highRisk}      tone="amber" />
        <Tile label="Critical"                value={r.critical}      tone="rose" />
        <Tile label="Mid-year support cases"  value={r.midYearBelow40Cases} tone="violet" />
      </div>

      {variant === "rvp" && (
        <div className="rounded-lg border border-[var(--color-edify-border)] p-2.5 mb-3">
          <div className="text-[11px] muted font-semibold uppercase mb-1.5">Country comparison</div>
          <div className="space-y-1 text-[12px]">
            {countryTargetRollups.map((c) => (
              <div key={c.country} className="grid grid-cols-[80px_1fr_auto] items-center gap-2">
                <span className="font-semibold">{c.country}</span>
                <div className="h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div
                    className={cn(
                      "h-full rounded-full",
                      c.teamTargetAchievement >= 75 ? "bg-emerald-500" :
                      c.teamTargetAchievement >= 60 ? "bg-amber-500"   :
                                                       "bg-rose-500",
                    )}
                    style={{ width: `${c.teamTargetAchievement}%` }}
                  />
                </div>
                <span className="text-[11.5px] tabular muted">{c.teamTargetAchievement}% · {c.midYearBelow40} mid-year</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="space-y-1.5">
        {notes.map((n) => (
          <div key={n.id} className="flex items-start gap-2 px-2.5 py-1.5 rounded-lg border border-[var(--color-edify-border)] bg-white text-[11.5px]">
            {n.kind === "mid-year" ? (
              <ShieldCheck size={12} className="text-emerald-700 mt-0.5 shrink-0" />
            ) : (
              <AlertTriangle size={12} className="text-amber-700 mt-0.5 shrink-0" />
            )}
            <div className="min-w-0">
              <div className="font-semibold">{n.title}</div>
              <div className="muted">{n.body}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-2 pt-2 border-t border-[#eef2f4] text-caption muted leading-snug">
        Support-first design: PIP escalation is gated until a support review report is complete.
      </div>
    </section>
  );
}

function Tile({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "emerald" | "amber" | "rose" | "violet";
}) {
  const cls =
    tone === "emerald" ? "text-emerald-700" :
    tone === "amber"   ? "text-amber-700"   :
    tone === "rose"    ? "text-rose-700"    :
    tone === "violet"  ? "text-violet-700"  :
                         "text-[var(--color-edify-text)]";
  return (
    <div className="rounded-lg border border-[var(--color-edify-border)] p-2.5 overflow-hidden">
      <div className="text-[10px] muted font-semibold leading-tight line-clamp-2 min-h-[24px]">{label}</div>
      <div className={`text-[18px] font-extrabold tabular leading-none mt-1.5 truncate ${cls}`}>{value}</div>
    </div>
  );
}

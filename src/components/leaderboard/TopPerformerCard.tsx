"use client";

// Top Performer Recognition Card.
//
// Two recognitions, surfaced per visibility rules:
//   • Best Performing CCEO    — visible on CCEO, CPL, CD, RVP, HR (everywhere
//                                except the Program Accountant + Impact
//                                Assessment dashboards).
//   • Best Performing Program Lead — visible on CD, RVP, HR.
//
// Tone: motivational. Always shows verified work only — never raw counts.

import Link from "next/link";
import { Trophy, Crown, Award, ArrowRight, type LucideIcon } from "lucide-react";
import { overallMonthlyLeaders, programLeadLeaderboard } from "@/lib/leaderboard-mock";
import { cn } from "@/lib/utils";

type Audience = "cceo" | "cpl" | "cd" | "rvp" | "hr";

export function TopPerformerCard({
  audience,
  show = "both",
}: {
  audience: Audience;
  /** Which slices to render. */
  show?:    "ccoo-only" | "pl-only" | "both";
}) {
  const showCceo = show !== "pl-only";
  const showPl   = show !== "ccoo-only";

  // Top CCEO is everywhere except Accountant + IA — but this card is opt-in
  // per dashboard so we don't need to gate here. We do hide the PL slice if
  // the audience isn't allowed to see it.
  const plAllowed = audience === "cd" || audience === "rvp" || audience === "hr";

  const topCceo = overallMonthlyLeaders[0];
  const topPl   = programLeadLeaderboard[0];

  if ((!showCceo || !topCceo) && (!showPl || !topPl || !plAllowed)) return null;

  const renderPl = showPl && topPl && plAllowed;
  const grid = showCceo && renderPl ? "lg:grid-cols-2" : "lg:grid-cols-1";

  return (
    <section className="card p-3.5 space-y-3 bg-gradient-to-br from-amber-50/40 via-white to-[var(--color-edify-soft)]/30 border-amber-200/60">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <h3 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
            <Trophy size={15} className="text-amber-600" />
            This Month&apos;s top performers
          </h3>
          <p className="text-caption muted mt-0.5">Verified work only · leave, route load, and approval delays are factored before any recognition.</p>
        </div>
        <Link
          href="/leaderboard"
          className="text-[11px] font-extrabold text-[var(--color-edify-primary)] inline-flex items-center gap-1 hover:underline"
        >
          Open leaderboard <ArrowRight size={11} />
        </Link>
      </header>

      <div className={cn("grid grid-cols-1 gap-3", grid)}>
        {showCceo && topCceo && (
          <Tile
            Icon={Crown}
            label="Best Performing CCEO"
            primaryName={topCceo.staffName}
            initials={topCceo.initials}
            region={topCceo.region}
            badge={topCceo.recognitionBadge ?? "Monthly Champion"}
            scoreLabel="Verified achievement"
            scoreValue={`${topCceo.achievementPercent}%`}
            stats={[
              { label: "Verified",    value: `${topCceo.verifiedCompleted}/${topCceo.targetValue}` },
              { label: "Salesforce",  value: `${topCceo.salesforceCompliancePercent}%` },
              { label: "Pass rate",   value: `${topCceo.verificationPassRate}%` },
            ]}
            tone="amber"
          />
        )}
        {renderPl && (
          <Tile
            Icon={Award}
            label="Best Performing Program Lead"
            primaryName={topPl!.programLeadName}
            initials={topPl!.initials}
            region={topPl!.region}
            badge={topPl!.recognitionBadge}
            scoreLabel="Overall PL score"
            scoreValue={`${topPl!.overallProgramLeadScore}`}
            stats={[
              { label: "Team target",      value: `${topPl!.teamTargetAchievement}%` },
              { label: "Staff on track",   value: `${topPl!.staffOnTrackPercent}%` },
              { label: "Verification",     value: `${topPl!.verificationPassRate}%` },
            ]}
            tone="violet"
          />
        )}
      </div>
    </section>
  );
}

function Tile({
  Icon, label, primaryName, initials, region, badge,
  scoreLabel, scoreValue, stats, tone,
}: {
  Icon:         LucideIcon;
  label:        string;
  primaryName:  string;
  initials:     string;
  region:       string;
  badge:        string;
  scoreLabel:   string;
  scoreValue:   string;
  stats:        { label: string; value: string }[];
  tone:         "amber" | "violet";
}) {
  const TONE = tone === "amber"
    ? {
        avatar: "bg-gradient-to-br from-amber-400 to-amber-600 text-white",
        badge:  "bg-amber-100 text-amber-800 border-amber-200",
        score:  "text-amber-700",
      }
    : {
        avatar: "bg-gradient-to-br from-violet-500 to-violet-700 text-white",
        badge:  "bg-violet-100 text-violet-800 border-violet-200",
        score:  "text-violet-700",
      };

  return (
    <div className="rounded-2xl border border-[var(--color-edify-border)] bg-white p-4 h-full flex flex-col gap-3">
      <header className="flex items-center gap-3">
        <span className={cn("h-12 w-12 rounded-2xl grid place-items-center text-body-lg font-extrabold shrink-0 shadow-sm", TONE.avatar)}>
          {initials}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-extrabold uppercase tracking-[0.14em] muted inline-flex items-center gap-1.5">
            <Icon size={11} className={tone === "amber" ? "text-amber-600" : "text-violet-600"} />
            {label}
          </div>
          <div className="text-[16px] font-extrabold tracking-tight truncate">{primaryName}</div>
          <div className="text-caption muted truncate">{region}</div>
        </div>
        <div className="text-right shrink-0">
          <div className={cn("text-[20px] font-extrabold tabular leading-none tracking-tight", TONE.score)}>{scoreValue}</div>
          <div className="text-[10px] muted mt-0.5">{scoreLabel}</div>
        </div>
      </header>

      <div>
        <span className={cn("inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-caption font-extrabold whitespace-nowrap border", TONE.badge)}>
          <Trophy size={10} />
          {badge}
        </span>
      </div>

      <ul className="grid grid-cols-3 gap-2 mt-auto">
        {stats.map((s) => (
          <li key={s.label} className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 px-2.5 py-1.5">
            <div className="text-[9.5px] muted font-bold uppercase tracking-wide truncate">{s.label}</div>
            <div className="text-body font-extrabold tabular leading-tight truncate">{s.value}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

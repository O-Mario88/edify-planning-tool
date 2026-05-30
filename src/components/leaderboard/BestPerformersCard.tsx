// Best Performers — role-aware recognition card.
//
// One component, four audiences. Every dashboard that mounts it gets the
// recognition tiles its role is allowed to see; the gating + data shaping
// live entirely in `bestPerformersFor()` (lib/leaderboard-mock). This file
// is a pure renderer — no hooks, so it works as a server component.
//
//   • cpl → your team's top CCEO + top CCEO on other teams
//   • cd  → best Program Lead, best CCEO, SSA leader (CCEO + PL)
//   • rvp → best Country Director, Program Lead, CCEO
//   • hr  → best team (Program Lead) + most improved staff

import Link from "next/link";
import {
  Trophy,
  Crown,
  Award,
  Globe2,
  TrendingUp,
  ArrowRight,
  type LucideIcon,
} from "lucide-react";
import {
  bestPerformersFor,
  type BestPerformersAudience,
  type BestPerformerTile,
  type BestPerformerKind,
  type BestPerformerTone,
} from "@/lib/leaderboard-mock";
import type { CurrentUser } from "@/lib/schools-mock";
import { cn } from "@/lib/utils";

const TONE: Record<
  BestPerformerTone,
  { avatar: string; badge: string; score: string; icon: string }
> = {
  amber: {
    avatar: "bg-gradient-to-br from-amber-400 to-amber-600 text-white",
    badge: "bg-amber-100 text-amber-800 border-amber-200",
    score: "text-amber-700",
    icon: "text-amber-600",
  },
  violet: {
    avatar: "bg-gradient-to-br from-violet-500 to-violet-700 text-white",
    badge: "bg-violet-100 text-violet-800 border-violet-200",
    score: "text-violet-700",
    icon: "text-violet-600",
  },
  emerald: {
    avatar: "bg-gradient-to-br from-emerald-500 to-emerald-700 text-white",
    badge: "bg-emerald-100 text-emerald-800 border-emerald-200",
    score: "text-emerald-700",
    icon: "text-emerald-600",
  },
  sky: {
    avatar: "bg-gradient-to-br from-sky-500 to-sky-700 text-white",
    badge: "bg-sky-100 text-sky-800 border-sky-200",
    score: "text-sky-700",
    icon: "text-sky-600",
  },
};

const KIND_ICON: Record<BestPerformerKind, LucideIcon> = {
  cceo: Crown,
  pl: Award,
  cd: Globe2,
  improved: TrendingUp,
};


export function BestPerformersCard({
  audience,
  user,
}: {
  audience: BestPerformersAudience;
  user?: CurrentUser;
}) {
  const panel = bestPerformersFor(audience, user);
  if (panel.tiles.length === 0) return null;

  return (
    <section className="card p-3.5 space-y-3 bg-gradient-to-br from-amber-50/40 via-white to-[var(--color-edify-soft)]/30 border-amber-200/60">
      <header className="flex items-baseline justify-between gap-2 flex-wrap">
        <div>
          <h3 className="text-[15px] font-extrabold tracking-tight inline-flex items-center gap-2">
            <Trophy size={15} className="text-amber-600" />
            {panel.title}
          </h3>
          <p className="text-caption muted mt-0.5">{panel.subtitle}</p>
        </div>
        <Link
          href="/leaderboard"
          className="text-[11px] font-extrabold text-[var(--color-edify-primary)] inline-flex items-center gap-1 hover:underline"
        >
          Open leaderboard <ArrowRight size={11} />
        </Link>
      </header>

      {/* The recognition tile is content-rich (avatar + name + score +
          badge + 3 stats), so it needs room. Everything renders in a
          2-column grid; a 3-tile panel features its first tile full
          width so no name truncates in a cramped third column. */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {panel.tiles.map((tile, i) => (
          <Tile
            key={tile.key}
            tile={tile}
            className={
              panel.tiles.length === 3 && i === 0 ? "sm:col-span-2" : undefined
            }
          />
        ))}
      </div>
    </section>
  );
}

function Tile({
  tile,
  className,
}: {
  tile: BestPerformerTile;
  className?: string;
}) {
  const tone = TONE[tile.tone];
  const Icon = KIND_ICON[tile.kind];

  return (
    <div
      className={cn(
        "rounded-2xl border border-[var(--color-edify-border)] bg-white p-4 h-full flex flex-col gap-3",
        className,
      )}
    >
      <header className="flex items-center gap-3">
        <span
          className={cn(
            "h-12 w-12 rounded-2xl grid place-items-center text-body-lg font-extrabold shrink-0 shadow-sm",
            tone.avatar,
          )}
        >
          {tile.initials}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-[10px] font-extrabold uppercase tracking-[0.14em] muted inline-flex items-center gap-1.5">
            <Icon size={11} className={tone.icon} />
            <span className="truncate">{tile.roleLabel}</span>
          </div>
          <div className="text-[16px] font-extrabold tracking-tight truncate">
            {tile.name}
          </div>
          <div className="text-caption muted truncate">{tile.context}</div>
        </div>
        <div className="text-right shrink-0">
          <div
            className={cn(
              "text-[20px] font-extrabold tabular leading-none tracking-tight",
              tone.score,
            )}
          >
            {tile.scoreValue}
          </div>
          <div className="text-[10px] muted mt-0.5">{tile.scoreLabel}</div>
        </div>
      </header>

      <div>
        <span
          className={cn(
            "inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-caption font-extrabold whitespace-nowrap border",
            tone.badge,
          )}
        >
          <Trophy size={10} />
          {tile.badge}
        </span>
      </div>

      <ul className="grid grid-cols-3 gap-2 mt-auto">
        {tile.stats.map((s) => (
          <li
            key={s.label}
            className="rounded-lg border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/30 px-2.5 py-1.5 overflow-hidden"
          >
            <div className="text-[9.5px] muted font-bold uppercase tracking-wide leading-tight">
              {s.label}
            </div>
            <div className="text-body font-extrabold tabular leading-tight truncate">
              {s.value}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

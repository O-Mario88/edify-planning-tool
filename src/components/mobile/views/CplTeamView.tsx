"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Search,
  SlidersHorizontal,
  ChevronRight,
  ChevronDown,
  Target,
  Calendar,
  CheckCircle2,
  ArrowUpRight,
  ArrowDownRight,
  TrendingUp,
  AlertTriangle,
  type LucideIcon,
} from "lucide-react";
import { MobileShell } from "@/components/mobile/MobileShell";
import { CplBottomNav } from "@/components/mobile/CplBottomNav";
import { MobileTopBar } from "@/components/mobile/MobileTopBar";
import { ProgressRing } from "@/components/ui/primitives";
import {
  cplMyTeam,
  cplTeamProgress,
  cplMyTargetsSummary,
  cplTeamTargetBreakdown,
  type CplTeamMember,
  type CplMemberContribution,
} from "@/lib/cpl-mock";
import { cn } from "@/lib/utils";

const TABS = ["My Team", "Regions", "Targets"] as const;
type Tab = (typeof TABS)[number];

const STATUS_TONE: Record<CplTeamMember["status"], string> = {
  "On Track": "text-emerald-600",
  "At Risk":  "text-amber-600",
  "Behind":   "text-rose-600",
};

const ROUTE_BG: Record<CplTeamMember["routeStatus"], string> = {
  Normal: "bg-emerald-50 text-emerald-700 border border-emerald-200",
  High:   "bg-amber-50 text-amber-700 border border-amber-200",
};

const TARGET_ICON: Record<"target" | "calendar" | "checkCircle", LucideIcon> = {
  target:      Target,
  calendar:    Calendar,
  checkCircle: CheckCircle2,
};

export function CplTeamView() {
  const [tab, setTab] = useState<Tab>("My Team");
  const [query, setQuery] = useState("");

  const filtered = cplMyTeam.filter((m) =>
    m.name.toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <MobileShell>
      <MobileTopBar title="My Team Performance" backHref="/dashboards/cpl" />
      {/* Tabs */}
      <div
        className="px-3 pt-3 pb-3 grid grid-cols-3 gap-1.5 text-white"
        style={{ backgroundImage: "linear-gradient(180deg, #0e1c2c 0%, #0a1623 100%)" }}
      >
        {TABS.map((t) => (
          <button
            key={t}
            type="button"
            onClick={() => setTab(t)}
            className={cn(
              "h-9 rounded-md text-[12px] font-extrabold tracking-tight",
              t === tab
                ? "bg-[var(--color-edify-primary)] text-white"
                : "bg-white/[.08] text-white/85 hover:bg-white/[.12]",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      <main className="flex-1 px-3 pt-3 pb-4 space-y-3 bg-[var(--color-page)]">
        {/* Search */}
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-edify-muted)]"
            />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search team member"
              aria-label="Search team member"
              className="w-full pl-9 pr-3 h-10 rounded-xl border border-[var(--color-edify-border)] bg-white text-body placeholder:text-[var(--color-edify-muted)] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
            />
          </div>
          <button
            type="button"
            aria-label="Filter"
            className="h-10 w-10 rounded-xl border border-[var(--color-edify-border)] bg-white grid place-items-center"
          >
            <SlidersHorizontal size={14} className="text-[var(--color-edify-muted)]" />
          </button>
        </div>

        {tab === "My Team" && (
          <>
            {/* Donut summary */}
            <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 shadow-sm">
              <div className="flex items-baseline justify-between mb-2 px-0.5">
                <h3 className="text-body font-extrabold tracking-tight">Overall Team Progress</h3>
                <span className="text-caption muted">({cplTeamProgress.monthLabel})</span>
              </div>
              <div className="flex items-center gap-3">
                <div className="relative shrink-0" style={{ width: 96, height: 96 }}>
                  <ProgressRing
                    pct={cplTeamProgress.donutPct}
                    size={96}
                    stroke={9}
                    color="#10b981"
                  />
                  <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
                    <div className="text-[20px] font-extrabold tabular leading-none">
                      {cplTeamProgress.donutPct}%
                    </div>
                    <div className="text-[9.5px] muted mt-0.5">On Track</div>
                  </div>
                </div>
                <ul className="flex-1 text-[11.5px] space-y-1.5">
                  <SummaryRow color="#10b981" label="On Track" count={cplTeamProgress.onTrack.count} pct={cplTeamProgress.onTrack.pct} />
                  <SummaryRow color="#f59e0b" label="At Risk"  count={cplTeamProgress.atRisk.count}  pct={cplTeamProgress.atRisk.pct} />
                  <SummaryRow color="#ef4444" label="Behind"   count={cplTeamProgress.behind.count}  pct={cplTeamProgress.behind.pct} />
                  <li className="pt-1.5 border-t border-[#eef2f4] flex items-center justify-between">
                    <span className="muted">Total CCEOs</span>
                    <span className="font-extrabold tabular">{cplTeamProgress.totalCceos}</span>
                  </li>
                </ul>
              </div>
            </section>

            {/* Member rows */}
            <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] divide-y divide-[var(--color-edify-divider)] shadow-sm">
              {filtered.map((m) => (
                <Link
                  key={m.id}
                  href="/notifications"
                  className="flex items-center gap-2.5 px-3 py-2.5 active:bg-[var(--color-edify-soft)]/40"
                >
                  <div className="h-9 w-9 rounded-full bg-[var(--color-edify-primary)] text-white text-[11px] font-extrabold grid place-items-center shrink-0">
                    {m.initials}
                  </div>
                  <div className="min-w-0 w-[88px]">
                    <div className="text-body font-extrabold tracking-tight truncate">{m.name}</div>
                    <div className="text-caption muted">{m.role}</div>
                  </div>
                  <div className="text-center w-[52px]">
                    <div className="text-body-lg font-extrabold tabular leading-none">{m.achievementPct}%</div>
                    <div className={cn("text-[9.5px] font-semibold mt-0.5", STATUS_TONE[m.status])}>
                      {m.status}
                    </div>
                  </div>
                  <div className="text-center w-[40px]">
                    <div className="text-body-lg font-extrabold tabular leading-none">{m.backlog}</div>
                    <div className="text-[9px] muted mt-0.5">Backlog</div>
                  </div>
                  <div className={cn("ml-auto px-1.5 py-0.5 rounded-md text-[9.5px] font-extrabold leading-tight text-center", ROUTE_BG[m.routeStatus])}>
                    <div>{m.routeBadge}</div>
                    <div className="font-semibold">{m.routeStatus}</div>
                  </div>
                  <ChevronRight size={12} className="text-[var(--color-edify-muted)] shrink-0" />
                </Link>
              ))}
              {filtered.length === 0 && (
                <div className="px-3 py-6 text-[12px] muted text-center">No team members match.</div>
              )}
            </section>

            {/* My Targets footer */}
            <section className="rounded-2xl bg-white border border-[var(--color-edify-border)] p-3 shadow-sm">
              <div className="flex items-center justify-between mb-2 px-0.5">
                <div className="flex items-baseline gap-1.5">
                  <h3 className="text-body font-extrabold tracking-tight">My Targets</h3>
                  <span className="text-caption muted">({cplMyTargetsSummary.monthLabel})</span>
                </div>
                <Link
                  href="/my-targets"
                  className="text-[11px] font-semibold text-emerald-600 inline-flex items-center gap-0.5"
                >
                  View Details
                  <ChevronRight size={11} />
                </Link>
              </div>
              <div className="grid grid-cols-3 gap-2">
                <TargetTile
                  Icon={TARGET_ICON.target}
                  label="Quarterly Progress"
                  value={`${cplMyTargetsSummary.quarterly.pct}%`}
                  caption={cplMyTargetsSummary.quarterly.status}
                />
                <TargetTile
                  Icon={TARGET_ICON.calendar}
                  label="Monthly Progress"
                  value={`${cplMyTargetsSummary.monthly.pct}%`}
                  caption={cplMyTargetsSummary.monthly.status}
                />
                <TargetTile
                  Icon={TARGET_ICON.checkCircle}
                  label="Approvals Completed"
                  value={`${cplMyTargetsSummary.approvals.count}`}
                  caption={cplMyTargetsSummary.approvals.label}
                />
              </div>
            </section>
          </>
        )}

        {tab === "Regions" && <ComingSoon what="Regional rollups" />}
        {tab === "Targets" && <TargetsBreakdown query={query} />}
      </main>

      <CplBottomNav />
    </MobileShell>
  );
}

function SummaryRow({ color, label, count, pct }: { color: string; label: string; count: number; pct: number }) {
  return (
    <li className="flex items-center gap-2">
      <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: color }} />
      <span className="flex-1">{label}</span>
      <span className="font-extrabold tabular">{count}</span>
      <span className="muted tabular w-[44px] text-right">({pct}%)</span>
    </li>
  );
}

function TargetTile({
  Icon,
  label,
  value,
  caption,
}: {
  Icon: LucideIcon;
  label: string;
  value: string;
  caption: string;
}) {
  return (
    <div className="rounded-xl bg-[var(--color-edify-soft)]/40 border border-[var(--color-edify-border)] p-2 text-center">
      <span className="w-7 h-7 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center mx-auto">
        <Icon size={13} />
      </span>
      <div className="text-[9.5px] muted font-semibold leading-tight mt-1 line-clamp-2 min-h-[24px]">
        {label}
      </div>
      <div className="text-[16px] font-extrabold tabular leading-none mt-1">{value}</div>
      <div className="text-[9.5px] font-semibold text-emerald-600 mt-0.5">{caption}</div>
    </div>
  );
}

function ComingSoon({ what }: { what: string }) {
  return (
    <div className="rounded-2xl bg-white border border-dashed border-[var(--color-edify-border)] p-6 text-center text-[12px] muted">
      {what} — coming next.
    </div>
  );
}

// ── Per-team target breakdown ──────────────────────────────────────────

const STATUS_BAR_COLOR: Record<CplMemberContribution["status"], string> = {
  "On Track": "#10b981",
  "At Risk":  "#f59e0b",
  "Behind":   "#ef4444",
};

const STATUS_TEXT_COLOR: Record<CplMemberContribution["status"], string> = {
  "On Track": "text-emerald-600",
  "At Risk":  "text-amber-600",
  "Behind":   "text-rose-600",
};

function TargetsBreakdown({ query }: { query: string }) {
  const [expandedKey, setExpandedKey] = useState<string | null>(cplTeamTargetBreakdown[0]?.key ?? null);
  const q = query.trim().toLowerCase();

  return (
    <section className="space-y-2.5">
      {cplTeamTargetBreakdown.map((target) => {
        const isOpen = expandedKey === target.key;
        const filteredMembers = q
          ? target.members.filter((m) => m.name.toLowerCase().includes(q))
          : target.members;
        const top = target.members.find((m) => m.memberId === target.topContributorId);
        const lag = target.members.find((m) => m.memberId === target.laggingMemberId);
        return (
          <article
            key={target.key}
            className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm overflow-hidden"
          >
            <button
              type="button"
              onClick={() => setExpandedKey(isOpen ? null : target.key)}
              className="w-full px-3 py-3 flex items-center gap-3 text-left active:bg-[var(--color-edify-soft)]/40"
              aria-expanded={isOpen ? "true" : "false"}
            >
              <div className="flex-1 min-w-0">
                <div className="text-body font-extrabold tracking-tight">{target.label}</div>
                <div className="text-caption muted">
                  {target.totalAchieved} / {target.totalTarget} {target.unit}
                </div>
                <div className="mt-1.5 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
                  <div
                    className="h-full"
                    style={{
                      width: `${Math.min(100, target.achievedPct)}%`,
                      backgroundColor: "var(--color-edify-primary)",
                    }}
                  />
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="text-[18px] font-extrabold tabular leading-none">{target.achievedPct}%</div>
                <div
                  className={cn(
                    "text-[10px] font-semibold mt-0.5 inline-flex items-center gap-0.5 justify-end",
                    target.trend === "up" ? "text-emerald-600" : "text-rose-600",
                  )}
                >
                  {target.trend === "up" ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                  {target.trendDelta}
                </div>
              </div>
              <ChevronDown
                size={16}
                className={cn(
                  "text-[var(--color-edify-muted)] shrink-0 transition-transform",
                  isOpen && "rotate-180",
                )}
              />
            </button>

            {isOpen && (
              <div className="px-3 pb-3 space-y-2.5 border-t border-[#eef2f4] pt-2.5">
                {/* Top / lagging callout */}
                <div className="grid grid-cols-2 gap-2">
                  {top && (
                    <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-2 flex items-start gap-2">
                      <span className="h-7 w-7 rounded-full bg-emerald-600 text-white text-[10px] font-extrabold grid place-items-center shrink-0">
                        {top.initials}
                      </span>
                      <div className="min-w-0">
                        <div className="text-[10px] font-semibold text-emerald-700 inline-flex items-center gap-1">
                          <TrendingUp size={10} />
                          Top contributor
                        </div>
                        <div className="text-[12px] font-extrabold tracking-tight truncate">{top.name}</div>
                        <div className="text-caption muted">
                          {top.achieved}/{top.target} · {top.pct}%
                        </div>
                      </div>
                    </div>
                  )}
                  {lag && (
                    <div className="rounded-xl bg-rose-50 border border-rose-200 p-2 flex items-start gap-2">
                      <span className="h-7 w-7 rounded-full bg-rose-600 text-white text-[10px] font-extrabold grid place-items-center shrink-0">
                        {lag.initials}
                      </span>
                      <div className="min-w-0">
                        <div className="text-[10px] font-semibold text-rose-700 inline-flex items-center gap-1">
                          <AlertTriangle size={10} />
                          Needs support
                        </div>
                        <div className="text-[12px] font-extrabold tracking-tight truncate">{lag.name}</div>
                        <div className="text-caption muted">
                          {lag.achieved}/{lag.target} · {lag.pct}%
                        </div>
                      </div>
                    </div>
                  )}
                </div>

                {/* Per-member rows */}
                <div className="space-y-1.5">
                  {filteredMembers.length === 0 && (
                    <div className="px-1 py-3 text-[12px] muted text-center">No members match your search.</div>
                  )}
                  {filteredMembers.map((m) => (
                    <MemberContributionRow key={m.memberId} m={m} />
                  ))}
                </div>
              </div>
            )}
          </article>
        );
      })}
    </section>
  );
}

function MemberContributionRow({ m }: { m: CplMemberContribution }) {
  const widthPct = Math.min(100, m.pct);
  return (
    <div className="flex items-center gap-2.5">
      <div className="h-7 w-7 rounded-full bg-[var(--color-edify-primary)] text-white text-[10px] font-extrabold grid place-items-center shrink-0">
        {m.initials}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[11.5px] font-extrabold tracking-tight truncate">{m.name}</div>
          <div className="text-caption muted tabular shrink-0">
            {m.achieved}/{m.target}
          </div>
        </div>
        <div className="mt-1 h-1.5 rounded-full bg-[#eef2f4] overflow-hidden">
          <div
            className="h-full"
            style={{ width: `${widthPct}%`, backgroundColor: STATUS_BAR_COLOR[m.status] }}
          />
        </div>
      </div>
      <div className="text-right shrink-0 w-[44px]">
        <div className="text-[12px] font-extrabold tabular leading-none">{m.pct}%</div>
        <div className={cn("text-[9px] font-semibold mt-0.5", STATUS_TEXT_COLOR[m.status])}>
          {m.status}
        </div>
      </div>
    </div>
  );
}

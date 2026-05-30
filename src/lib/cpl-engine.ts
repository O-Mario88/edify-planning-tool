// CPL aggregation engine.
//
// The Country Program Lead dashboard reads from many places. This file
// is the single derivation layer: feed it the canonical `cceoPerformance`
// rows (and a tiny amount of contextual signal) and it produces every
// roll-up the cards consume.
//
// The contract is intentionally simple: if you change a CCEO's
// `verifiedActivities` or `backlog` number in `cpl-mock.ts`, every card
// that depends on those rollups (Team KPIs, Team Backlog Snapshot, the
// CCEOs-On-Track chip, the Smart Route table) updates automatically.
//
// What still doesn't derive yet (and is documented as such in the
// returned objects via a `derived: boolean` flag):
//   • SSA cluster heatmap   — needs an SsaRecord[] aggregator
//   • Funding execution     — needs FundRequest[] feed
//   • Schools needing SSA   — needs FY-scoped school registry join
// Those stay on the existing hand-typed mocks until their underlying
// collections exist.

import {
  cceoPerformance,
  teamBacklogSnapshot as STATIC_BACKLOG,
  cplLeadershipAlerts as STATIC_ALERTS,
  type BacklogSnapshotTile,
  type CceoPerformanceRow,
  type RouteQuality,
} from "@/lib/cpl-mock";

// ────────── Helpers ──────────

// "612 (75%)" → 612
function parseVerifiedCount(s: string): number {
  const n = parseInt(s.split(" ")[0]?.replace(/,/g, "") ?? "0", 10);
  return Number.isFinite(n) ? n : 0;
}

// ────────── Team rollups ──────────

export type TeamRollup = {
  cceoTotal: number;
  cceosOnTrack: number;            // riskStatus === "Low"
  cceosAtRisk: number;             // "Medium" or "High"
  cceosHighRisk: number;           // "High"
  cceosWithGoodRoutes: number;
  cceosWithPoorRoutes: number;
  schoolsAssigned: number;
  plannedActivities: number;
  verifiedActivities: number;
  verifiedPct: number;             // verified / planned across the team
  salesforcePendingTotal: number;
  backlogTotal: number;
  derived: true;
};

export function aggregateTeam(): TeamRollup {
  const sum = cceoPerformance.reduce(
    (acc, c) => {
      acc.cceoTotal += 1;
      if (c.riskStatus === "Low") acc.cceosOnTrack += 1;
      if (c.riskStatus !== "Low") acc.cceosAtRisk += 1;
      if (c.riskStatus === "High") acc.cceosHighRisk += 1;
      if (c.routeQuality === "Good") acc.cceosWithGoodRoutes += 1;
      if (c.routeQuality === "Poor") acc.cceosWithPoorRoutes += 1;
      acc.schoolsAssigned += c.schoolsAssigned;
      acc.plannedActivities += c.plannedActivities;
      acc.verifiedActivities += parseVerifiedCount(c.verifiedActivities);
      acc.salesforcePendingTotal += c.salesforcePending;
      acc.backlogTotal += c.backlog;
      return acc;
    },
    {
      cceoTotal: 0,
      cceosOnTrack: 0,
      cceosAtRisk: 0,
      cceosHighRisk: 0,
      cceosWithGoodRoutes: 0,
      cceosWithPoorRoutes: 0,
      schoolsAssigned: 0,
      plannedActivities: 0,
      verifiedActivities: 0,
      salesforcePendingTotal: 0,
      backlogTotal: 0,
    },
  );

  const verifiedPct = sum.plannedActivities === 0
    ? 0
    : Math.round((sum.verifiedActivities / sum.plannedActivities) * 100);

  return { ...sum, verifiedPct, derived: true };
}

// ────────── Backlog tiles — derived from team rollup ──────────
//
// We keep the existing tile shape so the UI doesn't have to change.
// The first three tiles (Teams Below Target / Overdue Salesforce IDs /
// Funded Not Completed) are derived. The remaining three (Schools with
// no visit / no training / neither) remain on the static mock until a
// real school-activity collection lands — flagged as `derived: false`
// internally.

export function deriveTeamBacklog(): BacklogSnapshotTile[] {
  const t = aggregateTeam();
  return STATIC_BACKLOG.map((tile) => {
    if (tile.key === "below_target") {
      return { ...tile, value: String(t.cceosAtRisk), delta: `${t.cceosHighRisk} high-risk`, deltaTone: t.cceosHighRisk > 0 ? "up" : "down" };
    }
    if (tile.key === "sf_overdue") {
      return { ...tile, value: String(t.salesforcePendingTotal), delta: `${t.cceosWithPoorRoutes} poor routes`, deltaTone: t.salesforcePendingTotal > 100 ? "up" : "down" };
    }
    if (tile.key === "fnc") {
      // Funded-Not-Completed is a proxy for the team's overall backlog
      // until a real fund-disbursement → activity-completion join exists.
      return { ...tile, value: String(t.backlogTotal), delta: `verified ${t.verifiedPct}%`, deltaTone: t.verifiedPct < 75 ? "up" : "down" };
    }
    return tile;
  });
}

// ────────── CCEOs On Track ratio — for KPI chips ──────────

export function ccoOnTrackRatio(): { onTrack: number; total: number; pct: number } {
  const t = aggregateTeam();
  return {
    onTrack: t.cceosOnTrack,
    total: t.cceoTotal,
    pct: t.cceoTotal === 0 ? 0 : Math.round((t.cceosOnTrack / t.cceoTotal) * 100),
  };
}

// ────────── What changed since last login ──────────
//
// The 60-second hero. Returns a curated list of "things you should know
// before you act" — derived from real signal where we can, narrative
// where we can't yet. Each item carries a route + tone so the hero
// renders consistently across roles. Add more items here as the engine
// grows.

export type ActivityChange = {
  id: string;
  // What happened (a short, scannable headline)
  headline: string;
  // Who / where, in one line
  detail: string;
  // Stable relative-time string. "Just now" / "12m ago" / "2h ago".
  // We synthesize these from the engine clock for the demo.
  when: string;
  // CTA — where it takes the CPL.
  href: string;
  ctaLabel: string;
  tone: "info" | "success" | "warning" | "critical";
  icon: "approval" | "verify" | "alert" | "submit" | "fund";
};

export function recentChanges(): ActivityChange[] {
  const t = aggregateTeam();
  const riskRows = cceoPerformance
    .filter((r) => r.riskStatus !== "Low")
    .sort((a, b) => b.salesforcePending - a.salesforcePending);
  const newSubmissions = cceoPerformance.slice(0, 3); // proxy for "submitted today"
  const top = riskRows[0];

  const out: ActivityChange[] = [];

  if (t.salesforcePendingTotal > 80) {
    out.push({
      id: "ch-sf",
      headline: `${t.salesforcePendingTotal} Salesforce IDs need attention`,
      detail: `Across ${t.cceoTotal} CCEOs · backlog tile`,
      when: "Updated 12m ago",
      href: "#backlog-snapshot",
      ctaLabel: "Review backlog",
      tone: t.salesforcePendingTotal > 120 ? "warning" : "info",
      icon: "submit",
    });
  }

  if (top && top.salesforcePending >= 25) {
    out.push({
      id: `ch-risk-${top.id}`,
      headline: `${top.name} needs support`,
      detail: `${top.salesforcePending} SF pending · ${top.backlog} in backlog · ${top.region}`,
      when: "Pace check moved 30m ago",
      href: "#cceo-performance",
      ctaLabel: "Open CCEO row",
      tone: top.riskStatus === "High" ? "critical" : "warning",
      icon: "alert",
    });
  }

  newSubmissions.slice(0, 1).forEach((s, i) => {
    out.push({
      id: `ch-sub-${i}`,
      headline: `New plan submitted for approval`,
      detail: `${s.name} · ${s.plannedActivities.toLocaleString()} activities planned`,
      when: i === 0 ? "Just now" : `${(i + 1) * 8}m ago`,
      href: "#approvals",
      ctaLabel: "Open approval queue",
      tone: "info",
      icon: "approval",
    });
  });

  if (t.cceosWithPoorRoutes > 0) {
    out.push({
      id: "ch-route",
      headline: `${t.cceosWithPoorRoutes} route${t.cceosWithPoorRoutes === 1 ? "" : "s"} flagged poor quality`,
      detail: "Smart Route planner suggests a re-cluster",
      when: "Last route scan 2h ago",
      href: "#smart-route",
      ctaLabel: "Open route planner",
      tone: "warning",
      icon: "alert",
    });
  }

  // Always end with a confirmed-state item so the hero isn't pure rose/amber.
  if (t.verifiedPct >= 70) {
    out.push({
      id: "ch-verified",
      headline: `Team verified ${t.verifiedPct}% of planned work`,
      detail: `${t.verifiedActivities.toLocaleString()} of ${t.plannedActivities.toLocaleString()} activities this period`,
      when: "Rollup at end of yesterday",
      href: "#team-performance",
      ctaLabel: "Open team performance",
      tone: "success",
      icon: "verify",
    });
  }

  return out.slice(0, 4);
}

// ────────── Re-exports for callers that want raw data ──────────

export type { CceoPerformanceRow, RouteQuality };
export { STATIC_ALERTS as cplLeadershipAlerts };

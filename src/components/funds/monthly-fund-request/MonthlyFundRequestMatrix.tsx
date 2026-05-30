"use client";

// Monthly Fund Request — spreadsheet-style matrix.
//
// Visual goal: a premium, calm rendering of the reference spreadsheet
// in the brief. Grouped header bands (Staff Visits / Partner Visits /
// SSA / Cluster Training / Group Trainings / Total Monthly Allocation
// / Disbursement for Meals / Transport), team section bands, staff
// rows with the same column structure, team subtotals, and a grand
// total at the bottom.
//
// Every numeric cell is clickable — onCellClick fires with the
// `MfrCellTarget` describing what was clicked. The page wires this to
// a drilldown drawer that lists the source activities behind the
// number.
//
// Reading order on desktop: read left-to-right per row, scan
// vertically per team. The sticky first two columns (Staff +
// Particulars) keep identity visible during horizontal scroll.

import { useMemo } from "react";
import type {
  MfrActivityCategory,
  MfrLine,
  MonthlyFundRequest,
} from "@/lib/funds/monthly-fund-request-types";
import { cn } from "@/lib/utils";

export type MfrCellTarget = {
  /** Omit to aggregate across every line — used by the Activity × Week
   *  summary view, where each cell sums one category for a week. */
  lineId?: string;
  category: MfrActivityCategory;
  week?: 1 | 2 | 3 | 4 | 5;
};

export function MonthlyFundRequestMatrix({
  mfr,
  onCellClick,
}: {
  mfr: MonthlyFundRequest;
  onCellClick?: (target: MfrCellTarget) => void;
}) {
  // Group lines by team. Order matches the reference: East → North →
  // West → Central → Partners → Special Projects.
  const groups = useMemo(() => {
    const TEAM_ORDER = [
      "Team East", "Team North", "Team West", "Team Central",
      "Partners", "Special Projects",
    ];
    const groupMap = new Map<string, MfrLine[]>();
    for (const line of mfr.lines) {
      const team = line.kind === "partner" ? "Partners"
                 : line.kind === "special_project" ? "Special Projects"
                 : line.team;
      const arr = groupMap.get(team) ?? [];
      arr.push(line);
      groupMap.set(team, arr);
    }
    return TEAM_ORDER
      .filter((t) => groupMap.has(t))
      .map((t) => ({ team: t, lines: groupMap.get(t)! }));
  }, [mfr.lines]);

  // Grand totals per category (sum across all lines)
  const grand = useMemo(() => totalsAcross(mfr.lines), [mfr.lines]);

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto mfr-matrix-scroll">
        <table className="mfr-matrix">
          <colgroup>
            <col className="w-[28px]" />
            <col className="w-[140px]" />
            <col className="w-[200px]" />
            {/* Staff visits */}
            <col className="w-[64px]" />
            <col className="w-[76px]" />
            <col className="w-[88px]" />
            {/* Partner visits */}
            <col className="w-[64px]" />
            <col className="w-[76px]" />
            <col className="w-[88px]" />
            {/* SSA */}
            <col className="w-[64px]" />
            <col className="w-[76px]" />
            <col className="w-[88px]" />
            {/* Cluster training */}
            <col className="w-[64px]" />
            <col className="w-[76px]" />
            <col className="w-[88px]" />
            {/* Group trainings */}
            <col className="w-[64px]" />
            <col className="w-[76px]" />
            <col className="w-[88px]" />
            {/* Total monthly */}
            <col className="w-[110px]" />
            {/* Meals weeks */}
            <col className="w-[78px]" />
            <col className="w-[78px]" />
            <col className="w-[78px]" />
            <col className="w-[78px]" />
            <col className="w-[78px]" />
            <col className="w-[96px]" />
            {/* Transport */}
            <col className="w-[110px]" />
          </colgroup>

          <thead>
            {/* Category bands — the colored headers from the reference */}
            <tr className="mfr-band">
              <th colSpan={3} className="mfr-band-cell mfr-band-staff text-left pl-3">
                <span className="mfr-band-eyebrow">Funds Allocation for {mfr.monthLabel}</span>
              </th>
              <th colSpan={3} className="mfr-band-cell mfr-band-staff">Staff Visits</th>
              <th colSpan={3} className="mfr-band-cell mfr-band-partner">Partner Visits</th>
              <th colSpan={3} className="mfr-band-cell mfr-band-ssa">SSA</th>
              <th colSpan={3} className="mfr-band-cell mfr-band-cluster">Cluster Training</th>
              <th colSpan={3} className="mfr-band-cell mfr-band-group">Group Trainings</th>
              <th className="mfr-band-cell mfr-band-total">Total Monthly Allocation</th>
              <th colSpan={6} className="mfr-band-cell mfr-band-meals">Disbursement for Meals</th>
              <th className="mfr-band-cell mfr-band-transport">Transport</th>
            </tr>

            <tr className="mfr-subhead">
              <th>SN</th>
              <th className="text-left pl-1">Staff</th>
              <th className="text-left pl-1">Particulars</th>
              <Sub>Visits</Sub><Sub>Cost / visit</Sub><Sub>Total</Sub>
              <Sub>Visits</Sub><Sub>Cost / visit</Sub><Sub>Total</Sub>
              <Sub>Activities</Sub><Sub>Cost / unit</Sub><Sub>Total</Sub>
              <Sub>Schools</Sub><Sub>Cost / school</Sub><Sub>Total</Sub>
              <Sub>Schools</Sub><Sub>Cost / school</Sub><Sub>Total</Sub>
              <Sub>Total</Sub>
              <Sub>W1</Sub><Sub>W2</Sub><Sub>W3</Sub><Sub>W4</Sub><Sub>W5</Sub><Sub>Total meals</Sub>
              <Sub>Allocation</Sub>
            </tr>
          </thead>

          <tbody>
            {groups.map((g, gi) => {
              const teamTotals = totalsAcross(g.lines);
              const teamCls = teamBandClass(g.team);
              let lineCounter = 0;
              return (
                <RowGroup key={g.team}>
                  <tr className={cn("mfr-team-row", teamCls)}>
                    <td colSpan={26} className="mfr-team-cell">
                      <span className="mfr-team-name">{g.team}</span>
                      <span className="mfr-team-meta">{g.lines.length} {g.lines.length === 1 ? "row" : "rows"}</span>
                    </td>
                  </tr>
                  {g.lines.map((line) => {
                    lineCounter += 1;
                    return (
                      <StaffMatrixRow
                        key={line.id}
                        rowNumber={teamRowNumber(groups, gi, lineCounter)}
                        line={line}
                        onCellClick={onCellClick}
                      />
                    );
                  })}
                  {/* Team subtotal */}
                  <tr className="mfr-subtotal-row">
                    <td colSpan={3} className="mfr-subtotal-label pl-3">
                      {g.team} subtotal
                    </td>
                    <Sub3 cell={teamTotals.staffVisits} />
                    <Sub3 cell={teamTotals.partnerVisits} />
                    <Sub3 cell={teamTotals.ssa} />
                    <Sub3 cell={teamTotals.clusterTraining} />
                    <Sub3 cell={teamTotals.groupTrainings} />
                    <td className="mfr-num mfr-num-strong">{fmt(teamTotals.totalMonthlyAllocation)}</td>
                    <td className="mfr-num">{fmt(teamTotals.mealsByWeek.w1)}</td>
                    <td className="mfr-num">{fmt(teamTotals.mealsByWeek.w2)}</td>
                    <td className="mfr-num">{fmt(teamTotals.mealsByWeek.w3)}</td>
                    <td className="mfr-num">{fmt(teamTotals.mealsByWeek.w4)}</td>
                    <td className="mfr-num">{fmt(teamTotals.mealsByWeek.w5)}</td>
                    <td className="mfr-num mfr-num-strong">{fmt(teamTotals.mealsTotal)}</td>
                    <td className="mfr-num mfr-num-strong">{fmt(teamTotals.transportAllocation)}</td>
                  </tr>
                </RowGroup>
              );
            })}

            {/* Grand total */}
            <tr className="mfr-grand-row">
              <td colSpan={3} className="mfr-grand-label pl-3">Program activities — Grand Total</td>
              <Sub3 cell={grand.staffVisits} strong />
              <Sub3 cell={grand.partnerVisits} strong />
              <Sub3 cell={grand.ssa} strong />
              <Sub3 cell={grand.clusterTraining} strong />
              <Sub3 cell={grand.groupTrainings} strong />
              <td className="mfr-num mfr-num-hero">{fmt(grand.totalMonthlyAllocation)}</td>
              <td className="mfr-num">{fmt(grand.mealsByWeek.w1)}</td>
              <td className="mfr-num">{fmt(grand.mealsByWeek.w2)}</td>
              <td className="mfr-num">{fmt(grand.mealsByWeek.w3)}</td>
              <td className="mfr-num">{fmt(grand.mealsByWeek.w4)}</td>
              <td className="mfr-num">{fmt(grand.mealsByWeek.w5)}</td>
              <td className="mfr-num mfr-num-hero">{fmt(grand.mealsTotal)}</td>
              <td className="mfr-num mfr-num-hero">{fmt(grand.transportAllocation)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ────────── Row components ───────────────────────────────────────────

function StaffMatrixRow({
  rowNumber,
  line,
  onCellClick,
}: {
  rowNumber: number;
  line: MfrLine;
  onCellClick?: (t: MfrCellTarget) => void;
}) {
  const click = (category: MfrActivityCategory, week?: 1 | 2 | 3 | 4 | 5) =>
    onCellClick ? () => onCellClick({ lineId: line.id, category, week }) : undefined;
  return (
    <tr className="mfr-row">
      <td className="mfr-num mfr-num-muted">{rowNumber}</td>
      <td className="mfr-staff-cell">
        <div className="mfr-staff-name">{line.staffName ?? line.partnerName ?? "—"}</div>
        {line.staffRole && (
          <div className="mfr-staff-role">{line.staffRole} · {line.region}</div>
        )}
      </td>
      <td className="mfr-particulars">{line.particulars}</td>
      {/* Staff Visits */}
      <CountCell n={line.staffVisits.count} />
      <UnitCell n={line.staffVisits.unitCost} />
      <TotalCell n={line.staffVisits.total} onClick={click("StaffVisits")} />
      {/* Partner Visits */}
      <CountCell n={line.partnerVisits.count} />
      <UnitCell n={line.partnerVisits.unitCost} />
      <TotalCell n={line.partnerVisits.total} onClick={click("PartnerVisits")} />
      {/* SSA */}
      <CountCell n={line.ssa.count} />
      <UnitCell n={line.ssa.unitCost} />
      <TotalCell n={line.ssa.total} onClick={click("SSA")} />
      {/* Cluster Training */}
      <CountCell n={line.clusterTraining.count} />
      <UnitCell n={line.clusterTraining.unitCost} />
      <TotalCell n={line.clusterTraining.total} onClick={click("ClusterTraining")} />
      {/* Group Trainings */}
      <CountCell n={line.groupTrainings.count} />
      <UnitCell n={line.groupTrainings.unitCost} />
      <TotalCell n={line.groupTrainings.total} onClick={click("GroupTrainings")} />
      {/* Total Monthly */}
      <TotalCell strong n={line.totalMonthlyAllocation} />
      {/* Meals by week */}
      <TotalCell tone="meals" n={line.mealsByWeek.w1} onClick={click("Meals", 1)} />
      <TotalCell tone="meals" n={line.mealsByWeek.w2} onClick={click("Meals", 2)} />
      <TotalCell tone="meals" n={line.mealsByWeek.w3} onClick={click("Meals", 3)} />
      <TotalCell tone="meals" n={line.mealsByWeek.w4} onClick={click("Meals", 4)} />
      <TotalCell tone="meals" n={line.mealsByWeek.w5} onClick={click("Meals", 5)} />
      <TotalCell tone="meals" strong n={line.mealsTotal} onClick={click("Meals")} />
      {/* Transport */}
      <TotalCell tone="transport" strong n={line.transportAllocation} onClick={click("Transport")} />
    </tr>
  );
}

function CountCell({ n }: { n: number }) {
  return <td className="mfr-num mfr-num-muted">{n > 0 ? n.toLocaleString() : "—"}</td>;
}
function UnitCell({ n }: { n: number }) {
  return <td className="mfr-num mfr-num-muted">{n > 0 ? n.toLocaleString() : "—"}</td>;
}
function TotalCell({
  n,
  onClick,
  strong,
  tone,
}: {
  n: number;
  onClick?: () => void;
  strong?: boolean;
  tone?: "meals" | "transport";
}) {
  return (
    <td
      className={cn(
        "mfr-num",
        n > 0 ? "mfr-num-strong" : "mfr-num-zero",
        strong && "mfr-num-hero",
        tone === "meals" && "mfr-tone-meals",
        tone === "transport" && "mfr-tone-transport",
        onClick && n > 0 && "mfr-clickable",
      )}
      onClick={onClick}
    >
      {n > 0 ? n.toLocaleString() : "—"}
    </td>
  );
}
function Sub3({ cell, strong }: { cell: { count: number; unitCost: number; total: number }; strong?: boolean }) {
  return (
    <>
      <td className="mfr-num mfr-num-muted">{cell.count > 0 ? cell.count.toLocaleString() : "—"}</td>
      <td className="mfr-num mfr-num-muted">{cell.unitCost > 0 ? cell.unitCost.toLocaleString() : "—"}</td>
      <td className={cn("mfr-num", strong ? "mfr-num-hero" : "mfr-num-strong")}>
        {cell.total > 0 ? cell.total.toLocaleString() : "—"}
      </td>
    </>
  );
}
function Sub({ children }: { children: React.ReactNode }) {
  return <th className="mfr-subhead-cell">{children}</th>;
}

// Fragment helper so <RowGroup> conveys intent in the JSX (group of
// rows belongs together for a team).
function RowGroup({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}

// ────────── Helpers ──────────────────────────────────────────────────

function fmt(n: number): string {
  return n > 0 ? n.toLocaleString() : "—";
}

function totalsAcross(lines: MfrLine[]) {
  const sumCell = (key: keyof MfrLine) =>
    lines.reduce(
      (acc, l) => {
        const c = l[key] as { count: number; unitCost: number; total: number };
        return { count: acc.count + c.count, unitCost: 0, total: acc.total + c.total };
      },
      { count: 0, unitCost: 0, total: 0 },
    );
  const mealsByWeek = lines.reduce(
    (acc, l) => ({
      w1: acc.w1 + l.mealsByWeek.w1,
      w2: acc.w2 + l.mealsByWeek.w2,
      w3: acc.w3 + l.mealsByWeek.w3,
      w4: acc.w4 + l.mealsByWeek.w4,
      w5: acc.w5 + l.mealsByWeek.w5,
    }),
    { w1: 0, w2: 0, w3: 0, w4: 0, w5: 0 },
  );
  return {
    staffVisits:     sumCell("staffVisits"),
    partnerVisits:   sumCell("partnerVisits"),
    ssa:             sumCell("ssa"),
    clusterTraining: sumCell("clusterTraining"),
    groupTrainings:  sumCell("groupTrainings"),
    mealsByWeek,
    mealsTotal:           lines.reduce((s, l) => s + l.mealsTotal, 0),
    transportAllocation:  lines.reduce((s, l) => s + l.transportAllocation, 0),
    totalMonthlyAllocation: lines.reduce((s, l) => s + l.totalMonthlyAllocation, 0),
  };
}

function teamBandClass(team: string): string {
  if (team.includes("East"))    return "mfr-team-east";
  if (team.includes("North"))   return "mfr-team-north";
  if (team.includes("West"))    return "mfr-team-west";
  if (team.includes("Central")) return "mfr-team-central";
  if (team === "Partners")      return "mfr-team-partners";
  if (team === "Special Projects") return "mfr-team-sp";
  return "mfr-team-default";
}

function teamRowNumber(
  groups: { team: string; lines: MfrLine[] }[],
  groupIndex: number,
  rowInGroup: number,
): number {
  let n = 0;
  for (let i = 0; i < groupIndex; i++) n += groups[i].lines.length;
  return n + rowInGroup;
}

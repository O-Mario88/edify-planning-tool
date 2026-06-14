import Link from "next/link";
import { ChevronRight, ShieldCheck } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchLeadershipBoards, fetchLeadershipSnapshot, type BeDecisionInsight } from "@/lib/api/surfaces";
import { Pill } from "@/components/ui/Pill";
import { riskToPill, confidenceToPill, confidenceLabel, toneDot, DECISION_TYPE_LABEL } from "@/lib/decisions/leadership-format";

// Compact, data-informed embed of the Leadership Decision Engine for role
// dashboards. It fetches the SAME backend insights as /analytics/decision-engine
// (computed from real SSA, workload, partner, target + system-health data) and
// surfaces the top recommendations. It renders NOTHING when the backend is off —
// dashboards never show fabricated leadership recommendations. The engine
// recommends; leadership decides — full review happens on the engine page.
const RISK_ORDER: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

export async function DecisionEngineEmbed({
  board,
  heading = "Leadership Decision Engine",
  limit = 3,
}: {
  board?: string; // a single decisionType to focus (e.g. "staff_hr"); omit = all role boards
  heading?: string;
  limit?: number;
}) {
  const user = await getCurrentUser();
  const bu = { role: user.role, email: user.email };
  const [boardsR, snapR] = await Promise.all([
    fetchLeadershipBoards(bu, board ? { decisionType: board } : {}),
    fetchLeadershipSnapshot(bu),
  ]);

  // Backend off OR no boards visible to this role → render nothing (no clutter,
  // no fake data). The engine is strictly backend-driven.
  if (!boardsR.live || !boardsR.data.boards.length) return null;

  const insights: BeDecisionInsight[] = boardsR.data.boards
    .flatMap((b) => b.insights)
    .sort(
      (a, b) =>
        (RISK_ORDER[b.riskLevel] ?? 0) - (RISK_ORDER[a.riskLevel] ?? 0) ||
        b.confidenceScore - a.confidenceScore,
    );
  const top = insights.slice(0, limit);
  const headline = snapR.live ? snapR.data.strategicHeadline : null;
  const href = board ? `/analytics/decision-engine?board=${board}` : "/analytics/decision-engine";

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide muted">
            <ShieldCheck className="h-3.5 w-3.5" /> {heading}
            <span className="rounded-full bg-slate-900 px-1.5 py-px text-[9px] font-semibold text-white dark:bg-slate-100 dark:text-slate-900">
              Advisory
            </span>
          </div>
          {headline && (
            <p className="mt-1 text-sm font-medium leading-snug text-[var(--text-primary)]">{headline}</p>
          )}
        </div>
        <Link
          href={href}
          className="inline-flex shrink-0 items-center gap-0.5 rounded-lg px-2 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
        >
          Open <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      {top.length === 0 ? (
        <p className="mt-3 text-xs muted">No leadership actions flagged for this period — data is healthy.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {top.map((i) => (
            <li key={i.id}>
              <Link
                href={href}
                className="group flex items-start gap-2 rounded-lg border border-slate-100 p-2.5 transition hover:border-slate-300 dark:border-slate-800/80 dark:hover:border-slate-700"
              >
                <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${toneDot(i.riskLevel === "critical" || i.riskLevel === "high" ? "red" : i.riskLevel === "medium" ? "amber" : "green")}`} />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-1.5">
                    <span className="truncate text-sm font-medium text-[var(--text-primary)]">{i.recommendation}</span>
                  </span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
                    <span className="text-[10px] uppercase tracking-wide muted">{DECISION_TYPE_LABEL[i.decisionType] ?? i.decisionType}</span>
                    <Pill tone={riskToPill(i.riskLevel)} size="xs">{i.riskLevel}</Pill>
                    <Pill tone={confidenceToPill(i.confidenceLevel)} size="xs">{confidenceLabel(i.confidenceLevel, i.confidenceScore)}</Pill>
                  </span>
                </span>
                <ChevronRight className="mt-1 h-3.5 w-3.5 shrink-0 muted transition group-hover:translate-x-0.5" />
              </Link>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-[10px] muted">Evidence-backed · computed from live SSA, workload, partner &amp; target data · human decision required.</p>
    </div>
  );
}

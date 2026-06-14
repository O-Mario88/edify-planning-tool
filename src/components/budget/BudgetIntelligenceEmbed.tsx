import Link from "next/link";
import { ChevronRight, Wallet } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchBudgetIntelligenceBoards, fetchBudgetIntelligenceSnapshot, type BeBudgetInsight } from "@/lib/api/surfaces";
import { Pill } from "@/components/ui/Pill";
import { riskToPill, confidenceToPill, confidenceLabel, toneDot } from "@/lib/decisions/leadership-format";

// Compact, data-informed embed of the Budget Intelligence & Financial Decision
// Engine — the financial brain. Fetches the SAME backend insights as
// /budget/intelligence (computed from the CD cost register + verified activity +
// SSA impact) and surfaces the highest-exposure / lowest-yield funding lines.
// Renders NOTHING when the backend is off — never fabricated budget figures.
const RISK_ORDER: Record<string, number> = { critical: 4, high: 3, medium: 2, low: 1 };

function yieldTone(y: string): "red" | "amber" | "green" {
  if (y === "low") return "red";
  if (y === "weak" || y === "insufficient") return "amber";
  return "green";
}
function yieldPill(y: string): "danger" | "warning" | "success" {
  if (y === "low") return "danger";
  if (y === "weak" || y === "insufficient") return "warning";
  return "success";
}
const ugx = (n?: number | null) => (n == null ? "" : `UGX ${Math.round(n).toLocaleString("en-US")}`);

export async function BudgetIntelligenceEmbed({
  insightType,
  heading = "Budget Intelligence",
  limit = 3,
}: {
  insightType?: string;
  heading?: string;
  limit?: number;
}) {
  const user = await getCurrentUser();
  const bu = { role: user.role, email: user.email };
  const [boardsR, snapR] = await Promise.all([
    fetchBudgetIntelligenceBoards(bu, insightType ? { insightType } : {}),
    fetchBudgetIntelligenceSnapshot(bu),
  ]);

  if (!boardsR.live || !boardsR.data.insights.length) return null;

  const insights: BeBudgetInsight[] = [...boardsR.data.insights].sort(
    (a, b) => (RISK_ORDER[b.riskLevel] ?? 0) - (RISK_ORDER[a.riskLevel] ?? 0) || (b.amountAffected ?? 0) - (a.amountAffected ?? 0),
  );
  const top = insights.slice(0, limit);
  const headline = snapR.live ? snapR.data.headline : null;
  const href = insightType ? `/budget/intelligence?type=${insightType}` : "/budget/intelligence";

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide muted">
            <Wallet className="h-3.5 w-3.5" /> {heading}
            <span className="rounded-full bg-slate-900 px-1.5 py-px text-[9px] font-semibold text-white dark:bg-slate-100 dark:text-slate-900">Advisory</span>
          </div>
          {headline && <p className="mt-1 text-sm font-medium leading-snug text-[var(--text-primary)]">{headline}</p>}
        </div>
        <Link href={href} className="inline-flex shrink-0 items-center gap-0.5 rounded-lg px-2 py-1 text-xs font-medium text-slate-600 transition hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800">
          Open <ChevronRight className="h-3.5 w-3.5" />
        </Link>
      </div>

      <ul className="mt-3 space-y-2">
        {top.map((i) => (
          <li key={i.id}>
            <Link href={href} className="group flex items-start gap-2 rounded-lg border border-slate-100 p-2.5 transition hover:border-slate-300 dark:border-slate-800/80 dark:hover:border-slate-700">
              <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${toneDot(yieldTone(i.impactYield))}`} />
              <span className="min-w-0 flex-1">
                <span className="truncate text-sm font-medium text-[var(--text-primary)]">{i.recommendation}</span>
                <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
                  <Pill tone={yieldPill(i.impactYield)} size="xs">{i.impactYield} yield</Pill>
                  <Pill tone={riskToPill(i.riskLevel)} size="xs">{i.riskLevel}</Pill>
                  <Pill tone={confidenceToPill(i.confidenceLevel)} size="xs">{confidenceLabel(i.confidenceLevel, i.confidenceScore)}</Pill>
                  {i.amountAffected != null && <span className="text-[10px] muted">{ugx(i.amountAffected)}</span>}
                </span>
              </span>
              <ChevronRight className="mt-1 h-3.5 w-3.5 shrink-0 muted transition group-hover:translate-x-0.5" />
            </Link>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-[10px] muted">Cost ↔ verified activity ↔ SSA impact · computed from the CD cost register · human finance decision required.</p>
    </div>
  );
}

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT, type EdifyRole } from "@/lib/auth-public";
import { PageHeader } from "@/components/ui/PageHeader";
import { Pill } from "@/components/ui/Pill";
import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import { fetchBudgetIntelligenceBoards, fetchBudgetIntelligenceSnapshot, type BeBudgetInsight, type BeBudgetSnapshot } from "@/lib/api/surfaces";
import { riskToPill, confidenceToPill, confidenceLabel, toneDot } from "@/lib/decisions/leadership-format";

// Budget Intelligence & Financial Decision Engine — the financial brain. Every
// figure is computed from the CD cost register + verified activity + SSA impact
// (no fabricated budget data). The engine RECOMMENDS; leadership DECIDES. The
// backend re-enforces BUDGET_INTELLIGENCE_VIEW + role.
const ALLOWED: EdifyRole[] = ["CountryDirector", "ProgramAccountant", "RVP", "CountryProgramLead", "CCEO", "Admin"];
const TYPE_LABEL: Record<string, string> = {
  monthly: "Country Summary",
  activity: "Activity Spend Intelligence",
  partner: "Partner Spend Intelligence",
  regional: "Regional Spend Intelligence",
  accountability: "Accountability Intelligence",
};
const TYPE_ORDER = ["monthly", "activity", "partner", "regional", "accountability"];
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
const ugx = (n?: number | null) => (n == null ? "—" : `UGX ${Math.round(n).toLocaleString("en-US")}`);

export default async function BudgetIntelligencePage() {
  const user = await getCurrentUser();
  const role = user.role as EdifyRole;
  if (!ALLOWED.includes(role)) redirect(ROLE_REDIRECT[role] ?? "/");

  const bu = { role: user.role, email: user.email };
  const [boardsR, snapR] = await Promise.all([
    fetchBudgetIntelligenceBoards(bu),
    fetchBudgetIntelligenceSnapshot(bu),
  ]);

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-5 sm:px-6">
      <PageHeader
        title="Budget Intelligence"
        subtitle="Cost → verified activity → SSA impact. Where to continue, increase, pause, or reassign funds — leadership decides."
        titleBadge={<span className="rounded-full bg-slate-900 px-2 py-0.5 text-[10px] font-semibold text-white dark:bg-slate-100 dark:text-slate-900">Advisory</span>}
        noBack
      />
      {boardsR.live ? (
        <Body insights={boardsR.data.insights} snap={snapR.live ? snapR.data : null} />
      ) : (
        <BackendOff error={boardsR.error} />
      )}
    </div>
  );
}

function Body({ insights, snap }: { insights: BeBudgetInsight[]; snap: BeBudgetSnapshot | null }) {
  const byType = new Map<string, BeBudgetInsight[]>();
  for (const i of insights) (byType.get(i.insightType) ?? byType.set(i.insightType, []).get(i.insightType)!).push(i);
  return (
    <div className="mt-5 space-y-6">
      {snap && (
        <MetricStrip
          metrics={[
            { key: "low", label: "Low-yield funding lines", value: snap.lowYieldCount, tone: snap.lowYieldCount ? "alert" : "default" },
            { key: "high", label: "High-yield lines", value: snap.highYieldCount, tone: "good" },
            { key: "risk", label: "Spend at risk", value: ugx(snap.amountAtRisk) },
            { key: "total", label: "Insights", value: snap.totalInsights },
          ] satisfies MetricCell[]}
        />
      )}
      {insights.length === 0 ? (
        <div className="rounded-xl border border-dashed border-slate-200 p-8 text-center text-sm muted dark:border-slate-800">
          No budget insights yet for this period. Run a recompute once activities are costed.
        </div>
      ) : (
        TYPE_ORDER.filter((t) => byType.has(t)).map((t) => (
          <section key={t} className="space-y-3">
            <h2 className="text-sm font-semibold text-[var(--text-primary)]">{TYPE_LABEL[t] ?? t}</h2>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              {byType.get(t)!.map((i) => <InsightCard key={i.id} i={i} />)}
            </div>
          </section>
        ))
      )}
    </div>
  );
}

function InsightCard({ i }: { i: BeBudgetInsight }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900/40">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          {i.scopeName && <div className="truncate text-[11px] font-medium uppercase tracking-wide muted">{i.scopeName}</div>}
          <div className="mt-0.5 font-semibold leading-snug text-[var(--text-primary)]">{i.recommendation}</div>
        </div>
        {i.amountAffected != null && <div className="shrink-0 text-xs font-medium text-[var(--text-primary)]">{ugx(i.amountAffected)}</div>}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        <Pill tone={yieldPill(i.impactYield)} size="xs">{i.impactYield} yield</Pill>
        <Pill tone={riskToPill(i.riskLevel)} size="xs">{i.riskLevel} risk</Pill>
        <Pill tone={confidenceToPill(i.confidenceLevel)} size="xs">{confidenceLabel(i.confidenceLevel, i.confidenceScore)}</Pill>
      </div>
      <p className="text-xs muted">{i.reason}</p>
      {i.evidenceSummary && i.evidenceSummary.length > 0 && (
        <div className="mt-0.5 flex flex-wrap gap-1.5">
          {i.evidenceSummary.slice(0, 4).map((e, idx) => (
            <span key={idx} className="inline-flex items-center gap-1 rounded-md bg-slate-50 px-1.5 py-0.5 text-[10px] muted dark:bg-slate-800/60">
              <span className={`h-1.5 w-1.5 rounded-full ${toneDot(e.tone)}`} />{e.metricName}: <span className="font-medium text-[var(--text-primary)]">{e.metricValue}</span>
            </span>
          ))}
        </div>
      )}
      <div className="mt-1 rounded-lg bg-slate-50 p-2.5 text-xs text-[var(--text-primary)] dark:bg-slate-800/50">{i.suggestedAction}</div>
    </div>
  );
}

function BackendOff({ error }: { error: string | null }) {
  return (
    <div className="mt-6 rounded-xl border border-dashed border-slate-300 p-8 text-center dark:border-slate-700">
      <p className="text-sm font-medium text-[var(--text-primary)]">Budget Intelligence needs the live backend.</p>
      <p className="mt-1 text-xs muted">Financial recommendations are computed from real cost-register + activity + SSA data only — no mock figures. Enable the backend and run a recompute.</p>
      {error && <p className="mt-2 text-[11px] text-rose-500">{error}</p>}
    </div>
  );
}

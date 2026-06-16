import { MetricStrip, type MetricCell } from "@/components/ui/MetricStrip";
import type { BeLeadershipSummary } from "@/lib/api/surfaces";

// Live leadership KPI strip — every number is a real count/aggregate from the
// backend (/analytics/leadership-summary), scoped to the caller. Replaces the
// fabricated CountryKpiRow so a CD/RVP sees the true country/region picture.

const LABEL: Record<string, string> = {
  teaching_and_learning: "Teaching", financial_health: "Fees/Budget",
  christlike_behaviour: "Christ-like", exposure_to_word_of_god: "Word of God",
  government_requirements: "Govt Req", leadership: "Leadership",
  education_technology: "Ed Tech", learning_environment: "Learning Env",
};
const fmtUgx = (n: number) =>
  n >= 1_000_000 ? `UGX ${(n / 1_000_000).toFixed(1)}M` : n >= 1_000 ? `UGX ${(n / 1_000).toFixed(0)}K` : `UGX ${n}`;

export function LeadershipKpiStrip({ s, scopeLabel = "in scope" }: { s: BeLeadershipSummary; scopeLabel?: string }) {
  const weakest = s.weakestInterventions[0];
  const metrics: MetricCell[] = [
    { key: "schools", label: "Schools", value: s.schools.toLocaleString(), caption: scopeLabel },
    { key: "ssa", label: "SSA Complete", value: `${s.ssaCompletePct}%`, caption: `${s.ssaDone}/${s.schools}`, tone: s.ssaCompletePct >= 80 ? "good" : "alert" },
    { key: "ssaAvg", label: "Avg SSA Score", value: `${s.ssaAverage}/10`, caption: weakest ? `weakest: ${LABEL[weakest.intervention] ?? weakest.intervention} ${weakest.average}` : undefined, tone: s.ssaAverage >= 7 ? "good" : s.ssaAverage < 5 ? "alert" : "default" },
    { key: "core", label: "Core Schools", value: s.coreSchools.toLocaleString(), caption: `${s.schools ? Math.round((s.coreSchools / s.schools) * 100) : 0}%` },
    { key: "clustered", label: "Clustered", value: s.clustered.toLocaleString(), caption: `${s.unclustered.toLocaleString()} unclustered`, tone: s.unclustered ? "alert" : "good" },
    { key: "completed", label: "Completed Activities", value: s.pipeline.completed.toLocaleString(), caption: `${s.pipeline.iaVerified} IA-verified` },
    { key: "staff", label: "Field Staff", value: s.staffCount, caption: `${s.partnerCount} partners` },
    { key: "disbursed", label: "Disbursed", value: fmtUgx(s.disbursedTotalUgx), caption: `${s.paymentsCleared} payments · ${s.fundRequests} requests` },
  ];
  return <MetricStrip metrics={metrics} />;
}

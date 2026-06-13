import { StubPage } from "@/components/shell/StubPage";
import { MetricStrip } from "@/components/ui/MetricStrip";

export default function ExamScoresPage() {
  return (
    <StubPage
      title="Exam Scores"
      subtitle="5,672 records uploaded this cycle. Compare to baseline and verify outliers before scores publish."
    >
      <MetricStrip
        columns="grid-cols-2 md:grid-cols-4"
        metrics={[
          { key: "total", label: "Total Records", value: "5,672", delta: { dir: "up", text: "+9.4% vs Apr" } },
          { key: "verified", label: "Verified", value: "4,520", caption: "79.7% of total" },
          { key: "mean", label: "Mean Score", value: "63.4", delta: { dir: "up", text: "1.2 vs term 1" } },
          { key: "outliers", label: "Outliers Flagged", value: "42", caption: "Manual review" },
        ]}
      />

      <article className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">By Program</h2>
        <p className="text-[11.5px] muted">
          Exam Scores upload feeds the Verified Impact leaderboard. Records that fail validation
          fall into <a href="/quality-checks?issue=missing-exam-scores" className="text-[var(--color-edify-primary)] font-semibold hover:underline">Missing Exam Scores</a> on the
          quality console.
        </p>
      </article>
    </StubPage>
  );
}

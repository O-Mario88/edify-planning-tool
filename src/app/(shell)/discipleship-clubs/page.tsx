import { StubPage } from "@/components/shell/StubPage";
import { MetricStrip } from "@/components/ui/MetricStrip";

export default function DiscipleshipClubsPage() {
  return (
    <StubPage
      title="Discipleship Clubs"
      subtitle="986 active clubs across the Client and Core network. Verify weekly attendance and study-plan completion."
    >
      <MetricStrip
        columns="grid-cols-2 md:grid-cols-4"
        metrics={[
          { key: "active", label: "Active Clubs", value: "986", delta: { dir: "up", text: "+5.3% vs Apr" } },
          { key: "attendance", label: "Avg. Weekly Attendance", value: "24", delta: { dir: "up", text: "+1 vs Apr" } },
          { key: "verified", label: "Verified Reports", value: "742", caption: "75.3% of clubs" },
          { key: "curriculum", label: "Curriculum Complete", value: "68%", caption: "On track" },
        ]}
      />

      <article className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Missing Reports</h2>
        <p className="text-[11.5px] muted">
          98 clubs have not submitted this cycle. See <a href="/quality-checks?issue=missing-discipleship-data" className="text-[var(--color-edify-primary)] font-semibold hover:underline">Missing Discipleship Club Data</a> for the follow-up list.
        </p>
      </article>
    </StubPage>
  );
}

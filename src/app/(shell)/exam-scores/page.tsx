import { FileSpreadsheet, TrendingUp, ShieldCheck } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";

export default function ExamScoresPage() {
  return (
    <StubPage
      title="Exam Scores"
      subtitle="5,672 records uploaded this cycle. Compare to baseline and verify outliers before scores publish."
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat icon={<FileSpreadsheet size={14} />} label="Total Records"    value="5,672" caption="+9.4% vs Apr" />
        <Stat icon={<ShieldCheck     size={14} />} label="Verified"         value="4,520" caption="79.7% of total" />
        <Stat icon={<TrendingUp      size={14} />} label="Mean Score"       value="63.4"  caption="↑ 1.2 vs term 1" />
        <Stat icon={<FileSpreadsheet size={14} />} label="Outliers Flagged" value="42"    caption="Manual review" />
      </section>

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

function Stat({ icon, label, value, caption }: { icon: React.ReactNode; label: string; value: string; caption: string }) {
  return (
    <div className="card p-3.5">
      <div className="flex items-center gap-2 mb-1.5 text-[var(--color-edify-muted)]">{icon}<span className="text-[11px] font-semibold">{label}</span></div>
      <div className="text-[24px] font-extrabold tabular leading-none">{value}</div>
      <div className="text-caption muted mt-1">{caption}</div>
    </div>
  );
}

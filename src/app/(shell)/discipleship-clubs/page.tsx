import { Heart, Users, ShieldCheck, BookOpen } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";

export default function DiscipleshipClubsPage() {
  return (
    <StubPage
      title="Discipleship Clubs"
      subtitle="986 active clubs across the Client and Core network. Verify weekly attendance and study-plan completion."
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat icon={<Heart        size={14} />} label="Active Clubs"      value="986"   caption="+5.3% vs Apr" />
        <Stat icon={<Users        size={14} />} label="Avg. Weekly Attendance" value="24" caption="+1 vs Apr" />
        <Stat icon={<ShieldCheck  size={14} />} label="Verified Reports" value="742"   caption="75.3% of clubs" />
        <Stat icon={<BookOpen     size={14} />} label="Curriculum Complete" value="68%" caption="On track" />
      </section>

      <article className="card p-3.5">
        <h2 className="text-body-lg font-extrabold tracking-tight mb-2">Missing Reports</h2>
        <p className="text-[11.5px] muted">
          98 clubs have not submitted this cycle. See <a href="/quality-checks?issue=missing-discipleship-data" className="text-[var(--color-edify-primary)] font-semibold hover:underline">Missing Discipleship Club Data</a> for the follow-up list.
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

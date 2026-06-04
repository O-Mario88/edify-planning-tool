import { StubPage } from "@/components/shell/StubPage";
import { QualityCheckStatusCard } from "@/components/ui/lazy-charts";
import { TopIssuesCard } from "@/components/impact/TopIssuesCard";
import { RunQualityCheckButton } from "@/components/quality/RunQualityCheckButton";
import { qualityCheckSeverity, qualityCheckTotal } from "@/lib/impact-mock";
import { latestQualityRun } from "@/lib/quality/quality-checks";

function timeAgo(iso: string): string {
  const mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr${hrs === 1 ? "" : "s"} ago`;
  return new Date(iso).toLocaleDateString();
}

export default function QualityChecksPage() {
  const lastRun = latestQualityRun();

  return (
    <StubPage
      title="Quality Checks"
      subtitle={`${qualityCheckTotal} open issues across ${qualityCheckSeverity.length} severity tiers. Resolve critical first — they block program counting.`}
    >
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="min-w-0">
          <h2 className="text-body-lg font-extrabold tracking-tight">Open Quality Issues</h2>
          <p className="text-[11.5px] muted">Status breakdown and the top issues blocking impact verification.</p>
        </div>
        <RunQualityCheckButton />
      </div>

      {/* Last-run status banner — populated once a check has been run this session. */}
      <div className="rounded-xl border border-[var(--color-edify-border)] bg-[var(--color-edify-soft)]/40 px-3.5 py-2.5 flex items-center justify-between gap-3 flex-wrap text-[12px]">
        {lastRun ? (
          <>
            <span className="inline-flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <b>Last run {timeAgo(lastRun.ranAt)}</b>
              <span className="muted">by {lastRun.ranByName}</span>
            </span>
            <span className="muted tabular">
              Scanned <b>{lastRun.scannedActivities}</b> activities · <b>{lastRun.totalIssues}</b> open issues ·{" "}
              <b>{lastRun.liveSalesforceGaps}</b> missing Salesforce IDs
            </span>
          </>
        ) : (
          <span className="inline-flex items-center gap-2 muted">
            <span className="w-2 h-2 rounded-full bg-slate-400" />
            No quality check run yet this session — run one to scan submitted records for gaps.
          </span>
        )}
      </div>

      <section className="grid grid-cols-12 gap-4 items-start">
        <div className="col-span-12 md:col-span-5">
          <QualityCheckStatusCard />
        </div>
        <div className="col-span-12 md:col-span-7">
          <TopIssuesCard />
        </div>
      </section>
    </StubPage>
  );
}

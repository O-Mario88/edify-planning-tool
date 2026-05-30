import { Plus } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { QualityCheckStatusCard } from "@/components/ui/lazy-charts";
import { TopIssuesCard } from "@/components/impact/TopIssuesCard";
import { ActionButton } from "@/components/ui/ActionButton";
import { qualityCheckSeverity, qualityCheckTotal } from "@/lib/impact-mock";

export default function QualityChecksPage() {
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
        <ActionButton
          Icon={Plus}
          label="Run Quality Check"
          className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold hover:brightness-110"
          toast={{
            tone: "success",
            title: "Quality check scheduled",
            body: "Running impact checks across submitted Salesforce records. You'll be notified when complete.",
          }}
        />
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

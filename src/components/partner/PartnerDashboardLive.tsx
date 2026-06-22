import Link from "next/link";
import { PartnerHeader } from "@/components/partner/PartnerHeader";
import { PartnerWorkQueueLive } from "@/components/partner/PartnerWorkQueueLive";
import { PartnerActivityListLive } from "@/components/partner/PartnerActivityListLive";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { DebriefPromoterCard } from "@/components/debrief/DebriefPromoterCard";

// Production partner command center — scoped to the signed-in partner org.
// No fabricated pipeline totals; only backend-assigned work surfaces.
export function PartnerDashboardLive() {
  return (
    <>
      <PartnerHeader />
      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-4 md:space-y-5">
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Assigned work"
            title="What Edify routed to your team"
            description="Activities assigned by your CCEO or Program Lead — schedule, deliver, and submit evidence from here."
          />
          <PartnerWorkQueueLive />
        </section>

        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="All activities"
            title="Your organisation's activity list"
            description="Every assignment for your partner org, with status and evidence state."
          />
          <PartnerActivityListLive />
        </section>

        <DebriefPromoterCard submitterRole="Partner" />

        <footer className="card rounded-2xl px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <p className="text-[12px] muted">
            Need the day view?{" "}
            <Link href="/partner/today" className="font-semibold text-[var(--color-edify-primary)] hover:underline">
              Open Today
            </Link>
          </p>
          <Link
            href="/messages"
            className="text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline whitespace-nowrap"
          >
            Contact your Edify focal person
          </Link>
        </footer>
      </div>
    </>
  );
}

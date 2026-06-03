// /dashboards/partner — Partner Delivery Command Center.
//
// Reads like the partner's daily op-center, organised around the
// workflow (Assigned → Scheduled → Delivered → Evidence → CCEO →
// PL → Accountant → Paid). Every section answers a single question:
//
//   0.  Mission Hero          — who am I, what's on my plate?
//   1.  Workflow Tracker      — where does each activity stand?
//   2.  Top 3 Priorities      — what should I do in the next 10s?
//   3.  Done for Today        — daily habit checklist
//   4.  Partner Action Inbox  — every activity, filtered by tab
//   5.  Assigned Schools      — schools needing support this week
//   6.  Upcoming Activities   — Today / Tomorrow / This Week / Later
//   7.  Status snapshot       — Evidence Missing / Returned / Verified
//   8.  Payment pipeline      — every activity's payment state
//   9.  Thank-you footer
//
// Open to PartnerAdmin / PartnerFieldOfficer / PartnerViewer / Admin.

import { redirect } from "next/navigation";
import Link from "next/link";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { PartnerHeader } from "@/components/partner/PartnerHeader";
import { DebriefPromoterCard } from "@/components/debrief/DebriefPromoterCard";
import { PartnerWorkflowTracker } from "@/components/partner/PartnerWorkflowTracker";
import { PartnerPriorityActions } from "@/components/partner/PartnerPriorityActions";
import { PartnerDoneForToday } from "@/components/partner/PartnerDoneForToday";
import { PartnerActionInbox } from "@/components/partner/PartnerActionInbox";
import { PartnerAssignedSchools } from "@/components/partner/PartnerAssignedSchools";
import { PartnerUpcoming } from "@/components/partner/PartnerUpcoming";
import { PartnerStatusGrid } from "@/components/partner/PartnerStatusGrid";
import { PartnerPaymentStatusCard } from "@/components/partner/PartnerPaymentStatusCard";
import { PartnerEvidenceRequired } from "@/components/partner/PartnerEvidenceRequired";
import { PartnerReturnedCorrections } from "@/components/partner/PartnerReturnedCorrections";
import { PartnerEvidenceQualityPanel } from "@/components/partner/PartnerEvidenceQualityPanel";
import { PartnerSchoolImpactSummary } from "@/components/partner/PartnerSchoolImpactSummary";
import { PartnerDashboardMobileView } from "@/components/mobile/views/PartnerDashboardMobileView";
import { SectionHeader } from "@/components/ui/SectionHeader";
import {
  partnerPriorityActions,
  doneForTodayItems,
  partnerInboxTabs,
  partnerInboxRows,
  partnerAssignedSchools,
  partnerUpcoming,
  partnerStatusBuckets,
} from "@/lib/partner/partner-dashboard-mock";
import {
  missionStatusCards,
  bfepMissionOrg,
  workflowStepCounts,
} from "@/lib/partner/partner-evidence-mock";

const ALLOWED = new Set([
  "PartnerAdmin",
  "PartnerFieldOfficer",
  "PartnerViewer",
  "Admin",
]);

export default async function PartnerCommandCenter({
  searchParams,
}: {
  searchParams: Promise<{ preview?: string }>;
}) {
  const user = await getCurrentUser();
  const params = await searchParams;
  // Dev-only escape: ?preview=1 renders the layout without the
  // partner-role gate so we can verify the build in the test harness.
  // Hard-gated by NODE_ENV — production never honours this query.
  const previewMode = process.env.NODE_ENV !== "production" && params.preview === "1";
  if (!previewMode && !ALLOWED.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }

  const trackerCounts = [
    { key: "assigned"   as const, count: workflowStepCounts.assigned },
    { key: "scheduled"  as const, count: workflowStepCounts.scheduled },
    { key: "delivered"  as const, count: workflowStepCounts.delivered },
    { key: "evidence"   as const, count: workflowStepCounts.evidence },
    { key: "cceo"       as const, count: workflowStepCounts.cceo },
    { key: "plApproval" as const, count: workflowStepCounts.plApproval },
    { key: "accountant" as const, count: workflowStepCounts.accountant },
    { key: "paid"       as const, count: workflowStepCounts.paid },
  ];

  const desktop = (
    <>
      <PartnerHeader />

      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-6 space-y-4 md:space-y-5">
        {/* PartnerMissionHero retired per global hero removal pass. */}
        <DebriefPromoterCard submitterRole="Partner" />

        {/* PIPELINE — the 8-step workflow tracker. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Pipeline"
            title="Your work, from assigned to paid"
            description="Every activity moves through these eight stages — counts update live as you and Edify clear each gate."
          />
          <PartnerWorkflowTracker counts={trackerCounts} />
        </section>

        {/* TODAY — priorities, daily habit, inbox, evidence, corrections. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Today"
            title="What's in your hands right now"
            description="Top priorities, daily-habit checklist, action inbox, the evidence still owed, and anything Edify returned for fixing."
          />
          <PartnerPriorityActions actions={partnerPriorityActions} />
          <PartnerDoneForToday items={doneForTodayItems} />
          <PartnerActionInbox tabs={partnerInboxTabs} rows={partnerInboxRows} />
          <PartnerEvidenceRequired />
          <PartnerReturnedCorrections />
        </section>

        {/* SCHOOLS & SCHEDULE — the field-ops view. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Schools & schedule"
            title="Where and when you're going"
            description="Schools needing support this week and the activity schedule for today, tomorrow, and beyond."
          />
          <PartnerAssignedSchools schools={partnerAssignedSchools} />
          <PartnerUpcoming items={partnerUpcoming} />
        </section>

        {/* STATUS & PAYMENT — the closing intelligence panel. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Status & payment"
            title="How everything is tracking"
            description="Evidence snapshot, payment pipeline, 30-day evidence-quality trend, and the school-improvement contribution that all this work adds up to."
          />
          <PartnerStatusGrid buckets={partnerStatusBuckets} />
          <PartnerPaymentStatusCard />
          <PartnerEvidenceQualityPanel />
          <PartnerSchoolImpactSummary />
        </section>

        {/* Thank-you footer */}
        <footer className="card rounded-2xl px-4 py-3 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
          <p className="text-[12px] muted">
            <span className="text-emerald-700">✓</span> Thank you for your partnership. Your work is improving teaching, learning, and school leadership in your assigned schools.
          </p>
          <Link
            href="/messages"
            className="text-[12px] font-semibold text-[var(--color-edify-primary)] hover:underline whitespace-nowrap"
          >
            Need help? Contact your Edify focal person.
          </Link>
        </footer>
      </div>
    </>
  );

  const mobile = (
    <PartnerDashboardMobileView
      org={bfepMissionOrg}
      statusCards={missionStatusCards}
      trackerCounts={trackerCounts}
      priorityActions={partnerPriorityActions}
      doneItems={doneForTodayItems}
      inboxTabs={partnerInboxTabs}
      inboxRows={partnerInboxRows}
      assignedSchools={partnerAssignedSchools}
      upcoming={partnerUpcoming}
      statusBuckets={partnerStatusBuckets}
    />
  );

  return <ResponsiveDashboard desktop={desktop} mobile={mobile} />;
}

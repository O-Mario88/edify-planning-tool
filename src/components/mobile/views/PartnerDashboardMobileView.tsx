"use client";

// PartnerDashboardMobileView — phone-shaped variant of the Partner
// Delivery Command Center. The desktop tree stacks ~13 heavy panels and
// produces 10,000+ pixels of scroll on a 375-wide viewport — unusable
// one-thumb. This view keeps the same ordering and the same component
// implementations, but:
//
//   • Compact mission strip (4 numbers, one row) instead of the full
//     PartnerMissionHero card.
//   • Top 3 priorities + Done for Today rendered open — "what do I do
//     in the next 10 seconds" is one tap from the top.
//   • Everything else (Activity Workflow, Action Inbox, Evidence
//     Required, Returned Corrections, Assigned Schools, Upcoming,
//     Status, Payment Pipeline, Evidence Quality, School Impact) is
//     wrapped in <MobileCollapsibleSection> accordions, closed by
//     default. Counts surface in the header so the partner sees what's
//     waiting without opening the section.
//
// The desktop components inside the accordions already render fine on
// narrow viewports; we just stop forcing the partner to scroll past
// every one of them every visit.

import Link from "next/link";
import { Building2, Users, Handshake } from "lucide-react";
import { useSetPageTitle } from "@/components/shell/PageTitleContext";
import { MobileCollapsibleSection } from "@/components/mobile/views/MobileSubpageShell";
import { PartnerPriorityActions } from "@/components/partner/PartnerPriorityActions";
import { PartnerDoneForToday } from "@/components/partner/PartnerDoneForToday";
import { PartnerWorkflowTracker } from "@/components/partner/PartnerWorkflowTracker";
import { DebriefPromoterCard } from "@/components/debrief/DebriefPromoterCard";
import { PartnerActionInbox } from "@/components/partner/PartnerActionInbox";
import { PartnerEvidenceRequired } from "@/components/partner/PartnerEvidenceRequired";
import { PartnerReturnedCorrections } from "@/components/partner/PartnerReturnedCorrections";
import { PartnerAssignedSchools } from "@/components/partner/PartnerAssignedSchools";
import { PartnerUpcoming } from "@/components/partner/PartnerUpcoming";
import { PartnerStatusGrid } from "@/components/partner/PartnerStatusGrid";
import { PartnerPaymentStatusCard } from "@/components/partner/PartnerPaymentStatusCard";
import { PartnerEvidenceQualityPanel } from "@/components/partner/PartnerEvidenceQualityPanel";
import { PartnerSchoolImpactSummary } from "@/components/partner/PartnerSchoolImpactSummary";
import type {
  PartnerPriorityAction,
  DoneForTodayItem,
  PartnerInboxTab,
  PartnerInboxRow,
  PartnerAssignedSchool,
  PartnerUpcomingItem,
  StatusBucket,
} from "@/lib/partner/partner-dashboard-mock";
import type { MissionStatusCard } from "@/components/partner/PartnerMissionHero";

type MissionOrg = {
  partnerName: string;
  districts: string[];
  schoolsAssigned: number;
  activeActivities: number;
  edifyFocal: string;
  contractStatus: "Active" | "Paused" | "Ending";
};

type TrackerCount = {
  key:
    | "assigned"
    | "scheduled"
    | "delivered"
    | "evidence"
    | "cceo"
    | "plApproval"
    | "accountant"
    | "paid";
  count: number;
};

export function PartnerDashboardMobileView({
  org,
  statusCards,
  trackerCounts,
  priorityActions,
  doneItems,
  inboxTabs,
  inboxRows,
  assignedSchools,
  upcoming,
  statusBuckets,
}: {
  org: MissionOrg;
  statusCards: MissionStatusCard[];
  trackerCounts: TrackerCount[];
  priorityActions: PartnerPriorityAction[];
  doneItems: DoneForTodayItem[];
  inboxTabs: PartnerInboxTab[];
  inboxRows: PartnerInboxRow[];
  assignedSchools: PartnerAssignedSchool[];
  upcoming: PartnerUpcomingItem[];
  statusBuckets: StatusBucket[];
}) {
  // Page title — short, fits the dark mobile top bar without
  // truncation. Same value the desktop PartnerHeader registers.
  useSetPageTitle("Partner");

  const evidenceNeeded =
    statusCards.find((c) => c.key === "evidenceNeeded")?.count ?? 0;
  const awaitingCceo =
    statusCards.find((c) => c.key === "awaitingCceo")?.count ?? 0;
  const awaitingPl =
    statusCards.find((c) => c.key === "awaitingPl")?.count ?? 0;
  const inboxTotal = inboxRows.length;
  const upcomingToday = upcoming.filter((u) => u.bucket === "today").length;

  return (
    <div className="px-3 pb-24 space-y-3">
      {/* Compact mission strip — partner already knows who they are.
          Show the 4 numbers that change day-to-day. Uses the shared
          .hero-mobile gradient so every mobile dashboard hero reads
          like the same material. */}
      <section className="hero-mobile rounded-2xl text-white p-4 tile-in">
        <div className="relative z-[1]">
          <div className="text-[9.5px] font-extrabold uppercase tracking-[0.14em] text-emerald-300/90">
            Partner delivery
          </div>
          <h1 className="mt-1 text-[19px] font-extrabold leading-tight tracking-tight text-balance">{org.partnerName}</h1>
          <div className="mt-1.5 text-[11px] text-white/65 flex items-center gap-2.5 flex-wrap">
            <span className="inline-flex items-center gap-1"><Building2 size={11} /> {org.districts.join(", ")}</span>
            <span className="inline-flex items-center gap-1"><Users size={11} /> {org.schoolsAssigned} schools</span>
            <span className="inline-flex items-center gap-1"><Handshake size={11} /> {org.contractStatus}</span>
          </div>
          <div className="grid grid-cols-4 gap-1.5 mt-3.5">
            <MissionTile label="Active"   value={org.activeActivities} tone="neutral" stagger="stagger-1" />
            <MissionTile label="Evidence" value={evidenceNeeded}       tone="danger"  stagger="stagger-2" />
            <MissionTile label="CCEO"     value={awaitingCceo}         tone="warn"    stagger="stagger-3" />
            <MissionTile label="PL"       value={awaitingPl}           tone="warn"    stagger="stagger-4" />
          </div>
        </div>
      </section>

      {/* Today's Partner Debrief — kept above the priorities row so a
          field officer files their reality before triaging. */}
      <DebriefPromoterCard submitterRole="Partner" />

      {/* The "what do I do right now" pair — visible without tapping. */}
      <PartnerPriorityActions actions={priorityActions} />
      <PartnerDoneForToday items={doneItems} />

      {/* Everything else collapsed. Headers carry the count so the
          partner can triage without opening the section. */}
      <MobileCollapsibleSection
        title="Activity Workflow"
        subtitle="Where each activity sits in the pipeline"
        count={trackerCounts.reduce((sum, t) => sum + t.count, 0)}
        tone="edify"
      >
        <div className="p-3">
          <PartnerWorkflowTracker counts={trackerCounts} />
        </div>
      </MobileCollapsibleSection>

      <MobileCollapsibleSection
        title="Action Inbox"
        subtitle="Every activity, filtered by tab"
        count={inboxTotal}
        tone="rose"
      >
        <div className="p-3">
          <PartnerActionInbox tabs={inboxTabs} rows={inboxRows} />
        </div>
      </MobileCollapsibleSection>

      <MobileCollapsibleSection
        title="Evidence Required"
        subtitle="Per-activity checklist + completeness"
        count={evidenceNeeded}
        tone="rose"
      >
        <div className="p-3">
          <PartnerEvidenceRequired />
        </div>
      </MobileCollapsibleSection>

      <MobileCollapsibleSection
        title="Returned for Correction"
        subtitle="Structured fixes — no guessing"
        tone="amber"
      >
        <div className="p-3">
          <PartnerReturnedCorrections />
        </div>
      </MobileCollapsibleSection>

      <MobileCollapsibleSection
        title="Assigned Schools"
        subtitle="Schools needing support this week"
        count={assignedSchools.length}
      >
        <div className="p-3">
          <PartnerAssignedSchools schools={assignedSchools} />
        </div>
      </MobileCollapsibleSection>

      <MobileCollapsibleSection
        title="Upcoming Activities"
        subtitle="Today / Tomorrow / This Week / Later"
        count={upcomingToday}
        tone="blue"
      >
        <div className="p-3">
          <PartnerUpcoming items={upcoming} />
        </div>
      </MobileCollapsibleSection>

      <MobileCollapsibleSection
        title="Status Snapshot"
        subtitle="Evidence missing / returned / verified"
      >
        <div className="p-3">
          <PartnerStatusGrid buckets={statusBuckets} />
        </div>
      </MobileCollapsibleSection>

      <MobileCollapsibleSection
        title="Payment Pipeline"
        subtitle="Every activity's payment state"
        tone="green"
      >
        <div className="p-3">
          <PartnerPaymentStatusCard />
        </div>
      </MobileCollapsibleSection>

      <MobileCollapsibleSection
        title="Evidence Quality"
        subtitle="30-day trailing performance"
      >
        <div className="p-3">
          <PartnerEvidenceQualityPanel />
        </div>
      </MobileCollapsibleSection>

      <MobileCollapsibleSection
        title="School Improvement Impact"
        subtitle="The why behind it all"
        tone="green"
      >
        <div className="p-3">
          <PartnerSchoolImpactSummary />
        </div>
      </MobileCollapsibleSection>

      <footer className="rounded-2xl bg-white border border-[var(--color-edify-border)] shadow-sm px-3.5 py-3 text-[11.5px] muted">
        <span className="text-emerald-700">✓</span> Thank you for your partnership.{" "}
        <Link href="/messages" className="font-semibold text-[var(--color-edify-primary)] hover:underline">
          Need help?
        </Link>
      </footer>
    </div>
  );
}

function MissionTile({
  label,
  value,
  tone,
  stagger,
}: {
  label: string;
  value: number;
  tone: MissionStatusCard["tone"];
  stagger?: string;
}) {
  return (
    <div className={`hero-tile tone-${tone} tile-in ${stagger ?? ""}`}>
      <div className="flex items-center justify-between gap-1.5">
        <span className="text-[8.5px] uppercase tracking-[0.08em] font-extrabold text-white/65">{label}</span>
        <span className="dot" aria-hidden />
      </div>
      <div className="text-[20px] font-extrabold num-hero leading-none mt-1 text-white">{value}</div>
    </div>
  );
}

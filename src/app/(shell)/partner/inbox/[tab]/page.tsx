// /partner/inbox/[tab] — shared inbox template.
//
// One dynamic page handles all 8 inbox tabs (assigned, due-this-week,
// needs-evidence, needs-report, returned, awaiting-verification,
// verified, completed). Each renders the same shell with:
//   • a status-specific header (title + subtitle)
//   • the workflow tracker pinned for context
//   • a filtered activity list
//
// Tab metadata lives in lib/partner/partner-inbox-routes.ts so the
// sidebar links and this page read from one source.

import { notFound, redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerActionInbox } from "@/components/partner/PartnerActionInbox";
import { PartnerWorkflowTracker } from "@/components/partner/PartnerWorkflowTracker";
import {
  partnerInboxTabs,
  partnerInboxRows,
} from "@/lib/partner/partner-dashboard-mock";
import { workflowStepCounts } from "@/lib/partner/partner-evidence-mock";
import {
  INBOX_ROUTES,
  type InboxRouteKey,
} from "@/lib/partner/partner-inbox-routes";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerInboxTabPage({
  params,
  searchParams,
}: {
  params: Promise<{ tab: string }>;
  searchParams: Promise<{ preview?: string }>;
}) {
  const user = await getCurrentUser();
  const sp = await searchParams;
  const previewMode = process.env.NODE_ENV !== "production" && sp.preview === "1";
  if (!previewMode && !ALLOWED.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  const { tab } = await params;
  const route = INBOX_ROUTES.find((r) => r.key === tab as InboxRouteKey);
  if (!route) notFound();

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

  return (
    <>
      <PartnerSubPageHeader
        title={route.title}
        subtitle={route.subtitle}
        kpis={[
          { label: "In this queue",   value: route.badgeCount, iconKey: "inbox", tone: route.tone === "success" ? "good" : route.tone === "danger" ? "danger" : route.tone === "warn" ? "warn" : "neutral", caption: "Right now" },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        <PartnerWorkflowTracker counts={trackerCounts} />
        {/* Reuse the Command Center's action inbox — it already
            supports filtering across tab keys via its built-in
            tabs strip, with the row list scrolling inside the card. */}
        <PartnerActionInbox tabs={partnerInboxTabs} rows={partnerInboxRows} />
      </div>
    </>
  );
}

export async function generateStaticParams() {
  return INBOX_ROUTES.map((r) => ({ tab: r.key }));
}

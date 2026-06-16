// /partner/inbox/[tab] — shared inbox template.
//
// One dynamic page handles all 8 inbox tabs (assigned, due-this-week,
// needs-evidence, needs-report, returned, awaiting-verification,
// verified, completed). Each renders the same shell with a status-specific
// header and a live, backend-scoped activity list filtered to the tab.
//
// Tab metadata lives in lib/partner/partner-inbox-routes.ts so the
// sidebar links and this page read from one source. The activity data is the
// partner round-trip (fetchMyPartnerActivities) — no in-memory mock.

import { notFound, redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import {
  PartnerActivityListLive,
  type PartnerActivityFilter,
} from "@/components/partner/PartnerActivityListLive";
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

  return (
    <>
      <PartnerSubPageHeader title={route.title} subtitle={route.subtitle} />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        {/* Live, backend-scoped to this tab. The counts strip + rows both come
            from the partner round-trip — no fabricated badges. */}
        <PartnerActivityListLive
          filter={route.key as PartnerActivityFilter}
          variant={route.key === "returned" ? "corrections" : "list"}
          emptyHint={`Nothing in "${route.title}" right now.`}
        />
      </div>
    </>
  );
}

export async function generateStaticParams() {
  return INBOX_ROUTES.map((r) => ({ tab: r.key }));
}

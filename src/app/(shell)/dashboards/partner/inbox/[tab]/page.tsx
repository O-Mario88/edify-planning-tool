// Deprecated: canonical URL is /partner/inbox/[tab].
// Preserves the tab segment so old bookmarks land on the right queue.

import { permanentRedirect } from "next/navigation";

export default async function DeprecatedDashboardInboxTab({
  params,
}: {
  params: Promise<{ tab: string }>;
}) {
  const { tab } = await params;
  permanentRedirect(`/partner/inbox/${tab}`);
}

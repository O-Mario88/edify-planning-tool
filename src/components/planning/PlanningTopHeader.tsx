// PlanningTopHeader — Planning console chrome on the CANONICAL PageHeader
// (was the separate EntityHeader system). Now an async server component:
// it resolves the user, computes the role-scoped FilterScope, and renders
// a live <HeaderFilterBar> plus the planning snapshot/help badges. This
// retires EntityHeader from the planning surface and gives planning real,
// URL-synced filters instead of decorative pills.

import Link from "next/link";
import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { planningHeader } from "@/lib/planning-mock";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { liveDistrictNamesFor } from "@/lib/api/surfaces";

export async function PlanningTopHeader() {
  const user = await getCurrentUser();
  const liveDistrictNames = await liveDistrictNamesFor(user);
  const scope = getFilterScope({ user, liveDistrictNames });

  return (
    <PageHeader
      title={planningHeader.title}
      subtitle={planningHeader.subtitle}
      filterBar={<HeaderFilterBar scope={scope} />}
      searchPlaceholder={planningHeader.searchPlaceholder}
      meta={<PlanningHeaderBadges />}
    />
  );
}

// Inline badges row — Snapshot pill + Help link shown under the header on
// planning. Plain markup (no client hooks), so it renders fine inside the
// server component.
function PlanningHeaderBadges() {
  return (
    <div className="flex items-center gap-2">
      <span className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-[var(--color-edify-border)] bg-[var(--color-card)] text-caption font-semibold text-[var(--color-edify-muted)]">
        <span className="w-2 h-2 rounded-full bg-emerald-500" />
        Snapshot · just now
      </span>
      <Link
        href="/help"
        className="inline-flex items-center gap-1.5 h-8 px-3 rounded-full border border-[var(--color-edify-border)] bg-[var(--color-card)] text-caption font-semibold text-[var(--color-edify-muted)] hover:bg-[var(--color-edify-soft)]/40"
      >
        ? Help
      </Link>
    </div>
  );
}

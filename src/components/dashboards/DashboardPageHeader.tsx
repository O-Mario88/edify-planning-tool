// DashboardPageHeader — role-aware adapter over the canonical PageHeader.
//
// Now a SERVER component: it resolves the signed-in user and computes the
// role-scoped FilterScope, then hands a live <HeaderFilterBar> to
// PageHeader. The decorative static filter pills from dashboard-hero-mock
// are gone — every dashboard's FY/Quarter/Region/District/… filters are
// real, role-scoped, and URL-synced.

import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { heroContentForRole, type HeroRole } from "@/lib/dashboard-hero-mock";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { liveDistrictNamesFor } from "@/lib/api/surfaces";

export async function DashboardPageHeader({ role }: { role: HeroRole }) {
  const hero = heroContentForRole(role);
  const user = await getCurrentUser();
  // Geography dropdowns from the live backend district universe (mock fallback).
  const liveDistrictNames = await liveDistrictNamesFor(user);
  const scope = getFilterScope({ user, liveDistrictNames });
  return (
    <PageHeader
      title={hero.title}
      filterBar={<HeaderFilterBar scope={scope} />}
      searchPlaceholder="Search everything…"
    />
  );
}

// SsaHeader — SSA page chrome on the CANONICAL PageHeader (migrated off
// the EntityHeader system). Async server component: resolves the user,
// computes the role-scoped FilterScope, and renders a live
// <HeaderFilterBar> (FY/Quarter/Region/District + Advanced drawer) plus
// the page identity. Its bespoke decorative LabeledPills + dead Reset are
// retired — the live bar carries real, URL-synced filters and its own Reset.

import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { ssaHeader } from "@/lib/ssa-mock";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";

export async function SsaHeader() {
  const user = await getCurrentUser();
  const scope = getFilterScope({ user });

  return (
    <PageHeader
      title={ssaHeader.title}
      subtitle={ssaHeader.subtitle}
      filterBar={<HeaderFilterBar scope={scope} />}
      searchPlaceholder={ssaHeader.searchPlaceholder}
    />
  );
}

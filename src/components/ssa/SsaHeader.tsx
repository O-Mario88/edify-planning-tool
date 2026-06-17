// SsaHeader — SSA page chrome on the CANONICAL PageHeader (migrated off
// the EntityHeader system). Async server component: resolves the user,
// computes the role-scoped FilterScope, and renders a live
// <HeaderFilterBar> (FY/Quarter/Region/District + Advanced drawer) plus
// the page identity. Its bespoke decorative LabeledPills + dead Reset are
// retired — the live bar carries real, URL-synced filters and its own Reset.

import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { liveDistrictNamesFor } from "@/lib/api/surfaces";

// Static page chrome (title/subtitle/search placeholder). Inlined off ssa-mock
// so the header compiles independently of the mock data layer.
const SSA_HEADER = {
  title: "SSA Performance",
  subtitle:
    "Track school self-assessment performance across all 8 interventions and compare district performance.",
  searchPlaceholder: "Search schools, districts, or interventions…",
} as const;

export async function SsaHeader() {
  const user = await getCurrentUser();
  const liveDistrictNames = await liveDistrictNamesFor(user);
  const scope = getFilterScope({ user, liveDistrictNames });

  return (
    <PageHeader
      title={SSA_HEADER.title}
      subtitle={SSA_HEADER.subtitle}
      filterBar={<HeaderFilterBar scope={scope} />}
      searchPlaceholder={SSA_HEADER.searchPlaceholder}
    />
  );
}

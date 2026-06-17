// TeamTargetsHeader — canonical PageHeader with the live, role-scoped
// filter bar. Now an async server component: resolves the user, computes
// the FilterScope, and renders <HeaderFilterBar> (was decorative
// region/month pills). Title/subtitle/search flow through as before.

import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { teamTargetsHeader } from "@/lib/team-targets-mock";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { liveDistrictNamesFor } from "@/lib/api/surfaces";

export async function TeamTargetsHeader() {
  const user = await getCurrentUser();
  const liveDistrictNames = await liveDistrictNamesFor(user);
  const scope = getFilterScope({ user, liveDistrictNames });
  return (
    <PageHeader
      title={teamTargetsHeader.title}
      subtitle={teamTargetsHeader.subtitle}
      filterBar={<HeaderFilterBar scope={scope} />}
      searchPlaceholder={teamTargetsHeader.searchPlaceholder}
    />
  );
}

// SpHeader — Special Projects chrome on the CANONICAL PageHeader
// (migrated off the EntityHeader system — the last consumer). Async
// server component: resolves the user, computes the role-scoped
// FilterScope, and renders the live <HeaderFilterBar> instead of the old
// decorative month/region/projectType/partner pills.

import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { specialProjectsHeader } from "@/lib/special-projects-mock";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";
import { liveDistrictNamesFor } from "@/lib/api/surfaces";

export async function SpHeader() {
  const user = await getCurrentUser();
  const liveDistrictNames = await liveDistrictNamesFor(user);
  const scope = getFilterScope({ user, liveDistrictNames });

  return (
    <PageHeader
      title={specialProjectsHeader.title}
      subtitle={specialProjectsHeader.subtitle}
      filterBar={<HeaderFilterBar scope={scope} />}
      // No header search box — the /special-projects/schools directory
      // has its own live search; the header slot falls back to the global
      // ⌘K palette to avoid two competing search inputs.
    />
  );
}

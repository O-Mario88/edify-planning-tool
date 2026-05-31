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

export async function SpHeader() {
  const user = await getCurrentUser();
  const scope = getFilterScope({ user });

  return (
    <PageHeader
      title={specialProjectsHeader.title}
      subtitle={specialProjectsHeader.subtitle}
      filterBar={<HeaderFilterBar scope={scope} />}
      searchPlaceholder={specialProjectsHeader.searchPlaceholder}
    />
  );
}

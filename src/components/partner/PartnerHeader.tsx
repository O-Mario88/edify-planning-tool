// PartnerHeader — async SERVER adapter over PageHeader for the partner
// dashboard. Resolves the signed-in partner, computes their scoped
// FilterScope, and renders the live <HeaderFilterBar> (FY/Quarter + the
// geography the partner is allowed to see). The old decorative pills and
// the dead "Filters" button are gone — the filter bar carries its own
// Advanced drawer.

import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";

export async function PartnerHeader() {
  const user = await getCurrentUser();
  const scope = getFilterScope({ user });
  return (
    <PageHeader
      title="Partner"
      subtitle="Schedule assigned school support, submit evidence, track confirmation, and follow payment progress."
      filterBar={<HeaderFilterBar scope={scope} />}
    />
  );
}

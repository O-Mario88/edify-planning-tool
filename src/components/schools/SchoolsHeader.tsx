import { PageHeader } from "@/components/ui/PageHeader";
import { HeaderFilterBar } from "@/components/shell/HeaderFilterBar";
import { schoolsHeader } from "@/lib/schools-mock";
import { getCurrentUser } from "@/lib/auth";
import { getFilterScope } from "@/lib/filters/scope-service";

// Thin adapter over the canonical <PageHeader>. Async server component:
// resolves the viewer, computes their role-scoped FilterScope, and mounts
// the LIVE <HeaderFilterBar> (URL-synced, cascading) — the page body reads
// the same URL via selectionFromSearchParams() so the filters actually
// re-scope the KPI strip + directory, not just the chips.
export async function SchoolsHeader() {
  const user = await getCurrentUser();
  const scope = getFilterScope({ user });
  return (
    <PageHeader
      title={schoolsHeader.title}
      subtitle={schoolsHeader.subtitle}
      filterBar={<HeaderFilterBar scope={scope} />}
      // No header search box here — the directory has its own live
      // school/id/district search. The header slot falls back to the
      // global ⌘K palette so there aren't two competing search inputs.
    />
  );
}

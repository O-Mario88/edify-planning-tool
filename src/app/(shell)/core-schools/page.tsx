import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { CorePageHeader } from "@/components/core/CorePageHeader";
import { CoreHealthBanner } from "@/components/core/CoreHealthPanel";
import { CoreDirectoryClient } from "@/components/core/CoreDirectoryClient";
import { coreHealthReport } from "@/lib/core/core-health";
import { getCurrentUser } from "@/lib/auth";

export const dynamic = "force-dynamic";

// Core School Directory. The directory rows + header pills are fetched live
// from edify-api (the database) by <CoreDirectoryClient>, which self-fetches
// /api/core-schools and renders canonical loading / empty / error states —
// no mock fallback.
export default async function CoreSchoolDashboard() {
  const user = await getCurrentUser();
  const health = coreHealthReport();

  return (
    <>
      <CorePageHeader
        icon="schools"
        title="Core Schools"
        subtitle="Live from the backend database (edify-api). Filtered from the School Directory by core status."
        searchPlaceholder="Search core schools"
      />
      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 space-y-3 lg:space-y-4 pt-3">
        <CoreHealthBanner report={health} />
        <CoreDirectoryClient role={user.role} />
      </div>
      <RoleBottomNav />
    </>
  );
}

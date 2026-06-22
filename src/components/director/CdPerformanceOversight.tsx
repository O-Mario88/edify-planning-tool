import { getCurrentUser } from "@/lib/auth";
import { fetchHrRoster, fetchPartners } from "@/lib/api/surfaces";
import { CdPerformanceOversightClient } from "./CdPerformanceOversightClient";

// CD executive analytics band — staff/partner/budget oversight from live backend
// data. The CD monitors team plans; they never open field planning surfaces.
export async function CdPerformanceOversight() {
  const user = await getCurrentUser();
  const [roster, partners] = await Promise.all([
    fetchHrRoster(user),
    fetchPartners(user),
  ]);
  return (
    <CdPerformanceOversightClient
      staff={roster.live ? roster.data.staff : []}
      partners={partners.live ? partners.data : []}
    />
  );
}

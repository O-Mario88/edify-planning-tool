// Deprecated: canonical URL is /partner/evidence.
// The earlier /dashboards/partner/evidence version also embedded a
// "Returned Corrections" panel — that lives at /partner/corrections
// as its own dedicated route, which is the correct factoring.

import { permanentRedirect } from "next/navigation";

export default function DeprecatedDashboardEvidence() {
  permanentRedirect("/partner/evidence");
}

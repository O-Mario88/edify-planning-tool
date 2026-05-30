// Deprecated: canonical URL is /partner/reports.

import { permanentRedirect } from "next/navigation";

export default function DeprecatedDashboardReports() {
  permanentRedirect("/partner/reports");
}

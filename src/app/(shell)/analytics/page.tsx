import { FieldAnalytics } from "@/components/analytics/FieldAnalytics";
import { CceoAnalytics } from "@/components/analytics/CceoAnalytics";
import { CountryAnalytics } from "@/components/director/CountryAnalytics";
import { getCurrentUser } from "@/lib/auth";
import { getDonorMetricSnapshot } from "@/lib/donor-metrics";
import type { DonorRoleScope } from "@/lib/donor-metrics-types";

// Field Performance & School Improvement Analytics — the evidence centre
// of the planning tool. Connects what staff planned → did → verified →
// changed at schools → literacy outcomes → funding accountability.
//
// Role-specific analytics surfaces:
//   • CCEO            → bespoke single-officer console
//   • CountryDirector → national Country Performance & Impact Analytics
//   • everyone else   → shared <FieldAnalytics /> surface
//
// Each surface is overlaid with a Donor Reporting Impact section computed
// server-side from the role-scoped donor snapshot — donor-ready figures,
// readiness score, and data-quality caveats are derived once and passed
// down so the UI never invents numbers.
export default async function AnalyticsPage() {
  const user = await getCurrentUser();
  const snapshot = getDonorMetricSnapshot({
    role: donorScopeForRole(user.role),
    userName: user.name,
    generatedBy: user.name,
  });

  if (user.role === "CCEO") return <CceoAnalytics donorSnapshot={snapshot} />;
  if (user.role === "CountryDirector") return <CountryAnalytics donorSnapshot={snapshot} />;
  return (
    <FieldAnalytics
      role={user.role}
      userName={user.name}
      donorSnapshot={snapshot}
    />
  );
}

function donorScopeForRole(role: string): DonorRoleScope {
  switch (role) {
    case "CCEO":              return "CCEO";
    case "CountryProgramLead": return "ProgramLead";
    case "ImpactAssessment":  return "ImpactAssessment";
    case "CountryDirector":   return "CountryDirector";
    case "RVP":               return "RVP";
    default:                  return "ProgramLead";
  }
}

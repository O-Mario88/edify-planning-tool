import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PageHeader } from "@/components/ui/PageHeader";
import { RecruitmentIntelligenceCard } from "@/components/analytics/RecruitmentIntelligenceCard";
import { RecruitmentDistrictTable } from "@/components/analytics/RecruitmentDistrictTable";

// Recruitment Intelligence page — the CD's directory replacement. Aggregated,
// drillable advisory: should we recruit more or focus on current schools?
// Access mirrors the backend RECRUITMENT_INTELLIGENCE_VIEW permission.
const ALLOWED = ["CountryDirector", "RVP", "ImpactAssessment", "CountryProgramLead", "CCEO", "Admin"];

export default async function RecruitmentPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.includes(user.role)) redirect(ROLE_REDIRECT[user.role] ?? "/");

  return (
    <>
      <PageHeader
        title="Recruitment Intelligence"
        subtitle="Recruit more, or focus on current schools? A backend-driven, role-scoped decision aid combining SSA readiness, capacity, clustering, data quality, partner strain, and impact. It advises where to expand and where to pause — it never recruits automatically."
      />
      <div className="px-4 sm:px-6 pt-2 pb-24 space-y-4">
        <RecruitmentIntelligenceCard />
        <RecruitmentDistrictTable />
      </div>
    </>
  );
}

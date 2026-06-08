import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { RecruitmentIntelligenceCard } from "@/components/analytics/RecruitmentIntelligenceCard";

// Recruitment Intelligence page — the CD's directory replacement. Aggregated,
// drillable advisory: should we recruit more or focus on current schools?
// Access mirrors the backend RECRUITMENT_INTELLIGENCE_VIEW permission.
const ALLOWED = ["CountryDirector", "RVP", "ImpactAssessment", "CountryProgramLead", "CCEO", "Admin"];

export default async function RecruitmentPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.includes(user.role)) redirect(ROLE_REDIRECT[user.role] ?? "/");

  return (
    <div className="px-4 sm:px-6 pt-4 pb-24 space-y-4">
      <SectionHeader
        tier="strategic"
        eyebrow="Recruitment"
        title="Recruit more, or focus on current schools?"
        description="A backend-driven, role-scoped decision aid combining SSA readiness, capacity, clustering, data quality, partner strain, and impact. It advises where to expand and where to pause — it never recruits automatically."
      />
      <RecruitmentIntelligenceCard />
    </div>
  );
}

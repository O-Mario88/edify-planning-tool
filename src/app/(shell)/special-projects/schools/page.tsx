import { redirect } from "next/navigation";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { directoryRecords } from "@/lib/school-directory/directory";
import { buildProjectSchoolDirectory } from "@/lib/projects/project-school-directory";
import { ProjectSchoolDirectory } from "@/components/special-projects/ProjectSchoolDirectory";
import { SpHeader } from "@/components/special-projects/SpHeader";
import { MetricStrip } from "@/components/ui/MetricStrip";

// Special Project Schools — a PROJECT-GROUPED directory. Each project is a
// card holding only its assigned schools (a mini school-portfolio per
// project). This is NOT the general School Directory: unassigned schools and
// schools outside the user's scope never appear. Source of truth stays the
// directory (active SchoolProjectMembership ∩ scoped directory records).
export default async function SpecialProjectSchoolsPage() {
  const user = await getCurrentUser();
  // Partners have their own surfaces; everyone else with project scope lands here.
  if (["PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer"].includes(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }

  const currentUser = toCurrentUser(user);
  // CCEO/PL see only their portfolio/team schools inside each card; country
  // and coordination roles see all assigned schools in their visible projects.
  const scoped: Set<string> | "all" =
    user.role === "CCEO" || user.role === "CountryProgramLead"
      ? new Set(directoryRecords(user.staffId, user.role).map((s) => s.schoolId))
      : "all";

  const { cards, summary } = buildProjectSchoolDirectory(currentUser, scoped);

  const metrics = [
    { key: "active",    label: "Active Projects",  value: summary.activeProjects },
    { key: "schools",   label: "Project Schools",  value: summary.projectSchools },
    { key: "trained",   label: "Schools Trained",  value: summary.schoolsTrained },
    { key: "followups", label: "Follow-Ups Done",  value: summary.followUpsCompleted },
    { key: "improved",  label: "Schools Improved", value: summary.schoolsImproved, tone: summary.schoolsImproved > 0 ? ("good" as const) : ("default" as const) },
    { key: "evidence",  label: "Evidence Pending", value: summary.evidencePending, tone: summary.evidencePending > 0 ? ("alert" as const) : ("default" as const) },
  ];

  return (
    <>
      <SpHeader />
      <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        <header>
          <h1 className="text-[17px] font-extrabold tracking-tight">Special Project Schools</h1>
          <p className="text-[12px] muted">Schools assigned to active projects and targeted interventions, grouped by project.</p>
        </header>

        {/* Summary row */}
        <MetricStrip columns="grid-cols-2 sm:grid-cols-3 lg:grid-cols-6" metrics={metrics} />

        <ProjectSchoolDirectory cards={cards} userRole={user.role} />
      </div>
    </>
  );
}

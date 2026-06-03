import { redirect } from "next/navigation";
import { School, GraduationCap, CalendarCheck, TrendingUp, FileWarning, Briefcase } from "lucide-react";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { directoryRecords } from "@/lib/school-directory/directory";
import { buildProjectSchoolDirectory } from "@/lib/projects/project-school-directory";
import { ProjectSchoolDirectory } from "@/components/special-projects/ProjectSchoolDirectory";
import { SpHeader } from "@/components/special-projects/SpHeader";

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

  const kpis = [
    { label: "Active Projects",     value: summary.activeProjects,     Icon: Briefcase,     tone: "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]" },
    { label: "Project Schools",     value: summary.projectSchools,     Icon: School,        tone: "bg-blue-50 text-blue-700" },
    { label: "Schools Trained",     value: summary.schoolsTrained,     Icon: GraduationCap, tone: "bg-violet-50 text-violet-700" },
    { label: "Follow-Ups Done",     value: summary.followUpsCompleted, Icon: CalendarCheck, tone: "bg-amber-50 text-amber-700" },
    { label: "Schools Improved",    value: summary.schoolsImproved,    Icon: TrendingUp,    tone: "bg-emerald-50 text-emerald-700" },
    { label: "Evidence Pending",    value: summary.evidencePending,    Icon: FileWarning,   tone: "bg-rose-50 text-rose-700" },
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
        <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {kpis.map((k) => (
            <div key={k.label} className="card rounded-2xl p-3 flex items-center gap-2.5">
              <span className={`h-9 w-9 rounded-xl grid place-items-center shrink-0 ${k.tone}`}><k.Icon size={16} /></span>
              <div className="min-w-0">
                <div className="text-[20px] font-extrabold tabular leading-none">{k.value}</div>
                <div className="text-[11px] muted leading-tight mt-0.5">{k.label}</div>
              </div>
            </div>
          ))}
        </section>

        <ProjectSchoolDirectory cards={cards} userRole={user.role} />
      </div>
    </>
  );
}

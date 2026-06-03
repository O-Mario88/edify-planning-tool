import { getCurrentUser } from "@/lib/auth";
import { SpHeader } from "@/components/special-projects/SpHeader";
import { ProjectActivityPipeline, type PipelineRowVM } from "@/components/special-projects/ProjectActivityPipeline";
import { partnerPipelineActivities } from "@/lib/projects/project-activities";
import { projectById } from "@/lib/special-projects-mock";
import { intakeSchools } from "@/lib/intake/intake-mock";

// Project Activity Pipeline — the consolidated, role-aware queue for partner-
// delivered project work moving Assigned → Scheduled → Evidence → Salesforce
// → IA → Payment. Each role sees the whole board but can only act on the
// stages it owns (driven by the workflow state machine).
export default async function ProjectPipelinePage() {
  const user = await getCurrentUser();

  const rows: PipelineRowVM[] = partnerPipelineActivities().map((a) => {
    const project = projectById(a.projectId);
    const school = a.schoolId ? intakeSchools.find((s) => s.schoolId === a.schoolId) : undefined;
    return {
      id: a.id,
      projectId: a.projectId,
      projectShortName: project?.projectShortName ?? a.projectId,
      schoolName: school?.schoolName ?? a.schoolId ?? "—",
      schoolId: a.schoolId,
      district: school?.district,
      intervention: a.interventionId,
      activityType: a.activityType,
      partnerName: a.partnerName,
      salesforceActivityId: a.salesforceActivityId,
      salesforceType: a.salesforceActivityType,
      evidenceNote: a.evidenceNote,
      returnReason: a.returnReason,
      paymentRef: a.paymentRef,
      workflowStatus: a.workflowStatus!,
    };
  });

  return (
    <>
      <SpHeader />
      <div className="px-3 sm:px-4 md:px-6 pb-24 md:pb-6 space-y-3 md:space-y-4">
        <header>
          <h1 className="text-[17px] font-extrabold tracking-tight">Project Activity Pipeline</h1>
          <p className="text-[12px] muted">Partner-delivered project work — assigned → scheduled → evidence → Salesforce → IA verification → payment. You can act on the stages your role owns.</p>
        </header>
        <ProjectActivityPipeline rows={rows} userRole={user.role} />
      </div>
    </>
  );
}

import { notFound } from "next/navigation";
import { LineChart } from "lucide-react";
import { EntityDetail } from "@/components/shell/EntityDetail";
import { ProjectImpactAnalytics } from "@/components/special-projects/ProjectImpactAnalytics";
import { projectById, PROJECT_CATEGORY_LABEL, type ProjectCategory } from "@/lib/special-projects-mock";
import { computeProjectAnalytics } from "@/lib/projects/project-analytics";

// Project impact analytics — reach + verified delivery + linked-intervention
// improvement + overall 8-intervention SSA + donor-ready, for one project.
export default async function ProjectImpactPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = projectById(id);
  const snapshot = computeProjectAnalytics(id);
  if (!project || !snapshot) return notFound();

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",     href: "/dashboard" },
        { label: "Projects", href: "/special-projects" },
        { label: project.projectName, href: `/projects/${id}` },
        { label: "Impact" },
      ]}
      title={`${project.projectName} — Impact`}
      subtitle={`${PROJECT_CATEGORY_LABEL[project.projectCategory as ProjectCategory]} · ${project.primaryInterventionId}. Reach + verified delivery + measured improvement.`}
      Icon={LineChart}
    >
      <ProjectImpactAnalytics snapshot={snapshot} />
    </EntityDetail>
  );
}

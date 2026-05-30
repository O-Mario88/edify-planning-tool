import { notFound } from "next/navigation";
import {
  Sparkles,
  Target,
  Wallet,
  Activity,
  Users,
  ShieldCheck,
} from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import { specialProjects, type ProjectStatus } from "@/lib/special-projects-mock";

const STATUS_BADGE: Record<ProjectStatus, { tone: "green" | "amber" | "rose" | "violet" | "edify"; label: string }> = {
  "Active":    { tone: "green",  label: "Active" },
  "Planning":  { tone: "edify",  label: "Planning" },
  "At Risk":   { tone: "amber",  label: "At Risk" },
  "Delayed":   { tone: "rose",   label: "Delayed" },
  "Completed": { tone: "violet", label: "Completed" },
};

function fmtUgx(n?: number) {
  if (!n) return "—";
  return `UGX ${(n / 1_000_000).toFixed(1)}M`;
}

export default async function ProjectDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = specialProjects.find((p) => p.projectId === id);
  if (!project) return notFound();

  const enrolledPct = project.targetNumber
    ? Math.round(((project.schoolsEnrolled ?? 0) / project.targetNumber) * 100)
    : 0;

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",     href: "/dashboard" },
        { label: "Projects", href: "/special-projects" },
        { label: project.projectName },
      ]}
      title={project.projectName}
      subtitle={`${project.projectType} · ${project.financialYear}. Partner: ${project.assignedPartnerName ?? "Unassigned"}.`}
      Icon={Sparkles}
      badge={STATUS_BADGE[project.status]}
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi label="Target"           value={`${project.targetNumber} ${project.impactMeasurementType.toLowerCase()}`} caption="Goal for this FY"           Icon={Target}     tone="edify" />
        <DetailKpi label="Enrolled"         value={String(project.schoolsEnrolled ?? 0)} caption={`${enrolledPct}% of target`}                                   Icon={Activity}   tone={enrolledPct >= 80 ? "green" : enrolledPct >= 50 ? "amber" : "rose"} />
        <DetailKpi label="Teachers Impacted" value={String(project.teachersImpacted ?? 0)} caption="Cumulative this FY"                                          Icon={Users}      tone="violet" />
        <DetailKpi label="Budget Utilization" value={`${project.budgetUtilizationPct ?? 0}%`} caption={fmtUgx(project.totalAllocation)}                          Icon={Wallet}     tone={(project.budgetUtilizationPct ?? 0) >= 80 ? "green" : (project.budgetUtilizationPct ?? 0) >= 50 ? "amber" : "rose"} />
      </section>

      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        <div className="col-span-12 md:col-span-7">
          <DetailFacts
            rows={[
              { label: "Project ID",         value: project.projectId },
              { label: "Type",               value: project.projectType },
              { label: "Financial Year",     value: project.financialYear },
              { label: "Start Date",         value: project.startDate },
              { label: "End Date",           value: project.endDate },
              { label: "Partner",            value: project.assignedPartnerName ?? "—" },
              { label: "Partner Certification", value: project.partnerCertificationStatus ?? "—" },
              { label: "Partner Capacity",   value: project.partnerCapacityStatus ?? "—" },
              { label: "Health Score",       value: `${project.healthScore.toFixed(1)} / 5` },
            ]}
          />
        </div>
        <div className="col-span-12 md:col-span-5 card p-3.5">
          <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <ShieldCheck size={13} className="text-emerald-600" />
            Verification
          </h3>
          <p className="text-[11.5px] muted mt-1 leading-snug">
            Salesforce logging is{" "}
            <span className="font-extrabold text-[var(--color-edify-text)]">
              {project.salesforceLoggingRequired ? "required" : "not required"}
            </span>
            {" "}for this project. Special-project work is excluded from SSA-driven recommendations.
          </p>
          <dl className="mt-3 space-y-2 text-[11.5px]">
            <Row term="Verification status" value={project.verificationStatus ?? "—"} />
            <Row term="Sessions completed"  value={String(project.sessionsCompleted ?? 0)} />
            <Row term="Participants"        value={String(project.participantsReached ?? 0)} />
          </dl>
        </div>
      </section>
    </EntityDetail>
  );
}

function Row({ term, value }: { term: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="muted">{term}</dt>
      <dd className="font-extrabold tabular">{value}</dd>
    </div>
  );
}

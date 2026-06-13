// Compact "Special projects" card for role dashboards — surfaces the project
// work landscape (schools, open follow-ups, partner pipeline) with links into
// the project surfaces. Async server component; scopes like the directory.

import Link from "next/link";
import { Sparkles, ArrowRight, Handshake } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
import { MetricStrip } from "@/components/ui/MetricStrip";
import { toCurrentUser, type DemoUser } from "@/lib/auth";
import { directoryRecords } from "@/lib/school-directory/directory";
import { buildProjectSchoolDirectory } from "@/lib/projects/project-school-directory";
import { computeProjectPlanningGaps, projectPlanningGapCount } from "@/lib/projects/project-planning-gaps";
import { partnerPipelineActivities } from "@/lib/projects/project-activities";

export function ProjectWorkCard({ user }: { user: DemoUser }) {
  const currentUser = toCurrentUser(user);
  const scoped: Set<string> | "all" =
    user.role === "CCEO" || user.role === "CountryProgramLead"
      ? new Set(directoryRecords(user.staffId, user.role).map((s) => s.schoolId))
      : "all";

  const { cards, summary } = buildProjectSchoolDirectory(currentUser, scoped);
  if (cards.length === 0) return null; // no project schools in scope → hide

  const gapTotal = projectPlanningGapCount(computeProjectPlanningGaps(currentUser, scoped));

  const pipeline = partnerPipelineActivities();
  const awaitingIA = pipeline.filter((a) => a.workflowStatus === "SubmittedToIA").length;
  const readyForPayment = pipeline.filter((a) => a.workflowStatus === "IAVerified").length;
  const awaitingPartner = pipeline.filter((a) => a.workflowStatus === "AssignedToPartner" || a.workflowStatus === "PartnerScheduled").length;

  const stats = [
    { key: "schools", label: "Project schools", value: summary.projectSchools, href: "/special-projects/schools" },
    { key: "followups", label: "Open follow-ups", value: gapTotal, href: "/planning" },
    { key: "improved", label: "Schools improved", value: summary.schoolsImproved, href: "/special-projects/schools" },
  ];
  const pipelineStats = [
    { key: "awaitingPartner", label: "Awaiting partner schedule", value: awaitingPartner },
    { key: "awaitingIA", label: "Awaiting IA verification", value: awaitingIA },
    { key: "readyForPayment", label: "Ready for payment", value: readyForPayment },
  ];

  return (
    <SectionCard
      icon={<Sparkles size={13} />}
      title="Special projects"
      actions={<Link href="/special-projects/schools" className="text-[12px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1">Open <ArrowRight size={12} /></Link>}
    >
      <MetricStrip bare columns="grid-cols-3" metrics={stats} />
      <div className="mt-2.5 pt-2.5 border-t border-[var(--color-edify-divider)]">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11.5px] font-bold inline-flex items-center gap-1.5"><Handshake size={12} className="text-[var(--color-edify-primary)]" />Partner pipeline</span>
          <Link href="/special-projects/pipeline" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1">Pipeline <ArrowRight size={11} /></Link>
        </div>
        <MetricStrip bare columns="grid-cols-3" metrics={pipelineStats} />
      </div>
    </SectionCard>
  );
}

// Compact "Special projects" card for role dashboards — surfaces the project
// work landscape (schools, open follow-ups, partner pipeline) with links into
// the project surfaces. Async server component; scopes like the directory.

import Link from "next/link";
import { Sparkles, ArrowRight, GraduationCap, ClipboardList, Handshake } from "lucide-react";
import { SectionCard } from "@/components/ui/primitives";
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
    { label: "Project schools", value: summary.projectSchools, Icon: GraduationCap, href: "/special-projects/schools" },
    { label: "Open follow-ups", value: gapTotal, Icon: ClipboardList, href: "/planning" },
    { label: "Schools improved", value: summary.schoolsImproved, Icon: Sparkles, href: "/special-projects/schools" },
  ];
  const pipelineStats = [
    { label: "Awaiting partner schedule", value: awaitingPartner },
    { label: "Awaiting IA verification", value: awaitingIA },
    { label: "Ready for payment", value: readyForPayment },
  ];

  return (
    <SectionCard
      icon={<Sparkles size={13} />}
      title="Special projects"
      actions={<Link href="/special-projects/schools" className="text-[12px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1">Open <ArrowRight size={12} /></Link>}
    >
      <div className="grid grid-cols-3 gap-2">
        {stats.map((s) => (
          <Link key={s.label} href={s.href} className="rounded-lg border border-[var(--color-edify-border)] p-2.5 hover:bg-[var(--color-edify-soft)]/40 transition-colors">
            <div className="flex items-center gap-1.5 muted text-[10.5px] font-semibold"><s.Icon size={11} />{s.label}</div>
            <div className="text-[20px] font-extrabold tabular leading-none mt-1">{s.value}</div>
          </Link>
        ))}
      </div>
      <div className="mt-2.5 pt-2.5 border-t border-[var(--color-edify-divider)]">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11.5px] font-bold inline-flex items-center gap-1.5"><Handshake size={12} className="text-[var(--color-edify-primary)]" />Partner pipeline</span>
          <Link href="/special-projects/pipeline" className="text-[11.5px] font-semibold text-[var(--color-edify-primary)] inline-flex items-center gap-1">Pipeline <ArrowRight size={11} /></Link>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center">
          {pipelineStats.map((p) => (
            <div key={p.label} className="rounded-lg bg-[var(--color-edify-soft)]/40 p-2">
              <div className="text-[16px] font-extrabold tabular">{p.value}</div>
              <div className="text-[10px] muted leading-tight mt-0.5">{p.label}</div>
            </div>
          ))}
        </div>
      </div>
    </SectionCard>
  );
}

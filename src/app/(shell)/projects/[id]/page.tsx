import { notFound } from "next/navigation";
import Link from "next/link";
import {
  Sparkles,
  Target,
  Activity,
  Users,
  ShieldCheck,
  Layers,
  TrendingUp,
  TrendingDown,
  Minus,
  CalendarCheck,
  Lightbulb,
  LineChart,
} from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { specialProjects, type ProjectStatus } from "@/lib/special-projects-mock";
import { computeProjectImpact, projectVsNonProject } from "@/lib/projects/project-impact";
import { recommendSchoolsForProject } from "@/lib/projects/project-eligibility";
import { activitiesForProject } from "@/lib/projects/project-activities";

const STATUS_BADGE: Record<ProjectStatus, { tone: "green" | "amber" | "rose" | "violet" | "edify"; label: string }> = {
  "Draft":                 { tone: "edify",  label: "Draft" },
  "Active":                { tone: "green",  label: "Active" },
  "School Selection Open": { tone: "edify",  label: "School Selection Open" },
  "Training Planned":      { tone: "edify",  label: "Training Planned" },
  "Follow-Up Active":      { tone: "edify",  label: "Follow-Up Active" },
  "Monitoring":            { tone: "amber",  label: "Monitoring" },
  "Completed":             { tone: "violet", label: "Completed" },
  "Paused":                { tone: "amber",  label: "Paused" },
  "Closed":                { tone: "violet", label: "Closed" },
};

function trendIcon(v: number) {
  if (v > 0) return <TrendingUp size={12} className="text-emerald-600" />;
  if (v < 0) return <TrendingDown size={12} className="text-rose-600" />;
  return <Minus size={12} className="text-slate-400" />;
}

export default async function ProjectDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const project = specialProjects.find((p) => p.projectId === id);
  if (!project) return notFound();

  const impact = computeProjectImpact(id);
  const comparison = projectVsNonProject(id);
  const recommendations = recommendSchoolsForProject(project).filter((r) => !r.alreadyAssigned).slice(0, 8);
  const activities = activitiesForProject(id);

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
      {/* Intervention mapping — the project's link to the SSA diagnostic */}
      <section className="card p-3.5">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
          <Layers size={13} className="text-[var(--color-edify-primary)]" />
          SSA Intervention Mapping
        </h3>
        <p className="text-[11.5px] muted mt-1 leading-snug">
          This project is a targeted initiative — not one of the 8 SSA interventions. It is designed to
          close the gap in the interventions below, and its impact is measured against them.
        </p>
        <Link href={`/projects/${project.projectId}/impact`} className="float-right inline-flex items-center gap-1 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] text-white text-[12px] font-bold hover:bg-[var(--color-edify-dark)]">
          <LineChart size={13} /> Impact analytics
        </Link>
        <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-bold muted">Primary:</span>
          <span className="inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11.5px] font-extrabold bg-[var(--color-edify-primary)]/10 text-[var(--color-edify-primary)]">
            {project.primaryInterventionId}
          </span>
          {project.secondaryInterventionIds?.length ? (
            <>
              <span className="text-[11px] font-bold muted ml-2">Secondary:</span>
              {project.secondaryInterventionIds.map((s) => (
                <span key={s} className="inline-flex items-center px-2 py-[3px] rounded-md text-[11.5px] font-semibold bg-[var(--color-edify-soft)] text-[var(--color-edify-text)]">
                  {s}
                </span>
              ))}
            </>
          ) : null}
        </div>
      </section>

      {/* Impact KPIs */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi label="Schools Enrolled" value={String(impact?.schoolsEnrolled ?? 0)} caption={`${impact?.schoolsWithSsa ?? 0} with SSA data`} Icon={Activity} tone="edify" />
        <DetailKpi label={`Avg. ${project.primaryInterventionId} change`} value={impact ? `${impact.avgImprovement > 0 ? "+" : ""}${impact.avgImprovement.toFixed(1)}` : "—"} caption={impact ? `${impact.avgBefore.toFixed(1)} → ${impact.avgAfter.toFixed(1)}` : "no data"} Icon={Target} tone={(impact?.avgImprovement ?? 0) > 0 ? "green" : "amber"} />
        <DetailKpi label="Schools Improved" value={String(impact?.schoolsImproved ?? 0)} caption={`${impact?.schoolsDeclined ?? 0} declined · ${impact?.schoolsFlat ?? 0} flat`} Icon={Users} tone="violet" />
        <DetailKpi label="Schools Trained" value={String(impact?.schoolsTrained ?? 0)} caption={`${impact?.schoolsFollowedUp ?? 0} followed up`} Icon={CalendarCheck} tone="edify" />
      </section>

      {/* Project vs non-project comparison */}
      {comparison && (comparison.project.count > 0 || comparison.nonProject.count > 0) && (
        <section className="card p-3.5">
          <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <TrendingUp size={13} className="text-emerald-600" />
            Did the project make a difference?
          </h3>
          <p className="text-[11.5px] muted mt-1 leading-snug">
            Project schools vs. comparable non-project schools weak in {comparison.intervention}.
          </p>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3">
              <div className="text-[11px] font-bold text-emerald-800">Project schools ({comparison.project.count})</div>
              <div className="text-[20px] font-extrabold tabular text-emerald-700 mt-0.5">{comparison.project.avgImprovement > 0 ? "+" : ""}{comparison.project.avgImprovement.toFixed(1)}</div>
              <div className="text-[11px] muted">{comparison.project.avgBefore.toFixed(1)} → {comparison.project.avgAfter.toFixed(1)} on {comparison.intervention}</div>
            </div>
            <div className="rounded-lg border border-[var(--color-edify-border)] p-3">
              <div className="text-[11px] font-bold muted">Comparable non-project ({comparison.nonProject.count})</div>
              <div className="text-[20px] font-extrabold tabular mt-0.5">{comparison.nonProject.avgImprovement > 0 ? "+" : ""}{comparison.nonProject.avgImprovement.toFixed(1)}</div>
              <div className="text-[11px] muted">{comparison.nonProject.avgBefore.toFixed(1)} → {comparison.nonProject.avgAfter.toFixed(1)} on {comparison.intervention}</div>
            </div>
          </div>
          <div className="mt-2 text-[12px] font-semibold inline-flex items-center gap-1.5">
            {trendIcon(comparison.improvementGap)}
            Project advantage: <span className="font-extrabold">{comparison.improvementGap > 0 ? "+" : ""}{comparison.improvementGap.toFixed(1)}</span> vs. similar schools
          </div>
        </section>
      )}

      {/* Assigned schools — per-school before/after on mapped intervention */}
      <SectionCard icon={<Activity size={13} />} title={`Project Schools (${impact?.schoolsEnrolled ?? 0})`}>
        {impact && impact.perSchool.length > 0 ? (
          <div className="overflow-x-auto scrollbar -mx-1 px-1">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">School</th>
                  <th scope="col" className="text-right">{project.primaryInterventionId} before</th>
                  <th scope="col" className="text-right">after</th>
                  <th scope="col" className="text-left">Change</th>
                  <th scope="col" className="text-left">Trained</th>
                  <th scope="col" className="text-left">Follow-up</th>
                </tr>
              </thead>
              <tbody>
                {impact.perSchool.map((s) => (
                  <tr key={s.schoolId} className="hover:bg-[var(--color-edify-soft)]/40">
                    <td><Link href={`/schools/${s.schoolId}`} className="font-semibold hover:text-[var(--color-edify-primary)] hover:underline">{s.schoolName}</Link></td>
                    <td className="text-right tabular muted">{s.interventionScoreBefore ?? "—"}</td>
                    <td className="text-right tabular font-bold">{s.interventionScoreAfter ?? "—"}</td>
                    <td>
                      <span className="inline-flex items-center gap-1 text-[12px] font-bold">
                        {s.improvementValue !== undefined ? trendIcon(s.improvementValue) : null}
                        {s.improvementValue !== undefined ? `${s.improvementValue > 0 ? "+" : ""}${s.improvementValue.toFixed(1)}` : "no SSA"}
                      </span>
                    </td>
                    <td>{s.trained ? <StatusBadge tone="green">Yes</StatusBadge> : <span className="muted text-[11px]">—</span>}</td>
                    <td>{s.followedUp ? <StatusBadge tone="blue">Yes</StatusBadge> : <span className="muted text-[11px]">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[12px] muted py-4 text-center">No schools assigned yet. Use the School Directory to assign schools to this project.</p>
        )}
      </SectionCard>

      {/* Recommended schools — eligibility by SSA weakness */}
      {recommendations.length > 0 && (
        <SectionCard icon={<Lightbulb size={13} />} title="Recommended schools" subtitle={`Weak in ${project.primaryInterventionId} and not yet enrolled — assign from the School Directory.`}>
          <ul className="space-y-1.5">
            {recommendations.map((r) => (
              <li key={r.schoolId} className="flex items-center justify-between gap-3 rounded-lg border border-[var(--color-edify-border)] px-3 py-2">
                <div className="min-w-0">
                  <Link href={`/schools/${r.schoolId}`} className="text-[12.5px] font-bold hover:text-[var(--color-edify-primary)] hover:underline">{r.schoolName}</Link>
                  <div className="text-[11px] muted truncate">{r.district} · {r.reason}</div>
                </div>
                <span className="shrink-0 inline-flex items-center px-2 py-[2px] rounded-md text-[10.5px] font-extrabold bg-amber-50 text-amber-700">
                  {r.matchedIntervention} {r.weakInterventionScore}/10
                </span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {/* Project activities */}
      <SectionCard icon={<CalendarCheck size={13} />} title={`Project Activities (${activities.length})`}>
        {activities.length > 0 ? (
          <div className="overflow-x-auto scrollbar -mx-1 px-1">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Activity</th>
                  <th scope="col" className="text-left">Delivery</th>
                  <th scope="col" className="text-left">When</th>
                  <th scope="col" className="text-left">Status</th>
                  <th scope="col" className="text-left">Salesforce</th>
                  <th scope="col" className="text-left">IA</th>
                </tr>
              </thead>
              <tbody>
                {activities.map((a) => (
                  <tr key={a.id} className="hover:bg-[var(--color-edify-soft)]/40">
                    <td className="font-semibold">{a.activityType}</td>
                    <td className="text-[12px] muted">{a.deliveryType === "partner" ? (a.partnerName ?? "Partner") : (a.staffName ?? "Staff")}</td>
                    <td className="text-[12px] muted whitespace-nowrap">{a.scheduledDate ?? a.plannedMonth ?? a.plannedWeek ?? "—"}</td>
                    <td><StatusBadge tone={a.status === "Completed" ? "green" : a.status === "Cancelled" ? "grey" : "blue"}>{a.status}</StatusBadge></td>
                    <td className="text-[12px] tabular muted">{a.salesforceActivityId ?? "—"}</td>
                    <td><StatusBadge tone={a.iaVerificationStatus === "Confirmed" ? "green" : a.iaVerificationStatus === "Submitted" ? "amber" : "grey"}>{a.iaVerificationStatus}</StatusBadge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-[12px] muted py-4 text-center">No project activities scheduled yet.</p>
        )}
      </SectionCard>

      {/* Facts + verification (kept from the original detail) */}
      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        <div className="col-span-12 md:col-span-7">
          <DetailFacts
            rows={[
              { label: "Project ID",       value: project.projectId },
              { label: "Type",             value: project.projectType },
              { label: "Primary intervention", value: project.primaryInterventionId },
              { label: "Scope",            value: project.scopeKind ?? "country" },
              { label: "Financial Year",   value: project.financialYear },
              { label: "Start Date",       value: project.startDate },
              { label: "End Date",         value: project.endDate },
              { label: "Coordinator",      value: project.coordinatorName ?? "—" },
              { label: "Partner",          value: project.assignedPartnerName ?? "—" },
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
            <Row term="Schools assessed"   value={String(impact?.schoolsAssessed ?? 0)} />
            <Row term="Activities logged"  value={String(activities.length)} />
            <Row term="IA confirmed"        value={String(activities.filter((a) => a.iaVerificationStatus === "Confirmed").length)} />
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

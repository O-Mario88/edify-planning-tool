import { notFound } from "next/navigation";
import { FileText, AlertTriangle, CheckCircle2, MessageCircle } from "lucide-react";
import { EntityDetail, DetailKpi, DetailFacts } from "@/components/shell/EntityDetail";
import { dailyDebriefs, debriefsForUser } from "@/lib/field-intelligence-mock";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";

export default async function DebriefDetail({ params }: { params: Promise<{ id: string }> }) {
  // Fabricated daily debrief (named staff, reflections) — no live debrief backend
  // behind this detail. Withhold rather than render an invented field report.
  if (!isMockAllowed()) return notFound();

  const { id } = await params;
  const d = dailyDebriefs.find((x) => x.id === id);
  if (!d) return notFound();

  // Access guard: only render this debrief if the role-aware filter would
  // include it for the signed-in user. CD/HR/RVP/IA/Accountant never see
  // raw daily debriefs, so they 404 here.
  const demo = await getCurrentUser();
  const user = toCurrentUser(demo);
  const allowed = debriefsForUser(user).some((x) => x.id === d.id);
  if (!allowed) return notFound();

  return (
    <EntityDetail
      breadcrumbs={[
        { label: "Home",     href: "/dashboard" },
        { label: "Debriefs", href: "/debriefs" },
        { label: `${d.staffName} · ${d.date}` },
      ]}
      title={`${d.staffName} — ${d.date}`}
      subtitle={`${d.weekStartDate} → ${d.weekEndDate} · ${d.financialYear}`}
      Icon={FileText}
      badge={{ tone: "edify", label: d.systemClassification }}
    >
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <DetailKpi label="Planned"    value={String(d.plannedActivities)}    Icon={FileText} tone="edify" />
        <DetailKpi label="Completed"  value={String(d.completedActivities)}  Icon={CheckCircle2} tone="green" />
        <DetailKpi label="Verified"   value={String(d.verifiedActivities)}   Icon={CheckCircle2} tone="green" />
        <DetailKpi label="Incomplete" value={String(d.incompleteActivities)} Icon={AlertTriangle} tone="rose" />
      </section>

      <section className="grid grid-cols-12 gap-3 md:gap-4 items-start">
        <div className="col-span-12 md:col-span-7 card p-3.5 space-y-3">
          <h3 className="text-[13px] font-extrabold tracking-tight">Field Reflection</h3>
          <Block title="How did the day go?" body={d.howDayWent} />
          <Block title="What went well?" body={d.whatWentWell || "—"} />
          <Block title="What did not go well?" body={d.whatDidNotGoWell || "—"} />
          <Block title="Why?" body={d.whyItDidNotGoWell || "—"} />
          <Block title="What I did about it" body={d.whatStaffDidAboutIt || "—"} />
          <Block title="What I'll do differently" body={d.whatToDoDifferentlyNextTime || "—"} />
        </div>
        <div className="col-span-12 md:col-span-5">
          <DetailFacts
            rows={[
              { label: "Staff",            value: d.staffName },
              { label: "Program Lead",     value: d.programLeadId },
              { label: "Country Director", value: d.countryDirectorId ?? "—" },
              { label: "Financial Year",   value: d.financialYear },
              { label: "Classification",   value: d.systemClassification },
              { label: "Review status",    value: d.supervisorReviewStatus },
            ]}
          />
          {d.supportNeeded.length > 0 && (
            <div className="card rounded-2xl p-3 mt-3">
              <h3 className="text-[12px] font-extrabold tracking-tight mb-1.5 inline-flex items-center gap-1.5">
                <MessageCircle size={12} /> Support requested
              </h3>
              <div className="flex flex-wrap gap-1">
                {d.supportNeeded.map((s) => (
                  <span key={s} className="px-2 py-[2px] rounded-full bg-sky-100 text-sky-700 text-caption font-extrabold">
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>
    </EntityDetail>
  );
}

function Block({ title, body }: { title: string; body: string }) {
  return (
    <div>
      <div className="text-caption muted font-bold uppercase tracking-wide">{title}</div>
      <p className="text-[12px] leading-snug mt-0.5">{body}</p>
    </div>
  );
}

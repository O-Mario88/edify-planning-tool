import { FileText } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { debriefsForUser, type DebriefClassification } from "@/lib/field-intelligence-mock";
import { getCurrentUser, toCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

const CLASS_TONE: Record<DebriefClassification, "amber" | "rose" | "violet" | "blue" | "slate"> = {
  "School Availability Issue":     "amber",
  "Route / Travel Issue":          "amber",
  "Planning Issue":                "violet",
  "Funding Issue":                 "rose",
  "Partner Delivery Issue":        "violet",
  "Salesforce / System Issue":     "blue",
  "Evidence / Verification Issue": "blue",
  "Staff Support Needed":          "rose",
  "Protected Field Constraint":    "slate",
  "Accountability Concern":        "rose",
};

export default async function DebriefsIndex() {
  // Raw daily debriefs are restricted: CD/HR/RVP/IA/Accountant get an
  // empty list (they consume weekly compiled reports instead). PL sees
  // their team; CCEO sees their own.
  const demo = await getCurrentUser();
  const user = toCurrentUser(demo);

  // Daily debriefs here are hand-mocked (fabricated named staff + reflections);
  // the live debrief pipeline persists via the DailyDebrief backend, not this list.
  // Never render fabricated field debriefs in production.
  if (!isMockAllowed()) {
    return (
      <EntityIndex
        title="Daily Field Debriefs"
        subtitle="Every debrief submitted across the team. Pattern-detection rolls these up into weekly leadership decisions."
        Icon={FileText}
        count={0}
        searchPlaceholder="Search by staff, date, classification"
      >
        <InsufficientData surface="the daily field debriefs" detail="Field debriefs are withheld until this list is wired to the live debrief backend — no fabricated staff debriefs are shown." />
      </EntityIndex>
    );
  }

  const visible = debriefsForUser(user);

  return (
    <EntityIndex
      title="Daily Field Debriefs"
      subtitle="Every debrief submitted across the team. Pattern-detection rolls these up into weekly leadership decisions."
      Icon={FileText}
      count={visible.length}
      searchPlaceholder="Search by staff, date, classification"
    >
      {visible.length === 0 ? (
        <section className="card rounded-2xl p-6 text-center">
          <div className="text-[13px] font-extrabold tracking-tight">
            No daily debriefs visible to your role.
          </div>
          <p className="text-[11.5px] muted mt-1 leading-snug">
            Raw daily debriefs stay close to the field. Your role consumes weekly
            compiled reports instead.
          </p>
        </section>
      ) : (
        <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
          {visible.map((d) => (
            <IndexRow
              key={d.id}
              href={`/debriefs/${d.id}`}
              Icon={FileText}
              title={`${d.staffName} — ${d.date}`}
              subtitle={`${d.howDayWent} · ${d.plannedActivities} planned / ${d.verifiedActivities} verified`}
              meta={d.whatWentWell?.slice(0, 96) || "—"}
              badges={[{ label: d.systemClassification, tone: CLASS_TONE[d.systemClassification] ?? "slate" }]}
              rightTop={d.supervisorReviewStatus}
              rightBottom="review status"
            />
          ))}
        </section>
      )}
    </EntityIndex>
  );
}

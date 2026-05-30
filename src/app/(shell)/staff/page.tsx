import { Users } from "lucide-react";
import { EntityIndex, IndexRow } from "@/components/shell/EntityIndex";
import { staffTargetPerformance, type StaffTargetRow } from "@/lib/team-targets-mock";

const PACE_TONE: Record<StaffTargetRow["paceStatus"], "green" | "amber" | "rose"> = {
  "On Track":        "green",
  "Slightly Behind": "amber",
  "Behind":          "amber",
  "High Risk":       "rose",
  "Critical":        "rose",
};

export default function StaffIndex() {
  const staff = staffTargetPerformance;

  return (
    <EntityIndex
      title="Staff Directory"
      subtitle="Everyone with a target — CCEOs, Program Leads, partners. Click a row for the 360° profile."
      Icon={Users}
      count={staff.length}
      searchPlaceholder="Search by name, region, role"
    >
      <section className="card rounded-2xl divide-y divide-[var(--color-edify-divider)] overflow-hidden">
        {staff.map((s) => (
          <IndexRow
            key={s.staffId}
            href={`/staff/${s.staffId}`}
            Icon={Users}
            title={s.staffName}
            subtitle={`${s.role} · ${s.region}`}
            meta={`${s.completedActivities}/${s.monthlyTargetActivities} this month · SF compliance ${s.salesforceCompliancePercent}%`}
            badges={[{ label: s.paceStatus, tone: PACE_TONE[s.paceStatus] }]}
            rightTop={`${s.achievementPercent}%`}
            rightBottom="achievement"
          />
        ))}
      </section>
    </EntityIndex>
  );
}

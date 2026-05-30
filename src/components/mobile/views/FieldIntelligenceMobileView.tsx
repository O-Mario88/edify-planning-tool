"use client";

import { Brain, FileText, AlertTriangle, ListChecks, ArrowUpRight } from "lucide-react";
import {
  MobileSubpageShell,
  MobileKpiGrid,
  MobileSectionCard,
  MobileListRows,
  type MobileKpiTile,
  type ListRow,
  type KpiTone,
} from "@/components/mobile/views/MobileSubpageShell";
import {
  dailyDebriefs,
  fieldIntelligenceSummaryFor,
  detectRepeatedFieldBarriers,
  extractLeadershipDecisions,
  type DebriefClassification,
} from "@/lib/field-intelligence-mock";
import { currentUser } from "@/lib/schools-mock";

const CLASS_TONE: Record<DebriefClassification, KpiTone> = {
  "School Availability Issue":   "amber",
  "Route / Travel Issue":        "amber",
  "Planning Issue":              "violet",
  "Funding Issue":               "rose",
  "Partner Delivery Issue":      "violet",
  "Salesforce / System Issue":   "blue",
  "Evidence / Verification Issue": "blue",
  "Staff Support Needed":        "rose",
  "Protected Field Constraint":  "slate",
  "Accountability Concern":      "rose",
};

export function FieldIntelligenceMobileView() {
  const summary = fieldIntelligenceSummaryFor(currentUser);
  const patterns = detectRepeatedFieldBarriers(dailyDebriefs).slice(0, 5);
  const decisions = extractLeadershipDecisions(patterns).slice(0, 4);

  const tiles: MobileKpiTile[] = [
    { key: "debriefs", Icon: FileText,       label: "Debriefs This Week", value: summary.debriefsThisWeek.toString(), caption: "logged",          tone: "edify"  },
    { key: "raw",      Icon: ArrowUpRight,   label: "Raw Achievement",     value: `${summary.raw}%`,                   caption: "field-side",      tone: "amber"  },
    { key: "adj",      Icon: ArrowUpRight,   label: "Adjusted",            value: `${summary.adjusted}%`,              caption: "context-adjusted", tone: "green"  },
    { key: "barrier",  Icon: AlertTriangle,  label: "Top Barrier",         value: summary.topBarrier ?? "—",          caption: "repeated this week", tone: "rose" },
  ];

  const debriefRows: ListRow[] = dailyDebriefs.slice(0, 6).map((d) => ({
    key: d.id,
    title: `${d.staffName} · ${d.date}`,
    subtitle: d.whatWentWell?.slice(0, 80) ?? "—",
    meta: `Planned ${d.plannedActivities} · Verified ${d.verifiedActivities}`,
    pill: { label: d.systemClassification, tone: CLASS_TONE[d.systemClassification] ?? "slate" },
  }));

  const decisionRows: ListRow[] = decisions.map((d, i) => ({
    key: `${d.decisionArea}-${i}`,
    title: d.issue,
    subtitle: d.recommendedDecision,
    meta: `${d.decisionArea} · owner: ${d.ownerRole}`,
    pill: {
      label: d.urgency,
      tone:
        d.urgency === "Critical" ? "rose"  :
        d.urgency === "High"     ? "rose"  :
        d.urgency === "Medium"   ? "amber" :
                                    "blue" ,
    },
  }));

  return (
    <MobileSubpageShell
      title="Field Intelligence"
      subtitle={`Daily debrief → Weekly decisions · ${summary.debriefsThisWeek} debriefs this week`}
    >
      <MobileKpiGrid tiles={tiles} cols={2} />

      <MobileSectionCard
        title="Recent Debriefs"
        subtitle="Last entries from the field"
        ctaLabel="View All"
        ctaHref="#debriefs"
      >
        <MobileListRows rows={debriefRows} />
      </MobileSectionCard>

      <MobileSectionCard
        title="Leadership Decisions"
        subtitle="Pattern-based actions surfaced this week"
      >
        <MobileListRows rows={decisionRows} />
      </MobileSectionCard>

      <div className="muted text-caption inline-flex items-center gap-1 px-1">
        <Brain size={11} />
        Adjusted achievement filters out external constraints (illness, security, weather).
      </div>
      <div className="muted text-caption inline-flex items-center gap-1 px-1">
        <ListChecks size={11} />
        Repeated barriers ≥3× this week roll up into Leadership Decisions.
      </div>
    </MobileSubpageShell>
  );
}

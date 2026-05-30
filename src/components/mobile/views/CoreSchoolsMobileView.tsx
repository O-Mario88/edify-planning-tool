"use client";

import { Star, Trophy, Activity, AlertOctagon } from "lucide-react";
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
  coreSchools,
  summarizeCore,
  rankBestPerformingCoreSchools,
  detectCoreSchoolsNeedingAttention,
  type CoreSchoolRow,
} from "@/lib/core-schools-mock";

const PACKAGE_TONE: Record<CoreSchoolRow["packageStatus"], KpiTone> = {
  "Not Started":        "slate",
  "Started":            "blue",
  "Halfway Supported":  "blue",
  "Nearly Complete":    "amber",
  "Package Complete":   "green",
  "Behind Schedule":    "rose",
  "Critical Gap":       "rose",
};

export function CoreSchoolsMobileView() {
  const summary  = summarizeCore(coreSchools);
  const best     = rankBestPerformingCoreSchools(coreSchools).slice(0, 5);
  const needAttn = detectCoreSchoolsNeedingAttention(coreSchools).slice(0, 5);

  const tiles: MobileKpiTile[] = [
    { key: "total",     Icon: Star,         label: "Total Core Schools",   value: summary.totalCoreSchools.toString(),         caption: "Active",                tone: "edify"  },
    { key: "complete",  Icon: Trophy,       label: "Package Complete",     value: summary.packageComplete.toString(),          caption: "4V + 4T this year",     tone: "green"  },
    { key: "ssa",       Icon: Activity,     label: "Avg SSA",              value: summary.averageSsa.toFixed(2),               caption: "/ 10",                  tone: "violet" },
    { key: "behind",    Icon: AlertOctagon, label: "Behind / Critical",    value: summary.behindSchedule.toString(),           caption: "needs attention",       tone: "rose"   },
  ];

  const bestRows: ListRow[] = best.map((s) => ({
    key: s.schoolId,
    title: s.schoolName,
    subtitle: `${s.district} · ${s.assignedCceoName}`,
    meta: `Visits ${s.visitsCompleted}/4 · Trainings ${s.trainingsCompleted}/4`,
    rightTop: (s.latestVerifiedSsaAverage ?? 0).toFixed(1),
    rightBottom: "SSA",
    pill: { label: s.packageStatus, tone: PACKAGE_TONE[s.packageStatus] },
  }));

  const attnRows: ListRow[] = needAttn.map((s) => ({
    key: s.schoolId,
    title: s.schoolName,
    subtitle: `${s.district} · ${s.assignedCceoName}`,
    meta: s.recommendedNextAction,
    pill: { label: s.packageStatus, tone: PACKAGE_TONE[s.packageStatus] },
  }));

  return (
    <MobileSubpageShell
      title="Core Schools"
      subtitle={`${summary.totalCoreSchools} schools · ${summary.packageComplete} complete · avg SSA ${summary.averageSsa.toFixed(2)}`}
    >
      <MobileKpiGrid tiles={tiles} cols={2} />

      <MobileSectionCard
        title="Best Performing"
        subtitle="Ranked by SSA + package completion"
        ctaLabel="View All"
        ctaHref="#best"
      >
        <MobileListRows rows={bestRows} />
      </MobileSectionCard>

      <MobileSectionCard
        title="Needs Attention"
        subtitle="Behind, inactive, or below SSA threshold"
        ctaLabel="View All"
        ctaHref="#needs"
      >
        <MobileListRows rows={attnRows} />
      </MobileSectionCard>
    </MobileSubpageShell>
  );
}

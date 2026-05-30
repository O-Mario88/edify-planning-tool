"use client";

import {
  Target,
  Calendar,
  CalendarRange,
  Users,
  AlertTriangle,
  School,
  Cloud,
  type LucideIcon,
} from "lucide-react";
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
  teamTargetKpis,
  attentionItems,
  staffTargetPerformance,
  teamTargetsHeader,
  teamTargetsHeaderUser,
  type PaceStatus,
  type TeamTargetKpi,
  type AttentionItem,
} from "@/lib/team-targets-mock";

const KPI_ICON: Record<TeamTargetKpi["icon"], LucideIcon> = {
  target:        Target,
  calendar:      Calendar,
  calendarRange: CalendarRange,
  users:         Users,
  alertTriangle: AlertTriangle,
  school:        School,
  cloud:         Cloud,
};

const KPI_TONE: Record<TeamTargetKpi["tone"], KpiTone> = {
  emerald: "green",
  edify:   "edify",
  amber:   "amber",
  rose:    "rose",
  violet:  "violet",
};

const ATTN_TONE: Record<AttentionItem["tone"], KpiTone> = {
  amber: "amber",
  rose:  "rose",
  edify: "edify",
  violet:"violet",
  blue:  "blue",
};

const PACE_TONE: Record<PaceStatus, KpiTone> = {
  "On Track":         "green",
  "Slightly Behind":  "amber",
  "Behind":           "amber",
  "High Risk":        "rose",
  "Critical":         "rose",
};

export function TeamTargetsMobileView() {
  const tiles: MobileKpiTile[] = teamTargetKpis.map((k) => ({
    key:    k.key,
    Icon:   KPI_ICON[k.icon],
    label:  k.label,
    value:  k.value,
    caption: k.trend ? k.trend.delta : undefined,
    tone:   KPI_TONE[k.tone],
  }));

  const attnRows: ListRow[] = attentionItems.map((a) => ({
    key: a.key,
    title: a.title,
    subtitle: a.subtitle,
    rightTop: a.value,
    pill: { label: a.cta.replace(/[→]/g, "").trim(), tone: ATTN_TONE[a.tone] },
  }));

  const staffRows: ListRow[] = staffTargetPerformance.slice(0, 8).map((s) => ({
    key: s.staffId,
    title: s.staffName,
    subtitle: `${s.role} · ${s.region}${s.cluster ? ` · ${s.cluster}` : ""}`,
    meta: `${s.completedActivities}/${s.monthlyTargetActivities} this month · ${s.coreSchoolProgressPercent}% core`,
    rightTop: `${s.achievementPercent}%`,
    rightBottom: s.paceStatus,
    pill: { label: s.paceStatus, tone: PACE_TONE[s.paceStatus] },
  }));

  return (
    <MobileSubpageShell
      title="Team Targets"
      subtitle={teamTargetsHeader.subtitle ?? "Achievement, pace, and support reviews"}
      initials={teamTargetsHeaderUser.initials}
    >
      <MobileKpiGrid tiles={tiles.slice(0, 4)} cols={2} />

      <MobileSectionCard title="Needs Attention" subtitle="Where to focus this week">
        <MobileListRows rows={attnRows} />
      </MobileSectionCard>

      <MobileSectionCard
        title="Staff Performance"
        subtitle="Pace status and category progress"
        ctaLabel="View All"
        ctaHref="#staff"
      >
        <MobileListRows rows={staffRows} />
      </MobileSectionCard>
    </MobileSubpageShell>
  );
}

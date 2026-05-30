"use client";

import {
  User,
  CalendarDays,
  CalendarHeart,
  Lock,
  RotateCw,
  Users,
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
  leaveKpis,
  leaveRequests,
  publicHolidays,
  leaveHeader,
  leaveHeaderUser,
  leaveNotificationCount,
  type LeaveStatus,
  type LeaveKpi,
} from "@/lib/leave-mock";

const KPI_ICON: Record<LeaveKpi["icon"], LucideIcon> = {
  user:          User,
  calendarDays:  CalendarDays,
  calendarHeart: CalendarHeart,
  lock:          Lock,
  rotate:        RotateCw,
  users:         Users,
};

const KPI_TONE: Record<LeaveKpi["iconTone"], KpiTone> = {
  edify:   "edify",
  amber:   "amber",
  rose:    "rose",
  slate:   "slate",
  emerald: "green",
  violet:  "violet",
};

const STATUS_TONE: Record<LeaveStatus, KpiTone> = {
  Pending:   "amber",
  Approved:  "green",
  Rejected:  "rose",
  Cancelled: "slate",
};

export function LeaveMobileView() {
  const tiles: MobileKpiTile[] = leaveKpis.map((k) => ({
    key:    k.key,
    Icon:   KPI_ICON[k.icon],
    label:  k.label,
    value:  `${k.value} ${k.unit}`,
    caption: k.caption,
    tone:   KPI_TONE[k.iconTone],
  }));

  const requestRows: ListRow[] = leaveRequests.slice(0, 8).map((lr) => ({
    key: lr.leaveId,
    title: `${lr.staffName} · ${lr.leaveType}`,
    subtitle: `${lr.startDate} → ${lr.endDate} · ${lr.workingDays} days`,
    meta: `${lr.region} region · ${lr.planningImpact} impact`,
    pill: { label: lr.approvalStatus, tone: STATUS_TONE[lr.approvalStatus] },
  }));

  const holidayRows: ListRow[] = publicHolidays.slice(0, 8).map((h) => ({
    key: h.date,
    title: h.title,
    subtitle: h.date,
    pill: { label: "Holiday", tone: "rose" },
  }));

  return (
    <MobileSubpageShell
      title={leaveHeader.title}
      subtitle={leaveHeader.subtitle}
      initials={leaveHeaderUser.initials}
      notificationsCount={leaveNotificationCount}
    >
      <MobileKpiGrid tiles={tiles} cols={2} />

      <MobileSectionCard
        title="Leave Requests"
        subtitle="Most recent submissions"
        ctaLabel="View All"
        ctaHref="#requests"
      >
        <MobileListRows rows={requestRows} />
      </MobileSectionCard>

      <MobileSectionCard title="Public Holidays" subtitle="Auto-blocked planning days">
        <MobileListRows rows={holidayRows} />
      </MobileSectionCard>
    </MobileSubpageShell>
  );
}

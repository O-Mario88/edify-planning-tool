import Link from "next/link";
import { redirect } from "next/navigation";
import {
  AlertTriangle,
  ArrowRight,
  ChevronRight,
  ClipboardList,
  Inbox,
  ShieldAlert,
  Telescope,
  Users,
  type LucideIcon,
} from "lucide-react";
import { AggregatedFieldContextCard } from "@/components/field-intelligence/AggregatedFieldContextCard";
import { CommandStack } from "@/components/actions/CommandStack";
import { DashboardPageHeader } from "@/components/dashboards/DashboardPageHeader";
import { DashboardGreetingHero } from "@/components/dashboards/DashboardGreetingHero";
import { DecisionEngineEmbed } from "@/components/leadership/DecisionEngineEmbed";
import { DebriefReviewInbox } from "@/components/messages/DebriefReviewInbox";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { SectionHeader } from "@/components/ui/SectionHeader";
import { HrKpiStrip } from "@/components/hr/HrKpiStrip";
import { HrRosterLive } from "@/components/hr/HrRosterLive";
import { HrMobileView } from "@/components/mobile/views/HrMobileView";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { hrAggregatedFieldContext } from "@/lib/field-intelligence-mock";

// HR — People & Performance dashboard.
//
// HR works with RVP (escalation) and supports staff performance reviews.
// They do NOT see raw daily debriefs or named CCEOs by default. The page
// renders aggregated intelligence so HR can spot patterns (overload,
// route difficulty, repeated support requests) without invading staff
// trust.
//
// Reading order (top → bottom):
//   1. Hero chrome      — search · message · bell · avatar · greeting
//   2. CommandStack     — mission, next 3 actions, change digest
//   3. HR Attention     — 3 alert banners (decisions / flagged / reviews)
//   4. 4 KPI tiles      — clickable, each routes to its working queue
//   5. Best Performers  — team recognition (no individual CCEO ranking)
//   6. Field context    — aggregated barriers + support themes
//   7. Quick Actions    — 3 shortcut tiles to working queues

const ALLOWED = new Set(["HumanResource", "Admin"]);

export default async function HrFieldContextPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect(ROLE_REDIRECT[user.role]);

  const ctx = hrAggregatedFieldContext();

  const desktop = (
    <>
      <DashboardPageHeader role="HumanResource" />
      <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6 pt-3 md:pt-4 space-y-4 md:space-y-5">
        {/* GREETING HERO — system-wide layout rule: header → hero →
            stats → work. */}
        <DashboardGreetingHero user={user} />

        {/* Leadership Decision Engine — context-fair staff/HR + staffing advisory. */}
        <DecisionEngineEmbed board="staff_hr" heading="Staff & HR Decisions" />

        {/* STATISTICS FIRST — the KPI snapshot is the first thing under the
            hero so the numbers are seen before the attention queues. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="People snapshot"
            title="Your team at a glance"
            description="Headcount, active staff, leave, and the working-queue counts — the figures first."
          />
          <HrKpiStrip />
        </section>

        {/* ATTENTION — decisions and flags this week, below the figures. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Attention"
            title="HR decisions and flags this week"
            description="Escalations routed from CD/RVP, staff flagged for support, and performance reviews due."
          />
          <HrAttentionRow />
        </section>

        {/* TODAY — the work stack. */}
        <CommandStack user={user} hideMission />

        {/* PEOPLE — routed debriefs + recognition. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="People"
            title="Performance signals and recognition"
            description="Debriefs the routing engine flagged for HR, plus the period's top performers across program leads and CCEOs."
          />
          <DebriefReviewInbox user={user} audience="hr" />
          {/* Live, backend-driven staff roster. */}
          <HrRosterLive />
        </section>

        {/* FIELD — aggregated intelligence. */}
        <section className="space-y-3">
          <SectionHeader
            tier="strategic"
            eyebrow="Field"
            title="What's coming back from the field"
            description="Aggregated barriers, support themes, and team-health signals — no individual staff names, by design."
          />
          <AggregatedFieldContextCard
            ctx={ctx}
            title="Country field intelligence (HR view)"
            subtitle="Aggregated barriers · support themes · team health · open decisions in the leadership pipeline."
          />
        </section>

        {/* Closing utility row — three shortcut cards. */}
        <section className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {QUICK_ACTIONS.map((a) => (
            <Link
              key={a.title}
              href={a.href}
              className="card p-3.5 flex items-center gap-3 hover:bg-[var(--color-edify-soft)]/40 transition-colors"
            >
              <span className="h-9 w-9 rounded-md bg-[var(--color-edify-soft)]/80 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
                <a.Icon size={16} />
              </span>
              <div className="flex-1 min-w-0">
                <div className="text-[13px] font-extrabold tracking-tight truncate">{a.title}</div>
                <div className="text-[11.5px] muted truncate">{a.subtitle}</div>
              </div>
              <ChevronRight size={14} className="text-[var(--color-edify-muted)] shrink-0" />
            </Link>
          ))}
        </section>
      </div>
    </>
  );

  const mobile = (
    <>
      <DashboardPageHeader role="HumanResource" />
      <HrMobileView ctx={ctx} />
    </>
  );

  return <ResponsiveDashboard mobile={mobile} desktop={desktop} />;
}

// ─────────────────────── HR Attention Row ────────────────────────
//
// Three alert banners that surface the decisions and flags HR must
// resolve THIS WEEK. Each links to the matching queue so the alert is
// the entry point, not just a metric.

type HrAlert = {
  href:  string;
  tone:  "rose" | "amber" | "blue";
  title: string;
  body:  string;
  cta:   string;
  Icon:  LucideIcon;
};

const HR_ALERTS: HrAlert[] = [
  {
    href:  "/team-targets?view=hr-decisions",
    tone:  "rose",
    title: "3 HR decisions awaiting your call",
    body:  "Escalations routed from CD / RVP — review the case and resolve.",
    cta:   "Open decisions",
    Icon:  Inbox,
  },
  {
    href:  "/team-targets?view=support",
    tone:  "amber",
    title: "4 staff flagged for support",
    body:  "Workload, route difficulty, repeated requests — review with each Program Lead.",
    cta:   "Review staff",
    Icon:  ShieldAlert,
  },
  {
    href:  "/team-targets?view=reviews-due",
    tone:  "blue",
    title: "6 performance reviews due this month",
    body:  "Across 5 program leads — schedule a window with each PL.",
    cta:   "Open review queue",
    Icon:  ClipboardList,
  },
];

const ALERT_FRAME: Record<HrAlert["tone"], string> = {
  rose:  "bg-rose-50 border-rose-200 dark:bg-rose-500/[0.10] dark:border-rose-500/30",
  amber: "bg-amber-50 border-amber-200 dark:bg-amber-500/[0.10] dark:border-amber-500/30",
  blue:  "bg-blue-50 border-blue-200 dark:bg-blue-500/[0.10] dark:border-blue-500/30",
};
const ALERT_ICON: Record<HrAlert["tone"], string> = {
  rose:  "bg-rose-100 text-rose-700 dark:bg-rose-500/20 dark:text-rose-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-300",
  blue:  "bg-blue-100 text-blue-800 dark:bg-blue-500/20 dark:text-blue-300",
};
const ALERT_TITLE: Record<HrAlert["tone"], string> = {
  rose:  "text-rose-900 dark:text-rose-100",
  amber: "text-amber-900 dark:text-amber-100",
  blue:  "text-blue-900 dark:text-blue-100",
};

function HrAttentionRow() {
  return (
    <section className="card p-2.5">
      <div className="flex items-center gap-2 mb-2 pl-0.5">
        <span className="w-5 h-5 rounded-md bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center shrink-0">
          <AlertTriangle size={11} />
        </span>
        <h3 className="text-body font-bold">HR Attention</h3>
        <Link href="/team-targets" className="ml-auto text-[11.5px] font-semibold text-[var(--color-edify-primary)]">
          View All queues →
        </Link>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
        {HR_ALERTS.map((a) => (
          <Link
            key={a.title}
            href={a.href}
            className={`rounded-lg border px-2.5 py-2 flex items-start gap-2.5 overflow-hidden hover:brightness-[0.98] transition-[filter] ${ALERT_FRAME[a.tone]}`}
          >
            <span className={`w-7 h-7 rounded-md grid place-items-center mt-0.5 shrink-0 ${ALERT_ICON[a.tone]}`}>
              <a.Icon size={13} />
            </span>
            <div className="flex-1 min-w-0">
              <div className={`text-[12px] font-bold leading-tight line-clamp-1 ${ALERT_TITLE[a.tone]}`}>{a.title}</div>
              <div className="text-[11px] muted mt-0.5 line-clamp-2">{a.body}</div>
              <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--color-edify-primary)] mt-1">
                {a.cta}
                <ArrowRight size={10} />
              </span>
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

// ───────────────────────── Quick Actions ─────────────────────────

const QUICK_ACTIONS = [
  { href: "/team-targets",       title: "Open performance review queue", subtitle: "Reviews routed by Program Leads",  Icon: Users        },
  { href: "/team-targets",       title: "Review staff support signals",  subtitle: "Flagged staff & support requests", Icon: ShieldAlert  },
  { href: "/field-intelligence", title: "Aggregated field intelligence", subtitle: "Country-level patterns & themes",  Icon: Telescope    },
];

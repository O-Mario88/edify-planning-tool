// /partner/schedule — Schedule.
//
// The partner's "what do I need to schedule next" page. Reading
// order is deliberate:
//   1. Unscheduled assignments — every assignment from staff that
//      doesn't yet have a delivery week. Schedule from here.
//   2. 4-week delivery plan — what's already scheduled across the
//      month with capacity meters per week.
//
// Once an assignment is scheduled it leaves this page and shows up
// on /partner/assignments (My Plan).

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { isPlanStarted } from "@/lib/scheduled-plan/started-overlay";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerUnscheduledList } from "@/components/partner/PartnerUnscheduledList";
import { PartnerPlanningBoard } from "@/components/partner/PartnerPlanningBoard";
import { ScheduledPlanCard } from "@/components/scheduled-plan/ScheduledPlanCard";
import { submitRescheduleAction, startActivityAction } from "./actions";
import type { ScheduledPlan } from "@/lib/scheduled-plan/types";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerSchedulePage({
  searchParams,
}: {
  searchParams: Promise<{ preview?: string }>;
}) {
  const user = await getCurrentUser();
  const params = await searchParams;
  const previewMode = process.env.NODE_ENV !== "production" && params.preview === "1";
  if (!previewMode && !ALLOWED.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  return (
    <>
      <PartnerSubPageHeader
        title="Schedule"
        subtitle="Assignments from your Edify CCEO that need a delivery week. Once you schedule one, it moves to My Plan and shows up on your CCEO's monitoring dashboard."
        filters={[
          { iconKey: "calendar", label: "May 2026" },
          { iconKey: "filter",   label: "All facilitators" },
        ]}
        kpis={[
          { label: "Unscheduled",       value: 8,     iconKey: "alert",     tone: "danger",  caption: "Need a delivery week"    },
          { label: "Scheduled · 4 wks", value: 11,    iconKey: "cal-range", tone: "good",    caption: "Across the month"        },
          { label: "Facilitators",      value: 5,     iconKey: "users",     tone: "neutral", caption: "Active on team"          },
          { label: "Capacity used",     value: "62%", iconKey: "calendar",  tone: "good",    caption: "Of weekly visit ceiling" },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        {/* Scheduled plan demo — every scheduled activity surfaces
            two actions: Reschedule (opens the required-reason drawer
            with the routing preview) and Start Activity (opens the
            confirmation drawer + transitions status to In Progress).
            On mobile, Start fills the row and Reschedule wraps below. */}
        {DEMO_PLANS.map((demo) => {
          // Apply the started-plan overlay so a started activity stays
          // In Progress across reloads (its Start button is then retired).
          const plan = isPlanStarted(demo.id) ? { ...demo, status: "in_progress" as const } : demo;
          return (
            <ScheduledPlanCard
              key={plan.id}
              plan={plan}
              rescheduleAction={submitRescheduleAction}
              startAction={startActivityAction}
            />
          );
        })}

        {/* 1. Full list of unscheduled assignments — the partner's
            primary action on this page. */}
        <PartnerUnscheduledList />

        {/* 2. 4-week delivery plan — what's already scheduled.
            (PartnerPlanningBoard's old 3-card "Needs scheduling"
            strip is now superseded by the list above, but the
            week-board below stays useful for capacity context.) */}
        <PartnerPlanningBoard />
      </div>
    </>
  );
}

// Three demo scheduled plans across the lifecycle so the page shows
// the button-visibility rules end-to-end (scheduled + due_today +
// in_progress). Phase 4 reads these from the assignments store.
const DEMO_PLANS: ScheduledPlan[] = [
  {
    id:               "pa:maple-coaching",
    activityType:     "follow_up_visit",
    label:            "Literacy follow-up visit",
    schoolName:       "Maple Grove Primary",
    district:         "Kayunga",
    scheduledFor:     "Tue 19 May · Week 21",
    purpose:          "Teaching & Learning support — SSA score 4/10",
    ownerLabel:       "Partner: Abel Opio",
    evidenceRequired: ["Visit report", "Staff met", "Next action notes"],
    costLabel:        "UGX 40,000 · projected payment",
    status:           "due_today",
    actor:            "partner",
  },
  {
    id:               "pa:kireka-training",
    activityType:     "in_school_training",
    label:            "In-School literacy training",
    schoolName:       "Kireka Primary School",
    district:         "Mukono",
    scheduledFor:     "Thu 12 Jun · Week 24",
    purpose:          "P4 teacher capacity — SSA Teaching & Learning gap",
    ownerLabel:       "Partner: Sarah Kanyi",
    evidenceRequired: ["Attendance sheet (signed)", "Training photos", "Debrief notes"],
    costLabel:        "UGX 120,000 · projected payment",
    status:           "scheduled",
    actor:            "partner",
  },
  {
    id:               "pa:eden-followup",
    activityType:     "coaching_visit",
    label:            "Math coaching follow-up",
    schoolName:       "Eden Foundation School",
    district:         "Mukono",
    scheduledFor:     "Mon 11 May · Week 20",
    purpose:          "P5 math practice — review of June plan",
    ownerLabel:       "Partner: Abel Opio",
    evidenceRequired: ["Coaching report", "Teacher reflection"],
    costLabel:        "UGX 40,000 · projected payment",
    status:           "in_progress",
    actor:            "partner",
  },
];

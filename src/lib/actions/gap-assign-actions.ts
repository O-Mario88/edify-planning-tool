"use server";

// Record an assignment made from a planning gap board. When the backend is on,
// also creates a real Activity (with auto-cost lines) so the handoff lands in
// My Plan / partner queue — not just an in-memory overlay.

import { revalidatePath } from "next/cache";
import { getCurrentUser } from "@/lib/auth";
import { isBackendEnabled } from "@/lib/api/backend";
import { isMockAllowed } from "@/lib/mock-policy";
import {
  backendAssignSchoolVisitToPartner,
  backendScheduleSchoolVisit,
} from "@/lib/api/surfaces";
import { recordGapAssignment, type GapAssignmentOwner } from "@/lib/planning/assignment-overlay";
import { emitAudit, emitNotification } from "./audit";

export type AssignGapInput = {
  /** Business schoolId from the gap board — used for backend Activity create. */
  schoolId?: string;
  gapId?: string;
  title: string;
  schoolOrCluster: string;
  owner: GapAssignmentOwner;
  ownerName?: string;
  monthLabel?: string;
  week?: number;
  notes?: string;
  /** Real partner id when assigning to a partner in live mode. */
  partnerId?: string;
};

export type AssignGapResult =
  | { ok: true; id: string }
  | { ok: false; reason: "FORBIDDEN" | "INVALID_INPUT" | "BACKEND_ERROR"; message?: string };

const ASSIGN_ROLES = new Set(["CCEO", "CountryProgramLead", "Admin"]);

const MONTH_NUM: Record<string, number> = {
  Jan: 1, Feb: 2, Mar: 3, Apr: 4, May: 5, Jun: 6,
  Jul: 7, Aug: 8, Sep: 9, Oct: 10, Nov: 11, Dec: 12,
};

function parseMonthLabel(label?: string): number | undefined {
  if (!label) return undefined;
  const m = label.trim().match(/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b/);
  return m ? MONTH_NUM[m[1]] : undefined;
}

function fyQuarter(iso?: string): { fy: string; quarter: string } {
  const d = iso ? new Date(iso) : new Date();
  const y = d.getUTCFullYear();
  const m = d.getUTCMonth();
  const fy = String(m >= 9 ? y + 1 : y);
  const quarter = m >= 9 ? "Q1" : m <= 2 ? "Q2" : m <= 5 ? "Q3" : "Q4";
  return { fy, quarter };
}

export async function assignGapActivity(input: AssignGapInput): Promise<AssignGapResult> {
  const user = await getCurrentUser();
  if (!ASSIGN_ROLES.has(user.role)) return { ok: false, reason: "FORBIDDEN" };
  if (!input.title?.trim() || !input.owner) return { ok: false, reason: "INVALID_INPUT" };

  const schoolId = input.schoolId ?? input.gapId;
  const ownerName = input.ownerName?.trim() || (input.owner === "myself" ? user.name : undefined);
  const { fy, quarter } = fyQuarter();
  const plannedMonth = parseMonthLabel(input.monthLabel);

  let activityId: string | undefined;

  if (isBackendEnabled() && schoolId) {
    if (input.owner === "myself") {
      const r = await backendScheduleSchoolVisit(user, {
        schoolId,
        fy,
        quarter,
        ...(plannedMonth ? { plannedMonth } : {}),
        ...(input.week ? { plannedWeek: input.week } : {}),
      });
      if (r.live) activityId = r.data.id;
      else if (!isMockAllowed()) {
        return { ok: false, reason: "BACKEND_ERROR", message: r.error ?? "Could not schedule activity." };
      }
    } else if (input.owner === "partner" && input.partnerId) {
      const r = await backendAssignSchoolVisitToPartner(user, {
        schoolId,
        fy,
        quarter,
        assignedPartnerId: input.partnerId,
        ...(plannedMonth ? { plannedMonth } : {}),
        ...(input.week ? { plannedWeek: input.week } : {}),
      });
      if (r.live) activityId = r.data.id;
      else if (!isMockAllowed()) {
        return { ok: false, reason: "BACKEND_ERROR", message: r.error ?? "Could not assign to partner." };
      }
    }
  }

  const rec = recordGapAssignment({
    gapId: input.gapId ?? schoolId,
    title: input.title.trim(),
    schoolOrCluster: input.schoolOrCluster,
    owner: input.owner,
    ownerName,
    monthLabel: input.monthLabel,
    week: input.week,
    notes: input.notes?.trim() || undefined,
    assignedById: user.staffId,
    assignedByName: user.name,
  });

  emitAudit({
    action: "planning.activityAssigned",
    subjectKind: activityId ? "Activity" : "PlanActivityAssignment",
    subjectId: activityId ?? rec.id,
    actorId: user.staffId,
    actorRole: user.role,
    actorName: user.name,
    payload: {
      title: rec.title, school: rec.schoolOrCluster, owner: rec.owner, ownerName,
      month: rec.monthLabel, week: rec.week, backendActivityId: activityId ?? null,
    },
  });

  const when = rec.monthLabel ? `${rec.monthLabel}${rec.week ? ` · Wk ${rec.week}` : ""}` : "this cycle";
  if (input.owner === "partner" || input.owner === "partner_facilitator") {
    emitNotification({
      userId: "PARTNER",
      template: "planning.activityAssigned",
      channel: "Inbox",
      title: `New assignment: ${rec.title}`,
      body: `${user.name} assigned "${rec.title}" (${rec.schoolOrCluster}) to ${ownerName ?? "your team"} for ${when}.`,
      href: "/partner/assignments",
    });
  } else {
    emitNotification({
      userId: input.owner === "myself" ? user.staffId : "STAFF",
      template: "planning.activityAssigned",
      channel: "Inbox",
      title: `Assigned: ${rec.title}`,
      body: `"${rec.title}" (${rec.schoolOrCluster}) is on the plan for ${when}.`,
      href: "/my-plan",
    });
  }

  try {
    revalidatePath("/planning");
    revalidatePath("/my-plan");
    revalidatePath("/partner/assignments");
    revalidatePath("/partner/today");
    revalidatePath("/notifications");
    revalidatePath("/budget");
    revalidatePath("/weekly-funds");
  } catch {
    /* outside request scope */
  }

  return { ok: true, id: activityId ?? rec.id };
}

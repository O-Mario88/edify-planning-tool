import { describe, expect, it } from "vitest";
import {
  buildFundingByActivity,
  fromBeActivity,
  fromStoreActivity,
  sectionMyPlan,
  weekMonthLabel,
  type MyPlanItem,
} from "@/lib/planning/my-plan-sections";
import type { BeActivity } from "@/lib/api/surfaces";
import type { PlannedActivityRecord } from "@/lib/actions/store";
import type { WeeklyFundRequest } from "@/lib/funds/weekly-fund-types";

// Wed 2026-06-10 — week runs Mon 08 … Sun 14, month June.
const TODAY = new Date("2026-06-10T08:00:00Z");
const TODAY_ISO = "2026-06-10";

function storeAct(over: Partial<PlannedActivityRecord>): PlannedActivityRecord {
  return {
    id: "ACT-1", planId: "P-1", kind: "SCHOOL_VISIT", title: "School visit — Test",
    weekOfMonth: 2, assigneeId: "STF-1", estCostCents: 4_500_000, status: "Planned",
    createdAt: "2026-06-01", updatedAt: "2026-06-01",
    ...over,
  } as PlannedActivityRecord;
}

function beAct(over: Partial<BeActivity>): BeActivity {
  return {
    id: "BE-1", activityType: "school_visit", status: "planned", deliveryType: "staff",
    school: { schoolId: "S-1", name: "Test Primary" },
    ...over,
  } as BeActivity;
}

const NO_FUNDING = new Map<string, never>();

describe("section derivation", () => {
  function bucketOf(item: MyPlanItem | null): string | undefined {
    const sections = sectionMyPlan(item ? [item] : [], TODAY);
    return sections.find((s) => s.items.length > 0)?.key;
  }

  it("buckets by scheduled date: today / overdue → dueToday", () => {
    expect(bucketOf(fromStoreActivity(storeAct({ scheduledDate: "2026-06-10" }), NO_FUNDING, TODAY_ISO))).toBe("dueToday");
    expect(bucketOf(fromStoreActivity(storeAct({ scheduledDate: "2026-06-02" }), NO_FUNDING, TODAY_ISO))).toBe("dueToday");
  });

  it("rest of the current week → thisWeek; later or undated → thisMonth", () => {
    expect(bucketOf(fromStoreActivity(storeAct({ scheduledDate: "2026-06-13" }), NO_FUNDING, TODAY_ISO))).toBe("thisWeek");
    expect(bucketOf(fromStoreActivity(storeAct({ scheduledDate: "2026-06-25" }), NO_FUNDING, TODAY_ISO))).toBe("thisMonth");
    expect(bucketOf(fromStoreActivity(storeAct({ scheduledDate: undefined }), NO_FUNDING, TODAY_ISO))).toBe("thisMonth");
  });

  it("blocked-on-me statuses win over dates", () => {
    expect(bucketOf(fromStoreActivity(storeAct({ status: "SalesforceIdPending", scheduledDate: "2026-06-10" }), NO_FUNDING, TODAY_ISO))).toBe("waitingOnMe");
    expect(bucketOf(fromStoreActivity(storeAct({ status: "Returned", scheduledDate: "2026-06-13" }), NO_FUNDING, TODAY_ISO))).toBe("waitingOnMe");
    expect(bucketOf(fromBeActivity(beAct({ status: "salesforce_id_required" }), TODAY_ISO))).toBe("waitingOnMe");
    expect(bucketOf(fromBeActivity(beAct({ evidenceStatus: "missing", scheduledDate: "2026-06-10" }), TODAY_ISO))).toBe("waitingOnMe");
  });

  it("rescheduled and deferred items land in needsAttention", () => {
    expect(bucketOf(fromStoreActivity(storeAct({ rescheduleCount: 1, scheduledDate: "2026-06-10" }), NO_FUNDING, TODAY_ISO))).toBe("needsAttention");
    expect(bucketOf(fromStoreActivity(storeAct({ status: "Deferred" }), NO_FUNDING, TODAY_ISO))).toBe("needsAttention");
    expect(bucketOf(fromBeActivity(beAct({ status: "rescheduled" }), TODAY_ISO))).toBe("needsAttention");
  });

  it("slip-limit breaches sort first within needsAttention", () => {
    const a = fromStoreActivity(storeAct({ id: "A", rescheduleCount: 1, scheduledDate: "2026-06-11" }), NO_FUNDING, TODAY_ISO)!;
    const b = fromStoreActivity(storeAct({ id: "B", rescheduleCount: 3, scheduledDate: "2026-06-20" }), NO_FUNDING, TODAY_ISO)!;
    const section = sectionMyPlan([a, b], TODAY).find((s) => s.key === "needsAttention")!;
    expect(section.items.map((i) => i.id)).toEqual(["B", "A"]);
    expect(b.atSlipLimit).toBe(true);
  });

  it("completed/closed work never renders (it lives in /completed-activities)", () => {
    for (const status of ["Completed", "SubmittedForVerification", "Verified", "AccountabilityClosed", "Cancelled"] as const) {
      expect(fromStoreActivity(storeAct({ status }), NO_FUNDING, TODAY_ISO)).toBeNull();
    }
    for (const status of ["completed", "awaiting_ia_verification", "ia_verified", "evidence_accepted", "accountant_confirmed", "cancelled"]) {
      expect(fromBeActivity(beAct({ status }), TODAY_ISO)).toBeNull();
    }
  });

  it("always returns the five sections, even when empty", () => {
    const sections = sectionMyPlan([], TODAY);
    expect(sections.map((s) => s.key)).toEqual(["dueToday", "thisWeek", "thisMonth", "waitingOnMe", "needsAttention"]);
    expect(sections.every((s) => s.emptyCopy.length > 0)).toBe(true);
  });
});

describe("next-action resolution (the ONE button)", () => {
  it("salesforce-id-blocked → enterSalesforceId; evidence-blocked → uploadEvidence; returned → complete", () => {
    expect(fromStoreActivity(storeAct({ status: "SalesforceIdPending" }), NO_FUNDING, TODAY_ISO)!.nextAction).toBe("enterSalesforceId");
    expect(fromBeActivity(beAct({ evidenceStatus: "rejected" }), TODAY_ISO)!.nextAction).toBe("uploadEvidence");
    expect(fromStoreActivity(storeAct({ status: "Returned" }), NO_FUNDING, TODAY_ISO)!.nextAction).toBe("complete");
  });

  it("due/overdue → complete; future-dated → reschedule; at slip limit → complete", () => {
    expect(fromStoreActivity(storeAct({ scheduledDate: "2026-06-10" }), NO_FUNDING, TODAY_ISO)!.nextAction).toBe("complete");
    expect(fromStoreActivity(storeAct({ scheduledDate: "2026-06-25" }), NO_FUNDING, TODAY_ISO)!.nextAction).toBe("reschedule");
    expect(fromStoreActivity(storeAct({ scheduledDate: "2026-06-25", rescheduleCount: 3 }), NO_FUNDING, TODAY_ISO)!.nextAction).toBe("complete");
  });

  it("deferred (under the limit) → reschedule revives it", () => {
    expect(fromStoreActivity(storeAct({ status: "Deferred", scheduledDate: "2026-06-01" }), NO_FUNDING, TODAY_ISO)!.nextAction).toBe("reschedule");
  });
});

describe("date granularity + funding", () => {
  it("trainings/cluster meetings are date-exact; visits show week-of-month", () => {
    expect(fromStoreActivity(storeAct({ kind: "CLUSTER_TRAINING" }), NO_FUNDING, TODAY_ISO)!.exactDate).toBe(true);
    expect(fromBeActivity(beAct({ activityType: "cluster_meeting" }), TODAY_ISO)!.exactDate).toBe(true);
    const visit = fromStoreActivity(storeAct({ kind: "SCHOOL_VISIT", scheduledDate: "2026-06-25" }), NO_FUNDING, TODAY_ISO)!;
    expect(visit.exactDate).toBe(false);
    expect(weekMonthLabel(visit)).toBe("Week 4 · June");
  });

  it("derives requested/approved/disbursed from the weekly-fund pipeline", () => {
    const wfr = (status: WeeklyFundRequest["status"], lineId: string) =>
      ({ status, activities: [{ id: lineId, originPlanLineId: lineId, status: "Planned" }] }) as unknown as WeeklyFundRequest;
    const map = buildFundingByActivity([
      wfr("SUBMITTED", "ACT-REQ"), wfr("READY_TO_DISBURSE", "ACT-APPR"), wfr("IN_USE", "ACT-DISB"), wfr("CANCELLED", "ACT-NONE"),
    ]);
    expect(map.get("ACT-REQ")).toBe("Requested");
    expect(map.get("ACT-APPR")).toBe("Approved");
    expect(map.get("ACT-DISB")).toBe("Disbursed");
    expect(map.get("ACT-NONE")).toBeUndefined();
    expect(fromStoreActivity(storeAct({ id: "ACT-DISB" }), map, TODAY_ISO)!.funding).toBe("Disbursed");
  });

  it("maps backend paymentStatus loosely", () => {
    expect(fromBeActivity(beAct({ paymentStatus: "paid" }), TODAY_ISO)!.funding).toBe("Disbursed");
    expect(fromBeActivity(beAct({ paymentStatus: "pending" }), TODAY_ISO)!.funding).toBe("Requested");
    expect(fromBeActivity(beAct({}), TODAY_ISO)!.funding).toBeUndefined();
  });
});

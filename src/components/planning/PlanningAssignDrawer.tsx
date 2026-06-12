"use client";

// PlanningAssignDrawer — choose who owns a planning action.
//
// Drives the whole "where does this go next?" decision:
//   • Myself          → Activity moves to My Planning Queue (Today / My Plan).
//                       This path opens a second step inside the same drawer
//                       to pick a month + week before submission.
//   • Another staff   → Lands on that staff's planning queue.
//   • Partner (owns)  → Goes to /partner/schedule. Partner places it in a delivery
//                       week, then it returns to the CCEO monitoring dashboard.
//   • Partner (facilitator)
//                     → For training only. Staff still owns the activity;
//                       partner is just the facilitator and confirms availability.
//
// Returns an `AssignOutcome` so the caller can update local state +
// show the right success toast.
//
// Chrome: uses the canonical Modal primitive (variant="sheet", size="md")
// for the same compact, centered look as the reschedule modals — bottom
// sheet on mobile, centered card on md+. Focus trap, ESC-to-close,
// overlay click, body scroll lock, and portal rendering all come from
// the primitive; this component only owns the form state.

import { useState, useTransition } from "react";
import {
  User as UserIcon, Users, Handshake, ArrowRight, CheckCircle2,
  ChevronLeft, Calendar,
} from "lucide-react";
import { Modal } from "@/components/ui/Modal";
import { Button } from "@/components/ui/Button";
import { useDemoStore } from "@/components/demo/DemoStore";
import { assignGapActivity } from "@/lib/actions/gap-assign-actions";
import { cn } from "@/lib/utils";

export type AssignOwner = "myself" | "staff" | "partner" | "partner_facilitator";

export type AssignOutcome = {
  owner: AssignOwner;
  staffName?: string;
  partnerName?: string;
  facilitatorName?: string;
  notes?: string;
  /** When owner === "myself", the planner picks a month from the active cycle. */
  month?: string;        // human label, e.g. "May 2026"
  /** When owner === "myself", the planner picks a week within the month. */
  week?: 1 | 2 | 3 | 4 | 5;
};

export type PlanningAssignContext = {
  title: string;             // "Schedule School Improvement Training"
  schoolOrCluster: string;   // "Hope Primary School" or "Bbaale Cluster"
  purpose: string;           // generated purpose text
  /** Stable id of the gap-board item being resolved, when known. Persisted
   *  with the assignment so server-owned gap lists can drop it on reload. */
  gapId?: string;
  /// Training assignments allow Partner-as-facilitator; visits don't.
  /// Set true for training/cluster meetings so the facilitator option
  /// renders.
  allowPartnerFacilitator?: boolean;
  /// "Visit" workflows allow partner ownership; "SSA scheduling"
  /// doesn't. Default true.
  allowPartnerOwnership?: boolean;
  /**
   * Role of the person assigning. Controls which owner options the
   * drawer surfaces:
   *
   *   CCEO                        → only "Partner"
   *   PL / IA / CD / Admin        → Myself / Staff / Partner / Facilitator
   *   anyone else                 → Myself / Staff fallback
   *
   * Encodes the Section 1 permission contract from the operating
   * model: CCEO does not own activities directly through this
   * workflow — they assign to a partner. PL / IA / CD have the full
   * range.
   */
  assigningUserRole?: AssigningRole;
};

/** Roles the assignment drawer recognises for permission gating. */
export type AssigningRole = "CCEO" | "CountryProgramLead" | "ImpactAssessment" | "CountryDirector" | "Admin" | "Partner" | "Other";

/** Returns the AssignOwner values a given role is allowed to pick. */
function availableOwnersFor(role: AssigningRole | undefined, allowPartner: boolean, allowFacilitator: boolean): AssignOwner[] {
  if (role === "CCEO") {
    // CCEO assigns only to partners per the operating model. Scheduling for
    // themselves is the separate [Schedule] action (= self-assign); this
    // assign drawer is partner-only.
    return allowPartner ? ["partner"] : [];
  }
  if (role === "CountryProgramLead") {
    // PL assigns to a supervised CCEO (the "staff" option) OR a partner —
    // never to themselves and not as a facilitator.
    return allowPartner ? ["staff", "partner"] : ["staff"];
  }
  if (role === "ImpactAssessment" || role === "CountryDirector" || role === "Admin") {
    const opts: AssignOwner[] = ["myself", "staff"];
    if (allowPartner) opts.push("partner");
    if (allowFacilitator) opts.push("partner_facilitator");
    return opts;
  }
  // Fallback for any other role hitting this surface — most options off.
  return ["myself", "staff"];
}

const STAFF_POOL = [
  "Paul Chinyama (CCEO)",
  "Aisha Dar (CCEO)",
  "Daniel Mwangi (PL)",
];

const PARTNER_POOL = [
  "Bright Future Education Partners",
  "Literacy Training Uganda",
  "Numeracy First",
];

// ────────── Operational-cycle months ──────────
//
// The cycle runs Oct → Sep. Months are listed in cycle order so the
// dropdown reads the way a planner thinks ("we're in Nov, then Dec,
// then Jan…"). Weeks per month derived from the actual calendar —
// February is the only month with 4 weeks; every other month has 5.
//
// Production swaps this for `activeFinancialYear()`-derived values so
// the dropdown stays correct after each Oct-1 cycle reset.

type CycleMonth = { value: string; label: string; weeks: 4 | 5 };

function buildCycleMonths(): CycleMonth[] {
  // FY 2025/26 = Oct 2025 → Sep 2026.
  const startYear = 2025;
  const startMonth = 9; // 0-indexed October
  const out: CycleMonth[] = [];
  for (let i = 0; i < 12; i++) {
    const m = (startMonth + i) % 12;
    const y = startYear + Math.floor((startMonth + i) / 12);
    const daysInMonth = new Date(y, m + 1, 0).getDate();
    const weeks = (Math.ceil(daysInMonth / 7) >= 5 ? 5 : 4) as 4 | 5;
    out.push({
      value: `${y}-${String(m + 1).padStart(2, "0")}`,
      label: new Date(y, m, 1).toLocaleString("en-US", { month: "short", year: "numeric" }),
      weeks,
    });
  }
  return out;
}

const CYCLE_MONTHS = buildCycleMonths();

function defaultMonthValue(): string {
  // ENGINE_TODAY anchors to Nov 15, 2025 in the demo.
  return "2025-11";
}

export function PlanningAssignDrawer({
  open,
  context,
  onClose,
  onSubmit,
}: {
  open: boolean;
  context: PlanningAssignContext | null;
  onClose: () => void;
  onSubmit: (outcome: AssignOutcome) => void;
}) {
  type Step = "owner" | "schedule";

  const availableOwners = availableOwnersFor(
    context?.assigningUserRole,
    context?.allowPartnerOwnership !== false,
    context?.allowPartnerFacilitator === true,
  );

  const [step, setStep] = useState<Step>("owner");
  // Seed the default owner to the first one the role is allowed to
  // pick. For CCEO this means defaulting to "partner" — there are no
  // other options to fall back on.
  const [owner, setOwner] = useState<AssignOwner>(availableOwners[0] ?? "myself");
  const [staffName, setStaffName] = useState<string>(STAFF_POOL[0]);
  const [partnerName, setPartnerName] = useState<string>(PARTNER_POOL[0]);
  const [facilitator, setFacilitator] = useState<string>(PARTNER_POOL[0]);
  const [notes, setNotes] = useState("");
  const [monthValue, setMonthValue] = useState<string>(defaultMonthValue());
  const [week, setWeek] = useState<1 | 2 | 3 | 4 | 5>(2);
  const [, startAssign] = useTransition();
  const { pushToast } = useDemoStore();

  function reset() {
    setStep("owner");
    setOwner(availableOwners[0] ?? "myself");
    setStaffName(STAFF_POOL[0]);
    setPartnerName(PARTNER_POOL[0]);
    setFacilitator(PARTNER_POOL[0]);
    setNotes("");
    setMonthValue(defaultMonthValue());
    setWeek(2);
  }

  function handleClose() {
    reset();
    onClose();
  }

  // Submit fires the actual outcome. Two paths reach here:
  //   • Owner !== "myself" — fires from step "owner" directly.
  //   • Owner === "myself" — fires from step "schedule" with month+week.
  function handleSubmit() {
    if (!context) return;
    const monthLabel = CYCLE_MONTHS.find((m) => m.value === monthValue)?.label;
    const ownerName =
      owner === "staff" ? staffName :
      owner === "partner" ? partnerName :
      owner === "partner_facilitator" ? facilitator : undefined;

    // Caller updates its optimistic local view first.
    onSubmit({
      owner,
      staffName:       owner === "staff" ? staffName : undefined,
      partnerName:     owner === "partner" ? partnerName : undefined,
      facilitatorName: owner === "partner_facilitator" ? facilitator : undefined,
      notes:           notes || undefined,
      month:           owner === "myself" ? monthLabel : undefined,
      week:            owner === "myself" ? week : undefined,
    });

    // Persist the assignment as a real, auditable action + notify the assignee.
    const payloadTitle = context.title;
    const payloadSchool = context.schoolOrCluster;
    const payloadNotes = notes || undefined;
    startAssign(async () => {
      const res = await assignGapActivity({
        gapId: context.gapId,
        title: payloadTitle,
        schoolOrCluster: payloadSchool,
        owner,
        ownerName,
        monthLabel: owner === "myself" ? monthLabel : undefined,
        week: owner === "myself" ? week : undefined,
        notes: payloadNotes,
      });
      if (!res.ok) {
        pushToast({
          tone: "warning",
          title: "Assignment not recorded",
          body: res.reason === "FORBIDDEN" ? "Your role can't assign this activity." : "Couldn't record the assignment — try again.",
        });
      }
    });

    handleClose();
  }

  // Primary button — text + action vary by step + owner. Click flow:
  //   step="owner",  owner != myself → submit
  //   step="owner",  owner == myself → advance to step "schedule"
  //   step="schedule"                → submit
  function handlePrimary() {
    if (step === "owner" && owner === "myself") {
      setStep("schedule");
      return;
    }
    handleSubmit();
  }

  const allowPartner     = availableOwners.includes("partner");
  const allowFacilitator = availableOwners.includes("partner_facilitator");
  const allowMyself      = availableOwners.includes("myself");
  const allowStaff       = availableOwners.includes("staff");

  if (!context) return null;

  const primaryLabel =
    step === "schedule"                          ? "Add to My Plan"        :
    step === "owner"   && owner === "myself"     ? "Schedule the visit"    :
                                                   "Confirm assignment";
  const primaryIcon = step === "schedule" ? Calendar : ArrowRight;

  const activeMonth = CYCLE_MONTHS.find((m) => m.value === monthValue) ?? CYCLE_MONTHS[0];
  const weekOptions = Array.from({ length: activeMonth.weeks }, (_, i) => (i + 1) as 1 | 2 | 3 | 4 | 5);

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title={context.title}
      description={`For ${context.schoolOrCluster}`}
      size="md"
      variant="sheet"
      footer={
        <div className="flex items-center justify-between gap-2">
          {step === "schedule" ? (
            <Button variant="ghost" size="sm" Icon={ChevronLeft} onClick={() => setStep("owner")}>
              Back
            </Button>
          ) : (
            <Button variant="ghost" size="sm" onClick={handleClose}>Cancel</Button>
          )}
          <Button
            size="sm"
            TrailingIcon={step === "schedule" ? undefined : primaryIcon}
            Icon={step === "schedule" ? primaryIcon : undefined}
            onClick={handlePrimary}
          >
            {primaryLabel}
          </Button>
        </div>
      }
    >
      {step === "owner" && (
        <OwnerStep
          context={context}
          owner={owner} setOwner={setOwner}
          staffName={staffName} setStaffName={setStaffName}
          partnerName={partnerName} setPartnerName={setPartnerName}
          facilitator={facilitator} setFacilitator={setFacilitator}
          notes={notes} setNotes={setNotes}
          allowMyself={allowMyself}
          allowStaff={allowStaff}
          allowPartner={allowPartner}
          allowFacilitator={allowFacilitator}
        />
      )}
      {step === "schedule" && (
        <ScheduleStep
          monthValue={monthValue} setMonthValue={setMonthValue}
          week={week} setWeek={setWeek}
          weekOptions={weekOptions}
          activityTitle={context.title}
          schoolOrCluster={context.schoolOrCluster}
        />
      )}
    </Modal>
  );
}

// ────────── Step 1 — owner selection (unchanged content) ──────────

function OwnerStep({
  context,
  owner, setOwner,
  staffName, setStaffName,
  partnerName, setPartnerName,
  facilitator, setFacilitator,
  notes, setNotes,
  allowMyself, allowStaff, allowPartner, allowFacilitator,
}: {
  context: PlanningAssignContext;
  owner: AssignOwner;
  setOwner: (o: AssignOwner) => void;
  staffName: string; setStaffName: (s: string) => void;
  partnerName: string; setPartnerName: (s: string) => void;
  facilitator: string; setFacilitator: (s: string) => void;
  notes: string; setNotes: (s: string) => void;
  allowMyself: boolean;
  allowStaff:  boolean;
  allowPartner: boolean;
  allowFacilitator: boolean;
}) {
  // CCEO-only path — single allowed owner means the picker is just a
  // banner explaining the rule, not a real choice. Keeps the drawer
  // from rendering a stub one-option list.
  const onlyPartner = allowPartner && !allowMyself && !allowStaff && !allowFacilitator;
  return (
    <div className="space-y-3">
      <div className="rounded-xl bg-[var(--color-edify-soft)]/60 border border-[var(--color-edify-divider)] px-3.5 py-3">
        <div className="text-[10px] uppercase tracking-wider font-bold muted">Purpose</div>
        <p className="text-[12px] text-[var(--color-edify-text)] leading-snug mt-1">{context.purpose}</p>
      </div>

      <div className="text-caption uppercase tracking-wider font-bold muted">
        Who will own this activity?
      </div>

      {/* CCEO context hint — set when the role only allows partner.
          Tells the user why no other owner options appear. */}
      {onlyPartner && (
        <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-[11.5px] text-sky-800 inline-flex items-start gap-1.5">
          <Handshake size={12} className="mt-0.5 shrink-0" />
          <span>CCEOs route field activities through a partner. Assign the school below; the partner will schedule and deliver.</span>
        </div>
      )}

      {allowMyself && (
        <OwnerOption
          active={owner === "myself"}
          onClick={() => setOwner("myself")}
          Icon={UserIcon}
          title="Assign to Myself"
          body="Moves to your My Plan queue. You'll pick the month and week on the next step."
        />
      )}

      {allowStaff && (
        <>
          {/* When "myself" isn't an option (PL), staff assignment means a
              supervised CCEO — relabel + scope the pool accordingly. */}
          <OwnerOption
            active={owner === "staff"}
            onClick={() => setOwner("staff")}
            Icon={Users}
            title={allowMyself ? "Assign to Staff" : "Assign to CCEO"}
            body={allowMyself ? "Lands on that staff member's planning queue." : "Lands on that CCEO's planning queue. They schedule and deliver it."}
          />
          {owner === "staff" && (
            <select
              className="w-full h-9 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-body -mt-2"
              value={staffName}
              onChange={(e) => setStaffName(e.target.value)}
            >
              {(allowMyself ? STAFF_POOL : STAFF_POOL.filter((s) => s.includes("(CCEO)"))).map((s) => <option key={s}>{s}</option>)}
            </select>
          )}
        </>
      )}

      {allowPartner && (
        <>
          <OwnerOption
            active={owner === "partner"}
            onClick={() => setOwner("partner")}
            Icon={Handshake}
            title="Assign to Partner"
            body="Goes to the partner's scheduling dashboard. Once scheduled, it returns to your monitoring queue."
          />
          {owner === "partner" && (
            <select
              className="w-full h-9 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-body -mt-2"
              value={partnerName}
              onChange={(e) => setPartnerName(e.target.value)}
            >
              {PARTNER_POOL.map((p) => <option key={p}>{p}</option>)}
            </select>
          )}
        </>
      )}

      {allowFacilitator && (
        <>
          <OwnerOption
            active={owner === "partner_facilitator"}
            onClick={() => setOwner("partner_facilitator")}
            Icon={Handshake}
            title="Assign Partner as Facilitator (Edify still owns)"
            body="You stay the owner. The partner gets a facilitation assignment and confirms availability."
          />
          {owner === "partner_facilitator" && (
            <select
              className="w-full h-9 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-body -mt-2"
              value={facilitator}
              onChange={(e) => setFacilitator(e.target.value)}
            >
              {PARTNER_POOL.map((p) => <option key={p}>{p}</option>)}
            </select>
          )}
        </>
      )}

      <div className="pt-1">
        <label className="block text-caption uppercase tracking-wider font-bold muted mb-1.5">Notes (optional)</label>
        <textarea
          rows={2}
          className="w-full px-3 py-2 rounded-md border border-[var(--color-edify-border)] bg-white text-body resize-none focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
          placeholder="Context the assignee will see"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
        />
      </div>

      <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 flex items-start gap-2">
        <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
        <p className="text-[11.5px] text-emerald-800 leading-snug">
          {nextStepCopy(owner)}
        </p>
      </div>
    </div>
  );
}

// ────────── Step 2 — month + week (Myself only) ──────────

function ScheduleStep({
  monthValue, setMonthValue,
  week, setWeek,
  weekOptions,
  activityTitle, schoolOrCluster,
}: {
  monthValue: string;
  setMonthValue: (v: string) => void;
  week: 1 | 2 | 3 | 4 | 5;
  setWeek: (v: 1 | 2 | 3 | 4 | 5) => void;
  weekOptions: ReadonlyArray<1 | 2 | 3 | 4 | 5>;
  activityTitle: string;
  schoolOrCluster: string;
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-xl bg-[var(--color-edify-soft)]/60 border border-[var(--color-edify-divider)] px-3.5 py-3">
        <div className="text-[10px] uppercase tracking-wider font-bold muted">Scheduling</div>
        <p className="text-[12px] text-[var(--color-edify-text)] leading-snug mt-1">
          <span className="font-extrabold">{activityTitle}</span> at <span className="font-extrabold">{schoolOrCluster}</span>.
          Pick the month and week you'll deliver this activity.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-caption uppercase tracking-wider font-bold muted mb-1.5">Month</label>
          <select
            className="w-full h-10 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[13px] font-semibold"
            value={monthValue}
            onChange={(e) => {
              setMonthValue(e.target.value);
              // Keep week within the new month's range — if the user picked
              // Week 5 in a 5-week month then switches to a 4-week month,
              // clamp to Week 4 so the submission stays valid.
              const m = CYCLE_MONTHS.find((x) => x.value === e.target.value);
              if (m && week > m.weeks) setWeek(m.weeks as 1 | 2 | 3 | 4 | 5);
            }}
          >
            {CYCLE_MONTHS.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-caption uppercase tracking-wider font-bold muted mb-1.5">Week</label>
          <select
            className="w-full h-10 px-3 rounded-md border border-[var(--color-edify-border)] bg-white text-[13px] font-semibold"
            value={week}
            onChange={(e) => setWeek(Number(e.target.value) as 1 | 2 | 3 | 4 | 5)}
          >
            {weekOptions.map((w) => (
              <option key={w} value={w}>Week {w}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2.5 flex items-start gap-2">
        <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
        <p className="text-[11.5px] text-emerald-800 leading-snug">
          Adding to your My Plan queue for{" "}
          <span className="font-extrabold">
            {CYCLE_MONTHS.find((m) => m.value === monthValue)?.label} · Week {week}
          </span>.
          You can reschedule later if the date is interfered with.
        </p>
      </div>
    </div>
  );
}

function OwnerOption({
  active, onClick, Icon, title, body,
}: {
  active: boolean;
  onClick: () => void;
  Icon: typeof UserIcon;
  title: string;
  body: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "w-full text-left rounded-xl border p-3 transition-colors flex items-start gap-3",
        active
          ? "border-[var(--color-edify-primary)] bg-[var(--color-edify-soft)]/40 ring-2 ring-[var(--color-edify-primary)]/20"
          : "border-[var(--color-edify-divider)] bg-white hover:bg-[var(--color-edify-soft)]/40",
      )}
    >
      <span className={cn(
        "grid place-items-center h-9 w-9 rounded-lg shrink-0",
        active ? "bg-[var(--color-edify-primary)] text-white" : "bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)]",
      )}>
        <Icon size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-body font-extrabold tracking-tight">{title}</div>
        <p className="text-[11px] muted leading-snug mt-0.5">{body}</p>
      </div>
    </button>
  );
}

function nextStepCopy(owner: AssignOwner): string {
  switch (owner) {
    case "myself":              return "Pick the month and week on the next step. The activity will move to your My Plan queue with that schedule in place.";
    case "staff":               return "Activity lands on the staff member's planning queue with the purpose and gap context attached.";
    case "partner":             return "Activity appears on the partner's scheduling dashboard. Once they pick a delivery week, it returns to your monitoring queue.";
    case "partner_facilitator": return "Staff (you) stay the owner. The partner gets a facilitation assignment and confirms availability. You still see it in your monitoring queue.";
  }
}

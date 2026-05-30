// PartnerMissionHero — the dark, calm executive opener for the
// Partner Delivery Command Center. Replaces the old generic partner
// info card with a workflow-aware summary: partner identity on the
// left, six status counts on the right reading exactly the same
// numbers as the Workflow Tracker below.
//
// Purpose: in the first 3 seconds the partner should see
//   "Who am I, what's on my plate, what's blocking payment."

import { Handshake, Users, Building2, Calendar, type LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

export type MissionStatusKey =
  | "assigned" | "scheduled" | "evidenceNeeded"
  | "awaitingCceo" | "awaitingPl" | "paid";

export type MissionStatusCard = {
  key: MissionStatusKey;
  label: string;
  count: number;
  tone: "neutral" | "info" | "warn" | "danger" | "success";
};

export type MissionOrg = {
  partnerName: string;
  districts: string[];
  schoolsAssigned: number;
  activeActivities: number;
  edifyFocal: string;
  contractStatus: "Active" | "Paused" | "Pending Renewal";
};

const TONE: Record<MissionStatusCard["tone"], { bg: string; text: string; dot: string }> = {
  neutral: { bg: "bg-white/10",      text: "text-white",         dot: "bg-white/50"   },
  info:    { bg: "bg-blue-500/15",   text: "text-blue-100",      dot: "bg-blue-300"   },
  warn:    { bg: "bg-amber-500/15",  text: "text-amber-100",     dot: "bg-amber-300"  },
  danger:  { bg: "bg-rose-500/15",   text: "text-rose-100",      dot: "bg-rose-300"   },
  success: { bg: "bg-emerald-500/15",text: "text-emerald-100",   dot: "bg-emerald-300"},
};

const FACT_ICON: Record<string, LucideIcon> = {
  districts: Building2,
  schools:   Users,
  active:    Handshake,
  focal:     Users,
  contract:  Calendar,
};

export function PartnerMissionHero({
  org,
  statusCards,
}: {
  org: MissionOrg;
  statusCards: MissionStatusCard[];
}) {
  return (
    <section
      className="relative overflow-hidden rounded-3xl text-white p-5 sm:p-6"
      style={{
        background:
          "linear-gradient(135deg, #1c2f3a 0%, #263d4a 45%, #527083 100%)",
      }}
    >
      {/* Soft amber highlight bottom-right — same vocabulary as the
          existing mission headers across the app. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(closest-side, rgba(245,158,11,0.42), transparent 70%) 92% 92% / 380px 220px no-repeat",
        }}
      />

      <div className="relative grid grid-cols-12 gap-5 items-start">
        {/* Identity column */}
        <div className="col-span-12 lg:col-span-6 min-w-0">
          <p className="text-caption uppercase tracking-[0.12em] text-white/70 font-extrabold">
            Partner
          </p>
          <h1
            className="font-extrabold tracking-tight text-white leading-tight mt-1.5"
            style={{ color: "#fff", fontSize: "clamp(20px, 2.5vw, 26px)" }}
          >
            {org.partnerName}
          </h1>
          <p className="text-body sm:text-[13px] text-white/85 leading-snug mt-1.5 max-w-[58ch]">
            Your assigned school-support work for this week and month. Schedule activities,
            submit evidence, correct returned items, and track payment status.
          </p>

          {/* 5-up facts row — compact, no chrome */}
          <ul className="mt-4 grid grid-cols-2 sm:grid-cols-3 gap-y-2 gap-x-4">
            <Fact Icon={FACT_ICON.districts} label="Districts"        value={org.districts.join(", ")} />
            <Fact Icon={FACT_ICON.schools}   label="Schools assigned" value={String(org.schoolsAssigned)} />
            <Fact Icon={FACT_ICON.active}    label="Active"           value={`${org.activeActivities} activities`} />
            <Fact Icon={FACT_ICON.focal}     label="Edify focal"      value={org.edifyFocal} />
            <Fact Icon={FACT_ICON.contract}  label="Contract"         value={org.contractStatus} status={org.contractStatus === "Active" ? "good" : "warn"} />
          </ul>
        </div>

        {/* Status cards column — 6 calm counts (Assigned, Scheduled,
            Evidence Needed, Awaiting CCEO, Awaiting PL, Paid). */}
        <div className="col-span-12 lg:col-span-6">
          <div className="grid grid-cols-3 gap-2.5">
            {statusCards.map((c) => {
              const tone = TONE[c.tone];
              return (
                <div
                  key={c.key}
                  className={cn(
                    "rounded-xl border border-white/15 backdrop-blur px-3 py-2.5 flex flex-col gap-0.5",
                    tone.bg,
                  )}
                >
                  <span className="text-[9.5px] uppercase tracking-[0.1em] font-bold text-white/70 truncate">
                    {c.label}
                  </span>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={cn("text-[22px] font-extrabold tabular num-hero leading-none", tone.text)}>
                      {c.count}
                    </span>
                    <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", tone.dot)} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </section>
  );
}

function Fact({
  Icon, label, value, status,
}: {
  Icon: LucideIcon;
  label: string;
  value: string;
  status?: "good" | "warn";
}) {
  const valueCls = status === "good"
    ? "text-emerald-300"
    : status === "warn"
      ? "text-amber-300"
      : "text-white";
  return (
    <li className="flex items-start gap-2 min-w-0">
      <span className="mt-0.5 grid place-items-center h-6 w-6 rounded-md bg-white/10 text-white/80 shrink-0">
        <Icon size={11} />
      </span>
      <div className="min-w-0">
        <div className="text-[9.5px] uppercase tracking-[0.1em] font-bold text-white/65">{label}</div>
        <div className={cn("text-[12px] font-extrabold leading-tight truncate", valueCls)}>{value}</div>
      </div>
    </li>
  );
}

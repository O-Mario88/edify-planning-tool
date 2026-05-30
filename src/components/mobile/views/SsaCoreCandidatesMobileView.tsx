"use client";

import { ShieldCheck, Clock, BadgeCheck, AlertCircle, Star } from "lucide-react";
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
  coreSchoolCandidates,
  ssaCoreCandidateSummary,
  ssaVerificationTodos,
  ssaUser,
  type CoreCandidateStatus,
} from "@/lib/ssa-mock";

const STATUS_TONE: Record<CoreCandidateStatus, KpiTone> = {
  "Awaiting Verification":               "amber",
  "Awaiting SSA Verification ID":        "amber",
  "Verified — Potential Core":           "green",
  "Verified — Not Core Ready":           "rose",
  "Recommended for October Onboarding":  "blue",
  "Scheduled for Core Onboarding":       "green",
};

const STATUS_SHORT: Record<CoreCandidateStatus, string> = {
  "Awaiting Verification":               "Awaiting",
  "Awaiting SSA Verification ID":        "Awaiting ID",
  "Verified — Potential Core":           "Potential",
  "Verified — Not Core Ready":           "Not Ready",
  "Recommended for October Onboarding":  "Oct Onboarding",
  "Scheduled for Core Onboarding":       "Scheduled",
};

export function SsaCoreCandidatesMobileView() {
  const summary = ssaCoreCandidateSummary();

  const tiles: MobileKpiTile[] = [
    { key: "eligible",      Icon: Star,        label: "Eligible Clients", value: summary.eligibleClients.toString(),      caption: "in pipeline",     tone: "edify" },
    { key: "awaiting",      Icon: Clock,       label: "Awaiting Verification",  value: summary.awaitingVerification.toString(), caption: "needs SSA verify", tone: "amber" },
    { key: "october",       Icon: ShieldCheck, label: "Oct Onboarding",         value: summary.octoberRecommended.toString(), caption: "recommended",     tone: "green" },
    { key: "flagged",       Icon: BadgeCheck,  label: "Flagged Core",           value: summary.flaggedPotential.toString(),      caption: "potentialCoreFlag", tone: "violet" },
  ];

  const candidateRows: ListRow[] = coreSchoolCandidates.slice(0, 8).map((c) => ({
    key: c.candidateId,
    title: c.schoolName,
    subtitle: `${c.district} · ${c.assignedCceoName}`,
    meta: c.verifiedSsaAverage
      ? `Verified SSA ${c.verifiedSsaAverage.toFixed(1)} · original ${c.originalSsaAverage.toFixed(1)}`
      : `Original SSA ${c.originalSsaAverage.toFixed(1)}`,
    pill: { label: STATUS_SHORT[c.verificationStatus], tone: STATUS_TONE[c.verificationStatus] },
  }));

  const todoRows: ListRow[] = ssaVerificationTodos.slice(0, 8).map((t) => ({
    key: t.todoId,
    title: t.schoolName,
    subtitle: t.assignedStaffId,
    meta: `Original SSA ${t.originalSsaId} · due ${t.dueDate ?? "—"}`,
    pill: {
      label: t.status,
      tone:
        t.status === "Verified" || t.status === "Closed" ? "green" :
        t.status === "Submitted for Review"               ? "blue"  :
        t.status === "Potential Core School"              ? "violet":
        t.status === "Recommended"                        ? "amber" :
                                                            "rose"  ,
    },
  }));

  return (
    <MobileSubpageShell
      title="Core Candidates"
      subtitle={`${summary.eligibleClients} potential core schools · ${summary.awaitingVerification} awaiting verification`}
      initials={ssaUser.initials}
    >
      <MobileKpiGrid tiles={tiles} cols={2} />

      <MobileSectionCard
        title="Candidate Pipeline"
        subtitle="Client schools at SSA 7.5+ across all 8 interventions"
        ctaLabel="View All"
        ctaHref="#all"
      >
        <MobileListRows rows={candidateRows} />
      </MobileSectionCard>

      <MobileSectionCard
        title="SSA Verification Todos"
        subtitle="Auto-created by the recommendation engine"
      >
        <MobileListRows rows={todoRows} />
        <div className="px-3 py-2 border-t border-[#eef2f4]">
          <div className="flex items-center gap-2 text-caption muted">
            <AlertCircle size={11} />
            Duplicate todos prevented per (school, originalSsaId).
          </div>
        </div>
      </MobileSectionCard>
    </MobileSubpageShell>
  );
}

"use client";

import { useState } from "react";
import Link from "next/link";
import { Building2, Star, ShieldCheck, Calendar, ArrowRight } from "lucide-react";
import { SectionCard, StatusBadge } from "@/components/ui/primitives";
import { useDemoStore } from "@/components/demo/DemoStore";
import {
  coreSchoolCandidates,
  confirmSsaVerificationId,
  type CoreSchoolCandidate,
  type CoreCandidateStatus,
} from "@/lib/ssa-mock";
import { cn } from "@/lib/utils";

const statusTone: Record<CoreCandidateStatus, "amber" | "blue" | "green" | "grey" | "edify"> = {
  "Awaiting Verification":              "amber",
  "Awaiting SSA Verification ID":       "blue",
  "Verified — Potential Core":          "green",
  "Verified — Not Core Ready":          "grey",
  "Recommended for October Onboarding": "edify",
  "Scheduled for Core Onboarding":      "edify",
};

export function CoreCandidateTable() {
  const { pushToast } = useDemoStore();
  const [candidates, setCandidates] = useState(coreSchoolCandidates);
  const [draftIds, setDraftIds] = useState<Record<string, string>>({});

  function handleConfirm(c: CoreSchoolCandidate) {
    const id = (draftIds[c.candidateId] ?? "").trim();
    if (!id) {
      alert("SSA Verification ID is required.");
      return;
    }
    // Simulate the engine: synthesize a verified record from the original
    // average so the recalculated path runs end-to-end.
    const result = confirmSsaVerificationId({
      todoId: c.verificationTodoId ?? "TODO-NEW",
      ssaVerificationId: id,
      verifiedSsaRecord: {
        ssaId: c.originalSsaId,
        schoolId: c.schoolId,
        schoolTypeAtAssessment: "Client",
        assessmentDate: "2025-06-15",
        assessedByStaffId: c.assignedCceoId,
        // re-state the 8 scores (trivially derived from the original average
        // for the demo). In production these come from the verified record.
        christLikeBehavior: c.originalSsaAverage,
        exposureToWordOfGod: c.originalSsaAverage,
        feesBudgetAccounts: c.originalSsaAverage,
        governmentRequirements: c.originalSsaAverage,
        leadershipBestPractice: c.originalSsaAverage,
        learningEnvironment: c.originalSsaAverage,
        teachingEnvironment: c.originalSsaAverage,
        enrollment: c.originalSsaAverage,
        averageScore: c.originalSsaAverage,
        verifiedAverageScore: c.originalSsaAverage,
        status: "Verified",
        verificationStatus: "Verified",
        verificationId: id,
      },
    });

    setCandidates((prev) =>
      prev.map((row) => {
        if (row.candidateId !== c.candidateId) return row;
        if (result.flag === "Potential Core School") {
          return {
            ...row,
            ssaVerificationId: id,
            verifiedSsaAverage: c.originalSsaAverage,
            potentialCoreFlag: true,
            verificationStatus: "Verified — Potential Core",
            recommendedOnboardingMonth: "October",
            onboardingRecommendationStatus: "Recommended",
          };
        }
        return {
          ...row,
          ssaVerificationId: id,
          verificationStatus: "Verified — Not Core Ready",
          potentialCoreFlag: false,
        };
      }),
    );
  }

  return (
    <SectionCard
      icon={<Star size={13} />}
      title="Potential Core School Candidate Queue"
      subtitle="Client schools at SSA 7.5+ are routed through verification; verified schools are recommended for October onboarding."
    >
      <table className="w-full dtable">
        <thead>
          <tr>
            <th scope="col" className="text-left">School</th>
            <th scope="col" className="text-left">District</th>
            <th scope="col" className="text-left">Current Type</th>
            <th scope="col" className="text-left">Assigned CCEO</th>
            <th scope="col" className="text-right">Original SSA</th>
            <th scope="col" className="text-right">Verified SSA</th>
            <th scope="col" className="text-left">SSA Verification ID</th>
            <th scope="col" className="text-left">Status</th>
            <th scope="col" className="text-left">October Onboarding</th>
            <th scope="col" className="text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => {
            const showInputRow =
              c.verificationStatus === "Awaiting SSA Verification ID" ||
              c.verificationStatus === "Awaiting Verification";
            return (
              <tr key={c.candidateId} className={cn(c.potentialCoreFlag && "bg-emerald-50/30")}>
                <td>
                  <div className="flex items-center gap-2">
                    <span className="w-7 h-7 rounded-md grid place-items-center bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] shrink-0">
                      <Building2 size={13} />
                    </span>
                    <span className="text-body font-semibold whitespace-nowrap">{c.schoolName}</span>
                  </div>
                </td>
                <td className="text-[12px] muted">{c.district}</td>
                <td>
                  <StatusBadge tone="blue">{c.currentSchoolType}</StatusBadge>
                </td>
                <td className="text-[12px] muted whitespace-nowrap">{c.assignedCceoName}</td>
                <td className="text-right tabular text-body font-bold">
                  {c.originalSsaAverage.toFixed(2)}
                </td>
                <td className="text-right tabular text-body font-extrabold text-[var(--color-success)]">
                  {c.verifiedSsaAverage ? c.verifiedSsaAverage.toFixed(2) : "—"}
                </td>
                <td className="text-[11.5px] tabular">
                  {c.ssaVerificationId ? (
                    c.ssaVerificationId
                  ) : showInputRow ? (
                    <input
                      type="text"
                      placeholder="SSA-VER-…"
                      value={draftIds[c.candidateId] ?? ""}
                      onChange={(e) =>
                        setDraftIds((d) => ({ ...d, [c.candidateId]: e.target.value }))
                      }
                      className="h-7 px-2 rounded-md border border-[var(--color-edify-border)] bg-white text-[12px] w-[140px] focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
                    />
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td>
                  <StatusBadge tone={statusTone[c.verificationStatus]}>
                    {c.verificationStatus}
                  </StatusBadge>
                </td>
                <td className="text-[12px]">
                  {c.recommendedOnboardingMonth ? (
                    <span className="inline-flex items-center gap-1.5 text-[var(--color-edify-primary)] font-semibold">
                      <Calendar size={11} />
                      {c.recommendedOnboardingMonth} ·{" "}
                      <span className="muted font-medium">
                        {c.onboardingRecommendationStatus}
                      </span>
                    </span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="text-right whitespace-nowrap">
                  {showInputRow ? (
                    <button
                      type="button"
                      className="btn btn-sm btn-primary"
                      onClick={() => handleConfirm(c)}
                    >
                      <ShieldCheck size={11} />
                      Confirm SSA ID
                    </button>
                  ) : c.potentialCoreFlag ? (
                    <button
                      type="button"
                      onClick={() => {
                        pushToast({
                          tone: "success",
                          title: `${c.schoolName} queued`,
                          body: "Recommended for October Core onboarding workflow.",
                        });
                      }}
                      className="btn btn-sm btn-primary inline-flex items-center gap-1"
                      aria-label={`Recommend ${c.schoolName} for October onboarding`}
                    >
                      Recommend October
                      <ArrowRight size={11} />
                    </button>
                  ) : (
                    <Link
                      href={`/schools/${c.schoolId}`}
                      className="btn btn-sm"
                      aria-label={`Open ${c.schoolName}`}
                    >
                      View School
                    </Link>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[11px] muted leading-snug">
        <span className="font-semibold text-[var(--color-edify-text)]">Core flagging is engine-only.</span>{" "}
        Only verified SSAs with average ≥ 7.5 across all 8 interventions are flagged Potential Core
        and queued for October onboarding (FY = October → September).
      </div>
    </SectionCard>
  );
}

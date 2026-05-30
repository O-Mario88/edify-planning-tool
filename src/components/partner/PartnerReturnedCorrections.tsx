// PartnerReturnedCorrections — surfaces every CCEO/PL/M&E return so
// the partner knows exactly what to fix. Each row shows the
// standardised return reason (no free-text guessing), what to fix in
// plain language, who returned it, and the due date. Replaces the
// vague "evidence rejected" pattern with structured guidance.

import { RotateCcw, AlertTriangle, ArrowRight, Building2, Calendar, UserCheck } from "lucide-react";
import { cn } from "@/lib/utils";
import { evidenceSummaries } from "@/lib/partner/partner-evidence-mock";
import {
  RETURN_REASON_LABEL,
  type PartnerEvidenceSummary,
  type StandardReturnReason,
} from "@/lib/partner/partner-evidence";

// "What to fix" guidance per standardised reason. Standardising this
// keeps the language consistent across every return so the partner
// sees the same instruction every time.
const FIX_GUIDANCE: Record<StandardReturnReason, string> = {
  attendance_sheet_missing:        "Upload the signed attendance sheet showing teacher names, school, date, and facilitator.",
  attendance_sheet_unclear:        "Upload a clearer attendance sheet — names must be readable and the school + date visible.",
  wrong_school:                    "Confirm the correct school and re-upload all evidence with the right school name.",
  wrong_date:                      "Correct the activity date in the report and on the evidence documents.",
  wrong_activity_type:             "Confirm the activity type. If wrong, contact the assigning CCEO before re-uploading.",
  missing_debrief:                 "Add a partner debrief summarising what was delivered, lessons learned, and next steps.",
  missing_ssa_link:                "Link the activity to the school's SSA weak area in the report.",
  missing_participant_count:       "Add the number of teachers / leaders / students involved.",
  duplicate_submission:            "This was already submitted under another activity. Open that activity or contact your CCEO.",
  poor_quality_image:              "Re-take or re-upload a clearer image (well-lit, in focus, readable text).",
  unsupported_document_type:       "Convert to PDF or JPG and re-upload. .docx / .heic / .webp are not accepted.",
  outside_partner_scope:           "This activity is outside the contracted scope. Contact your CCEO to reassign or scope.",
  report_does_not_match:           "The report content does not match the assigned activity. Rewrite the report to reflect what was actually delivered.",
  evidence_does_not_prove_delivery:"The evidence does not show the work was completed. Add proof (photos / attendance / signed delivery note).",
};

export function PartnerReturnedCorrections() {
  const returned = evidenceSummaries.filter(
    (s) => s.status === "returned_for_correction",
  );

  return (
    <section className="card p-3.5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="grid place-items-center h-7 w-7 rounded-md bg-amber-100 text-amber-700">
              <RotateCcw size={14} />
            </span>
            <h3 className="text-[15px] font-extrabold tracking-tight">Returned for Correction</h3>
          </div>
          <p className="text-[12px] muted mt-1">
            Specific items returned by your CCEO / PL / M&amp;E. Each row tells you exactly what to fix.
          </p>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] uppercase tracking-wide font-bold muted">To correct</div>
          <div className="text-[18px] font-extrabold tabular num-hero text-amber-700 leading-none mt-1">
            {returned.length}
          </div>
        </div>
      </header>

      {returned.length === 0 ? (
        <div className="text-center py-6 text-[12px] muted italic">
          Nothing returned — your evidence is clean. Keep it up.
        </div>
      ) : (
        <ul className="space-y-2">
          {returned.map((s) => (
            <CorrectionRow key={s.activityId} summary={s} />
          ))}
        </ul>
      )}
    </section>
  );
}

function CorrectionRow({ summary: s }: { summary: PartnerEvidenceSummary }) {
  if (!s.returnReason) return null;
  const reasonLabel = RETURN_REASON_LABEL[s.returnReason];
  const fix = FIX_GUIDANCE[s.returnReason];
  const dueDate = s.dueDateIso ? new Date(s.dueDateIso) : null;

  return (
    <li className="rounded-xl border border-amber-200 bg-amber-50/40 p-3.5">
      <div className="flex items-start gap-3">
        <span className="grid place-items-center h-9 w-9 rounded-lg bg-amber-100 text-amber-700 shrink-0">
          <AlertTriangle size={14} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-1.5 text-caption muted">
                <Building2 size={10} />
                <span className="truncate">{s.schoolName}</span>
                <span>·</span>
                <span className="truncate">{s.activityLabel}</span>
              </div>
              <h4 className="text-[13.5px] font-extrabold tracking-tight mt-0.5">
                {reasonLabel}
              </h4>
            </div>
            {dueDate && (
              <span className="inline-flex items-center gap-1 text-caption font-bold text-amber-800 whitespace-nowrap shrink-0">
                <Calendar size={11} />
                Due {dueDate.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}
              </span>
            )}
          </div>

          {/* What to fix — plain language guidance */}
          <p className="text-[12px] text-amber-900 leading-snug mt-1.5">
            <span className="font-bold">What to fix:</span> {fix}
          </p>

          {/* Reviewer comment (if any) */}
          {s.reviewerComment && (
            <p className="text-[11.5px] text-amber-800/90 leading-snug mt-1.5 italic">
              "{s.reviewerComment}"
            </p>
          )}

          {/* Footer */}
          <div className="mt-2.5 flex items-center gap-2 flex-wrap">
            <button
              type="button"
              className="inline-flex items-center gap-1 h-8 px-3 rounded-md bg-amber-500 text-white text-[11.5px] font-extrabold hover:bg-amber-600"
            >
              Correct Submission <ArrowRight size={11} />
            </button>
            {s.returnedBy && (
              <span className={cn(
                "inline-flex items-center gap-1 text-caption muted ml-auto",
              )}>
                <UserCheck size={10} />
                Returned by {s.returnedBy}
              </span>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

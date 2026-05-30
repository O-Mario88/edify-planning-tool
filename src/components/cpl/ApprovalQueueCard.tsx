"use client";

import { useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { CheckCircle2, ClipboardList, Loader2 } from "lucide-react";
import Link from "next/link";
import { SectionCard, TableEmptyRow } from "@/components/ui/primitives";
import { approvalQueue } from "@/lib/cpl-mock";
import { useDemoStore } from "@/components/demo/DemoStore";
import { spring } from "@/lib/motion";

// 4-tone discipline: pending → amber, critical → rose. Drop the
// decorative orange variant so all "issue" chips speak one of two tones.
const issueChip: Record<string, string> = {
  "Missing Fields":      "bg-amber-100 text-amber-800",
  "Attachments Missing": "bg-rose-100 text-rose-700",
  "Targets Not Set":     "bg-amber-100 text-amber-800",
};

export function ApprovalQueueCard() {
  const { pushToast } = useDemoStore();
  const reduce = useReducedMotion();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set());

  function handleApprove(id: string, staff: string) {
    setBusyId(`approve-${id}`);
    window.setTimeout(() => {
      setApprovedIds((prev) => new Set(prev).add(id));
      setBusyId(null);
      pushToast({
        tone: "success",
        title: `Plan approved`,
        body: `${staff}'s plan is now ready for funding workflow.`,
      });
    }, 450);
  }

  function handleReview(id: string, staff: string) {
    setBusyId(`review-${id}`);
    window.setTimeout(() => {
      setBusyId(null);
      pushToast({
        tone: "info",
        title: "Review note logged",
        body: `Review opened for ${staff}'s plan. Audit entry recorded.`,
      });
    }, 350);
  }

  return (
    <SectionCard
      icon={<ClipboardList size={13} />}
      title="Approval Queue"
      actions={
        <Link className="text-[var(--text-body)] font-semibold text-[var(--color-edify-primary)]" href="/approvals">
          View All pending approvals →
        </Link>
      }
    >
      {/* Mobile card list — each pending approval becomes a stacked
          card so the 5-column table doesn't force horizontal scroll. */}
      <ul className="md:hidden flex flex-col gap-2">
        {approvalQueue.map((r) => (
          <motion.li
            key={r.id}
            animate={approvedIds.has(r.id) ? { backgroundColor: "#ecfdf5" } : { backgroundColor: "#ffffff" }}
            transition={reduce ? { duration: 0 } : { duration: 0.6 }}
            className="rounded-xl border border-[var(--color-edify-border)] px-3 py-2.5 flex flex-col gap-2"
            style={{ display: undefined }}
          >
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-full bg-[var(--color-edify-primary)] text-white text-[11px] font-extrabold grid place-items-center shrink-0">
                {r.initials}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-body font-extrabold text-slate-900 truncate">{r.staff}</div>
                <div className="text-caption muted truncate">{r.activitiesCovered} · Submitted {r.submitted}</div>
              </div>
            </div>
            {r.issues.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {r.issues.map((i) => (
                  <span
                    key={i}
                    className={`inline-flex items-center px-2 py-[2px] rounded-md text-[10px] font-semibold ${issueChip[i] ?? "bg-[#eef2f4] text-[#475467]"}`}
                  >
                    {i}
                  </span>
                ))}
              </div>
            )}
            <div className="flex items-center gap-1.5 justify-end">
              <button
                type="button"
                onClick={() => handleReview(r.id, r.staff)}
                disabled={busyId === `review-${r.id}` || approvedIds.has(r.id)}
                className="btn btn-sm disabled:opacity-55"
              >
                {busyId === `review-${r.id}` ? <Loader2 size={11} className="animate-spin" /> : null}
                Review
              </button>
              {approvedIds.has(r.id) ? (
                <motion.span
                  initial={reduce ? false : { scale: 0.7, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  transition={reduce ? { duration: 0 } : spring.pop}
                  className="inline-flex items-center gap-1 h-7 px-2.5 rounded-md text-[11px] font-bold bg-emerald-100 text-emerald-700"
                >
                  <CheckCircle2 size={11} />
                  Approved
                </motion.span>
              ) : (
                <button
                  type="button"
                  onClick={() => handleApprove(r.id, r.staff)}
                  disabled={busyId === `approve-${r.id}`}
                  className="inline-flex items-center justify-center gap-1 h-7 px-2.5 rounded-md text-[11px] font-semibold bg-[var(--color-success)] text-white hover:opacity-90 disabled:opacity-55"
                  aria-label={`Approve ${r.staff}'s plan`}
                >
                  {busyId === `approve-${r.id}` ? <Loader2 size={11} className="animate-spin" /> : null}
                  Approve
                </button>
              )}
            </div>
          </motion.li>
        ))}
      </ul>

      <div className="hidden md:block overflow-x-auto scrollbar -mx-1 px-1">
        <table className="w-full dtable">
          <thead>
            <tr>
              <th scope="col" className="text-left">Staff / CCEO</th>
              <th scope="col" className="text-left">Activities Covered</th>
              <th scope="col" className="text-left">Missing Fields / Issues</th>
              <th scope="col" className="text-left">Submitted</th>
              <th scope="col" className="text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {approvalQueue.map((r) => (
              <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/40">
                <td>
                  <div className="flex items-center gap-2">
                    <div className="w-7 h-7 rounded-full bg-[var(--color-edify-primary)] text-white text-[10px] font-bold grid place-items-center shrink-0">
                      {r.initials}
                    </div>
                    <div className="text-[11.5px] font-semibold whitespace-nowrap">{r.staff}</div>
                  </div>
                </td>
                <td className="text-[11.5px] muted whitespace-nowrap">{r.activitiesCovered}</td>
                <td>
                  <div className="flex flex-wrap gap-1">
                    {r.issues.map((i) => (
                      <span
                        key={i}
                        className={`inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-semibold ${issueChip[i] ?? "bg-[#eef2f4] text-[#475467]"}`}
                      >
                        {i}
                      </span>
                    ))}
                  </div>
                </td>
                <td className="text-[11.5px] muted">{r.submitted}</td>
                <td className="text-right whitespace-nowrap">
                  <div className="inline-flex items-center gap-1.5">
                    <button
                      type="button"
                      onClick={() => handleReview(r.id, r.staff)}
                      disabled={busyId === `review-${r.id}` || approvedIds.has(r.id)}
                      className="btn btn-sm text-caption disabled:opacity-55"
                    >
                      {busyId === `review-${r.id}` ? <Loader2 size={10} className="animate-spin" /> : null}
                      Review
                    </button>
                    {approvedIds.has(r.id) ? (
                      <motion.span
                        initial={reduce ? false : { scale: 0.7, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={reduce ? { duration: 0 } : spring.pop}
                        className="inline-flex items-center gap-1 h-6 px-2 rounded-md text-caption font-bold bg-emerald-100 text-emerald-700"
                      >
                        <CheckCircle2 size={10} />
                        Approved
                      </motion.span>
                    ) : (
                      <button
                        type="button"
                        onClick={() => handleApprove(r.id, r.staff)}
                        disabled={busyId === `approve-${r.id}`}
                        className="inline-flex items-center justify-center gap-1 h-6 px-2 rounded-md text-caption font-semibold bg-[var(--color-success)] text-white hover:opacity-90 disabled:opacity-55"
                        aria-label={`Approve ${r.staff}'s plan`}
                      >
                        {busyId === `approve-${r.id}` ? <Loader2 size={10} className="animate-spin" /> : null}
                        Approve
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {approvalQueue.length === 0 && (
              <TableEmptyRow
                colSpan={5}
                title="No plans pending approval"
                body="When CCEOs submit monthly plans they'll appear here for your review. New CCEOs start with empty plans — encourage early submission."
              />
            )}
          </tbody>
        </table>
      </div>

      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[var(--text-caption)] muted leading-snug">
        <span className="font-semibold text-[var(--color-edify-text)]">Plan approvals only.</span>{" "}
        Fund approval flows separately through the Program Accountant, then Country Director, then RVP where required.
      </div>
    </SectionCard>
  );
}

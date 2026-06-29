"use client";

import { useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";
import { CheckCircle2, ClipboardList, Loader2, RotateCcw } from "lucide-react";
import { SectionCard, TableEmptyRow } from "@/components/ui/primitives";
import { useDemoStore } from "@/components/demo/DemoStore";
import { spring } from "@/lib/motion";
import { getTeamPlansForApproval, approvePlan, returnPlan } from "@/lib/actions/plan-actions";
import type { BeMonthlyPlan } from "@/lib/api/surfaces";

const ugx = (n: number) => `UGX ${Math.round(n).toLocaleString()}`;

export function ApprovalQueueCard() {
  const { pushToast } = useDemoStore();
  const reduce = useReducedMotion();
  const [busyId, setBusyId] = useState<string | null>(null);
  const [plans, setPlans] = useState<BeMonthlyPlan[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [approvedIds, setApprovedIds] = useState<Set<string>>(new Set());

  const load = () => {
    setLoading(true);
    setError(null);
    getTeamPlansForApproval()
      .then((res) => {
        if (res.ok && res.plans) {
          setPlans(res.plans);
        } else {
          setError(res.error ?? "Failed to load plans");
        }
      })
      .catch(() => setError("Failed to load plans"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
  }, []);

  async function handleApprove(id: string, staff: string) {
    setBusyId(`approve-${id}`);
    try {
      const res = await approvePlan(id);
      if (res.ok) {
        setApprovedIds((prev) => new Set(prev).add(id));
        pushToast({
          tone: "success",
          title: `Plan approved`,
          body: `${staff}'s plan is now approved.`,
        });
        load();
      } else {
        pushToast({
          tone: "error",
          title: `Failed to approve`,
          body: (res as any).message ?? (res as any).reason ?? "The change was rejected by backend.",
        });
      }
    } catch {
      pushToast({
        tone: "error",
        title: `Failed to approve`,
        body: "Could not reach the server.",
      });
    } finally {
      setBusyId(null);
    }
  }

  async function handleReturn(id: string, staff: string) {
    const reason = window.prompt("Enter return reason:");
    if (reason === null) return; // user cancelled prompt
    
    setBusyId(`return-${id}`);
    try {
      const res = await returnPlan(id, reason.trim() || "Needs adjustments");
      if (res.ok) {
        pushToast({
          tone: "info",
          title: "Plan returned",
          body: `${staff}'s plan has been returned for adjustments.`,
        });
        load();
      } else {
        pushToast({
          tone: "error",
          title: `Failed to return`,
          body: (res as any).message ?? (res as any).reason ?? "The action was rejected by backend.",
        });
      }
    } catch {
      pushToast({
        tone: "error",
        title: `Failed to return`,
        body: "Could not reach the server.",
      });
    } finally {
      setBusyId(null);
    }
  }

  const getInitials = (name?: string | null) => {
    if (!name) return "??";
    return name.split(" ").map(n => n[0]).join("").toUpperCase().slice(0, 2);
  };

  const getMonthLabel = (iso: string) => {
    const MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const match = iso.match(/-(\d{2})$/);
    if (match) return `${MONTHS[Number(match[1])]} ${iso.slice(0, 4)}`;
    return iso;
  };

  return (
    <SectionCard
      icon={<ClipboardList size={13} />}
      title="Plan Approval Queue"
      actions={
        <button onClick={load} className="text-[var(--text-body)] font-semibold text-[var(--color-edify-primary)] hover:underline">
          Refresh Queue
        </button>
      }
    >
      {loading ? (
        <div className="py-6 flex items-center justify-center gap-2 text-caption muted">
          <Loader2 size={14} className="animate-spin text-[var(--color-edify-primary)]" />
          Loading plan approval queue...
        </div>
      ) : error ? (
        <div className="py-4 text-center text-caption text-rose-600 font-medium">
          {error}
        </div>
      ) : !plans || plans.length === 0 ? (
        <TableEmptyRow
          colSpan={5}
          title="No plans pending approval"
          body="When CCEOs submit monthly plans they'll appear here for your review. New CCEOs start with empty plans — encourage early submission."
        />
      ) : (
        <>
          {/* Mobile card list */}
          <ul className="md:hidden flex flex-col gap-2">
            {plans.map((r) => (
              <motion.li
                key={r.id}
                animate={approvedIds.has(r.id) ? { backgroundColor: "#ecfdf5" } : { backgroundColor: "#ffffff" }}
                transition={reduce ? { duration: 0 } : { duration: 0.6 }}
                className="rounded-xl border border-[var(--color-edify-border)] px-3 py-2.5 flex flex-col gap-2"
              >
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 rounded-full bg-[var(--color-edify-primary)] text-white text-[11px] font-extrabold grid place-items-center shrink-0">
                    {getInitials(r.ownerName)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-body font-extrabold text-slate-900 truncate">{r.ownerName ?? "Unknown Staff"}</div>
                    <div className="text-caption muted truncate">
                      {getMonthLabel(r.monthIso)} · {r.activities?.length ?? r.activityCount ?? 0} activities · {ugx(r.totalCostCents / 100)}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 justify-end">
                  <button
                    type="button"
                    onClick={() => handleReturn(r.id, r.ownerName ?? "Staff")}
                    disabled={busyId === `return-${r.id}` || approvedIds.has(r.id)}
                    className="btn btn-sm disabled:opacity-55 inline-flex items-center gap-1"
                  >
                    {busyId === `return-${r.id}` ? <Loader2 size={11} className="animate-spin" /> : <RotateCcw size={11} />}
                    Return
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
                      onClick={() => handleApprove(r.id, r.ownerName ?? "Staff")}
                      disabled={busyId === `approve-${r.id}`}
                      className="inline-flex items-center justify-center gap-1 h-7 px-2.5 rounded-md text-[11px] font-semibold bg-[var(--color-success)] text-white hover:opacity-90 disabled:opacity-55"
                      aria-label={`Approve ${r.ownerName ?? "Staff"}'s plan`}
                    >
                      {busyId === `approve-${r.id}` ? <Loader2 size={11} className="animate-spin" /> : null}
                      Approve
                    </button>
                  )}
                </div>
              </motion.li>
            ))}
          </ul>

          {/* Desktop view */}
          <div className="hidden md:block overflow-x-auto scrollbar -mx-1 px-1">
            <table className="w-full dtable">
              <thead>
                <tr>
                  <th scope="col" className="text-left">Staff / CCEO</th>
                  <th scope="col" className="text-left">Month</th>
                  <th scope="col" className="text-left">Activities</th>
                  <th scope="col" className="text-left">Total Budget</th>
                  <th scope="col" className="text-right">Action</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((r) => (
                  <tr key={r.id} className="hover:bg-[var(--color-edify-soft)]/40">
                    <td>
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-full bg-[var(--color-edify-primary)] text-white text-[10px] font-bold grid place-items-center shrink-0">
                          {getInitials(r.ownerName)}
                        </div>
                        <div className="text-[11.5px] font-semibold whitespace-nowrap">{r.ownerName ?? "Unknown Staff"}</div>
                      </div>
                    </td>
                    <td className="text-[11.5px] muted whitespace-nowrap">{getMonthLabel(r.monthIso)}</td>
                    <td className="text-[11.5px] muted whitespace-nowrap">{r.activities?.length ?? r.activityCount ?? 0} activities</td>
                    <td className="text-[11.5px] font-extrabold tabular text-slate-800">{ugx(r.totalCostCents / 100)}</td>
                    <td className="text-right whitespace-nowrap">
                      <div className="inline-flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => handleReturn(r.id, r.ownerName ?? "Staff")}
                          disabled={busyId === `return-${r.id}` || approvedIds.has(r.id)}
                          className="btn btn-sm text-caption disabled:opacity-55 inline-flex items-center gap-1"
                        >
                          {busyId === `return-${r.id}` ? <Loader2 size={10} className="animate-spin" /> : <RotateCcw size={10} />}
                          Return
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
                            onClick={() => handleApprove(r.id, r.ownerName ?? "Staff")}
                            disabled={busyId === `approve-${r.id}`}
                            className="inline-flex items-center justify-center gap-1 h-6 px-2 rounded-md text-caption font-semibold bg-[var(--color-success)] text-white hover:opacity-90 disabled:opacity-55"
                            aria-label={`Approve ${r.ownerName ?? "Staff"}'s plan`}
                          >
                            {busyId === `approve-${r.id}` ? <Loader2 size={10} className="animate-spin" /> : null}
                            Approve
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <div className="mt-3 pt-3 border-t border-[#eef2f4] text-[var(--text-caption)] muted leading-snug">
        <span className="font-semibold text-[var(--color-edify-text)]">Plan approvals only.</span>{" "}
        Fund approval flows separately through the Program Accountant, then Country Director, then RVP where required.
      </div>
    </SectionCard>
  );
}

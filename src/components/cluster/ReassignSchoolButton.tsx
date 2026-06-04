"use client";

// Reassign a school from its current cluster to another. Uses the existing
// assignToExistingClusterAction, whose engine path (assignSchoolToCluster)
// already records a "reassignment" when the school is currently clustered.
// Inline picker → server action → toast + refresh.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeftRight, Loader2, X } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { assignToExistingClusterAction } from "@/lib/actions/cluster-actions";

export type ReassignTarget = { id: string; name: string; district: string };

export function ReassignSchoolButton({
  schoolId,
  schoolName,
  currentClusterId,
  targets,
}: {
  schoolId: string;
  schoolName: string;
  currentClusterId: string;
  targets: ReassignTarget[];
}) {
  const [open, setOpen] = useState(false);
  const [targetId, setTargetId] = useState("");
  const [isPending, startTransition] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  const options = targets.filter((t) => t.id !== currentClusterId);
  if (options.length === 0) return null;

  function move() {
    if (!targetId) return;
    startTransition(async () => {
      const res = await assignToExistingClusterAction([schoolId], targetId);
      if (res.ok && res.assigned > 0) {
        const dest = options.find((t) => t.id === targetId)?.name ?? "the cluster";
        pushToast({ tone: "success", title: "School reassigned", body: `${schoolName} moved to ${dest}.` });
        setOpen(false);
        setTargetId("");
        router.refresh();
      } else {
        pushToast({
          tone: "warning",
          title: "Couldn't reassign",
          body: !res.ok && res.reason === "FORBIDDEN" ? "You can't reassign cluster membership." : "Reassignment failed — refresh and retry.",
        });
      }
    });
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        title={`Reassign ${schoolName}`}
        aria-label={`Reassign ${schoolName} to another cluster`}
        className="ml-1 inline-flex items-center justify-center w-6 h-6 rounded-md text-slate-400 hover:text-[var(--color-edify-primary)] hover:bg-[var(--color-edify-soft)]/60 shrink-0"
      >
        <ArrowLeftRight size={12} />
      </button>
    );
  }

  return (
    <span className="ml-1 inline-flex items-center gap-1 shrink-0">
      <select
        value={targetId}
        onChange={(e) => setTargetId(e.target.value)}
        aria-label={`Target cluster for ${schoolName}`}
        className="h-7 max-w-[150px] rounded-md border border-[var(--color-edify-border)] bg-white text-[11px] px-1.5 focus:outline-none focus:ring-2 focus:ring-[var(--color-edify-primary)]/30"
      >
        <option value="">Move to…</option>
        {options.map((t) => (
          <option key={t.id} value={t.id}>{t.name} · {t.district}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={move}
        disabled={isPending || !targetId}
        className="inline-flex items-center justify-center h-7 px-2 rounded-md bg-[var(--color-edify-primary)] text-white text-[11px] font-bold hover:brightness-110 disabled:opacity-50"
      >
        {isPending ? <Loader2 size={11} className="animate-spin" /> : "Move"}
      </button>
      <button
        type="button"
        onClick={() => { setOpen(false); setTargetId(""); }}
        aria-label="Cancel reassignment"
        className="inline-flex items-center justify-center w-6 h-7 rounded-md text-slate-500 hover:bg-slate-100"
      >
        <X size={12} />
      </button>
    </span>
  );
}

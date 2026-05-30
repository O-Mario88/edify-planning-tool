"use client";

// Admin trigger that runs the full W3→W5 chain (createPlan,
// addActivityToPlan x3, submitPlan, approvePlan → triggers weekly
// fund request generation). Used on /admin/audit-log so the audit
// table populates demonstrably with one click.
//
// The button isn't a permanent feature — it's a build-out aid the
// team can remove once the real plan-builder is wired. Until then
// it's the fastest way to prove every server action emits the right
// audit + notification side effects.

import { useTransition, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Sparkles, AlertCircle, CheckCircle2 } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { seedSamplePlan, type SeedResult } from "@/lib/actions/demo-seed-actions";
import { cn } from "@/lib/utils";

export function SeedSamplePlanButton() {
  const [pending, startTransition] = useTransition();
  const [last, setLast] = useState<SeedResult | null>(null);
  const { pushToast } = useDemoStore();
  const router = useRouter();

  function run() {
    startTransition(async () => {
      const res = await seedSamplePlan();
      setLast(res);
      if (res.ok) {
        pushToast({
          tone: "success",
          title: "Sample plan seeded · W3→W11",
          body: `${res.activityIds.length} acts · ${res.generatedRequestIds.length} WFRs · ${res.participantIds.length} participants · ${res.ssaSnapshotIds.length} SSAs · ${res.partnerActivityIds.length} partner act · donor hash ${res.donorFiltersHash?.slice(0, 12) ?? "—"}`,
        });
      } else if (res.reason === "FORBIDDEN") {
        pushToast({ tone: "warning", title: "Admin only", body: "Sign in as Admin to seed sample data." });
      } else {
        pushToast({ tone: "error", title: `Failed at ${res.step}`, body: res.detail });
      }
      router.refresh();
    });
  }

  return (
    <div className="flex items-center gap-3 flex-wrap">
      <button
        type="button"
        onClick={run}
        disabled={pending}
        className={cn(
          "inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-slate-900 hover:bg-slate-800 text-white text-[12px] font-extrabold shadow-[0_6px_14px_-6px_rgba(15,23,32,0.5)] transition-all",
          "disabled:opacity-50 disabled:cursor-not-allowed",
        )}
      >
        {pending ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />}
        Seed sample plan (W3 → W5)
      </button>
      {last?.ok && (
        <span className="inline-flex items-center gap-1.5 text-[11px] muted">
          <CheckCircle2 size={12} className="text-emerald-600" />
          Last run: <span className="font-mono">{last.planId.slice(0, 12)}…</span> · {last.activityIds.length} act · {last.generatedRequestIds.length} req
        </span>
      )}
      {last && !last.ok && last.reason === "FAILED" && (
        <span className="inline-flex items-center gap-1.5 text-[11px] text-rose-700">
          <AlertCircle size={12} />
          Failed at <span className="font-mono">{last.step}</span>: {last.detail}
        </span>
      )}
    </div>
  );
}

"use client";

// Run-quality-check CTA. Canonical button→server-action wiring: useTransition
// for pending state, toast the discriminated result, router.refresh() to pull
// the new run (the action already revalidated the route cache server-side).

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ShieldCheck } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { runQualityCheck } from "@/lib/actions/quality-actions";

export function RunQualityCheckButton() {
  const [isPending, startTransition] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  function run() {
    startTransition(async () => {
      const res = await runQualityCheck();
      if (res.ok) {
        pushToast({
          tone: "success",
          title: "Quality check complete",
          body: `Scanned ${res.scannedActivities} activities — ${res.totalIssues} open issues found.`,
        });
        router.refresh();
      } else {
        pushToast({
          tone: "warning",
          title: "Not permitted",
          body: "Only Impact Assessment, Country Director, and Admin can run quality checks.",
        });
      }
    });
  }

  return (
    <button
      type="button"
      onClick={run}
      disabled={isPending}
      className="h-9 px-3 rounded-xl bg-[var(--color-edify-primary)] text-white text-body font-semibold hover:brightness-110 inline-flex items-center gap-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
    >
      {isPending ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />}
      {isPending ? "Running…" : "Run Quality Check"}
    </button>
  );
}

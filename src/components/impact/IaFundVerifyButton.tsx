"use client";

// IA "Verify for disbursement" button — calls verifyFundRequestByIa,
// which stamps iaVerifiedAt on a CCEO weekly fund request and unblocks
// the accountant's disbursement (the B12 gate). Without this control the
// gate was unreachable, deadlocking every CCEO weekly disbursement.

import { useTransition } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Loader2 } from "lucide-react";
import { verifyFundRequestByIa } from "@/lib/actions/weekly-fund-actions";
import { useDemoStore } from "@/components/demo/DemoStore";

export function IaFundVerifyButton({ reqId, label }: { reqId: string; label: string }) {
  const [pending, startTransition] = useTransition();
  const { pushToast } = useDemoStore();
  const router = useRouter();

  function run() {
    startTransition(async () => {
      const res = await verifyFundRequestByIa(reqId);
      if (res.ok) {
        pushToast({ tone: "success", title: "Verified for disbursement", body: `${label} cleared — the accountant can now disburse.` });
      } else {
        pushToast({ tone: "warning", title: "Couldn't verify", body: `Reason: ${res.reason}` });
      }
      router.refresh();
    });
  }

  return (
    <button
      type="button"
      onClick={run}
      disabled={pending}
      className="inline-flex items-center gap-1 h-8 px-3 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-[11.5px] font-bold whitespace-nowrap shrink-0 disabled:opacity-50"
    >
      {pending ? <Loader2 size={12} className="animate-spin" /> : <CheckCircle2 size={12} />}
      Verify for disbursement
    </button>
  );
}

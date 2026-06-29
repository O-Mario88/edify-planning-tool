"use client";

import { useState, useTransition } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { approveImport } from "@/lib/data-intake-actions";
import { useDemoStore } from "@/components/demo/DemoStore";

// Tiny client island used inside the Data Validation queue server page.
// Calls the `approveImport` server action and renders a "Approved" pill
// on success so the row stays visually settled until the next reload
// picks up the server-side status flip.

export function ApproveImportButton({
  batchId,
  fileName,
  label = "Approve →",
}: {
  batchId: string;
  fileName: string;
  label?: string;
}) {
  const { pushToast } = useDemoStore();
  const [pending, startTransition] = useTransition();
  const [done, setDone] = useState(false);

  function go() {
    startTransition(async () => {
      const res = await approveImport(batchId);
      if (!res.ok) {
        pushToast({
          tone: "warning",
          title: "Could not import batch",
          body:
            res.reason === "FORBIDDEN" ? "Your role cannot import batches." :
            res.reason === "NOT_FOUND" ? "Batch no longer exists." :
            "Batch is not in a validated state.",
        });
        return;
      }
      setDone(true);
      pushToast({
        tone: "success",
        title: "Batch imported successfully",
        body: `${fileName} merged into school directory.`,
      });
    });
  }

  if (done) {
    return (
      <span className="text-[11px] font-bold text-emerald-700 inline-flex items-center gap-1">
        <CheckCircle2 size={11} />
        Imported
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={go}
      disabled={pending}
      className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline disabled:opacity-55 inline-flex items-center gap-1"
    >
      {pending && <Loader2 size={11} className="animate-spin" />}
      {label}
    </button>
  );
}

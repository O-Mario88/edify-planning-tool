"use client";

import { useEffect, useState } from "react";
import { CheckCircle2 } from "lucide-react";
import { SalesforceCompletionModal, type CompletionActivity } from "./SalesforceCompletionModal";
import { loadCompletions, saveCompletion } from "@/lib/cceo-execution-store";
import { cn } from "@/lib/utils";

// Reusable "Confirm" action for the /visits and /trainings index pages.
//
// Opens the SalesforceCompletionModal — the same Completion Verification Gate
// used in the CCEO execution flow. Entering the Salesforce ID (SVE- for visits,
// TS- for trainings) confirms the activity is logged in Salesforce; trainings
// additionally capture the teacher / school-leader breakdown. Persists to the
// client-side completion store so the row flips to "Confirmed".
export function ConfirmCompletionButton({
  activity,
  className,
}: {
  activity: CompletionActivity;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    setDone(!!loadCompletions()[activity.id]);
  }, [activity.id]);

  if (done) {
    return (
      <span className={cn("inline-flex items-center gap-1 px-2 py-[3px] rounded-md text-[11px] font-extrabold bg-emerald-100 text-emerald-700 whitespace-nowrap", className)}>
        <CheckCircle2 size={12} /> Confirmed
      </span>
    );
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn("btn btn-sm", className)}
      >
        Confirm
      </button>
      <SalesforceCompletionModal
        activity={activity}
        open={open}
        onClose={() => setOpen(false)}
        onComplete={(c) => { saveCompletion(c); setDone(true); }}
      />
    </>
  );
}

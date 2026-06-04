"use client";

import { useEffect, useState, useTransition } from "react";
import { CheckCircle2 } from "lucide-react";
import { SalesforceCompletionModal, type CompletionActivity } from "./SalesforceCompletionModal";
import { loadCompletions, saveCompletion } from "@/lib/cceo-execution-store";
import { useDemoStore } from "@/components/demo/DemoStore";
import { confirmActivityCompletion } from "@/lib/actions/completion-actions";
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
  confirmed = false,
}: {
  activity: CompletionActivity;
  className?: string;
  /** Server-confirmed state (from the completion overlay) so the badge shows
   *  for everyone, not just the browser that confirmed it. */
  confirmed?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [done, setDone] = useState(confirmed);
  const [, startConfirm] = useTransition();
  const { pushToast } = useDemoStore();

  useEffect(() => {
    setDone(confirmed || !!loadCompletions()[activity.id]);
  }, [activity.id, confirmed]);

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
        onComplete={(c) => {
          // Optimistic client store keeps the row "Confirmed" instantly + across
          // reloads; the server action records it durably, audits it, and hands
          // the Salesforce ID to IA for verification.
          saveCompletion(c);
          setDone(true);
          startConfirm(async () => {
            const res = await confirmActivityCompletion({
              activityId:       c.activityId,
              activityType:     activity.activityType,
              schoolName:       activity.schoolName,
              salesforceId:     c.salesforceId,
              salesforceIdKind: c.salesforceIdKind,
              teachers:         c.participants?.teachers,
              leaders:          c.participants?.schoolLeaders,
            });
            if (!res.ok) {
              pushToast({
                tone: "warning",
                title: "Completion not recorded",
                body: res.reason === "FORBIDDEN" ? "Your role can't confirm this completion." : "Check the Salesforce ID and try again.",
              });
            }
          });
        }}
      />
    </>
  );
}

"use client";

// "Bump" control for an overdue, unscheduled partner activity. Sends a
// reminder via remindPartnerToSchedule, then settles into a "Reminded" pill.

import { useState, useTransition } from "react";
import { BellRing, Check, Loader2 } from "lucide-react";
import { useDemoStore } from "@/components/demo/DemoStore";
import { remindPartnerToSchedule, type RemindPartnerInput } from "@/lib/actions/partner-reminder-actions";

export function BumpPartnerButton(props: RemindPartnerInput) {
  const [done, setDone] = useState(false);
  const [isPending, startTransition] = useTransition();
  const { pushToast } = useDemoStore();

  function bump() {
    startTransition(async () => {
      const res = await remindPartnerToSchedule(props);
      if (res.ok) {
        setDone(true);
        pushToast({ tone: "success", title: "Reminder sent", body: `${res.sentTo} was nudged to schedule ${props.schoolName}.` });
      } else {
        pushToast({ tone: "warning", title: "Not permitted", body: "Only account owners and leadership can bump partners." });
      }
    });
  }

  if (done) {
    return (
      <span className="inline-flex items-center gap-1 text-[10px] font-bold text-emerald-700 whitespace-nowrap">
        <Check size={11} /> Reminded
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={bump}
      disabled={isPending}
      className="inline-flex items-center gap-1 h-7 px-2 rounded-md border border-amber-200 bg-amber-50 text-amber-800 text-[10.5px] font-bold hover:bg-amber-100 disabled:opacity-50 whitespace-nowrap"
    >
      {isPending ? <Loader2 size={11} className="animate-spin" /> : <BellRing size={11} />}
      Bump
    </button>
  );
}

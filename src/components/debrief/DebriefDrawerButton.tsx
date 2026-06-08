"use client";

// A self-contained trigger + drawer pair. Drop it anywhere a user should be
// able to file the daily debrief (Today command center, My Plan, dashboard
// promoter card, header). Opening is local state — no global wiring needed.

import { useState } from "react";
import { ArrowRight, ClipboardList } from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { DailyDebriefDrawer } from "./DailyDebriefDrawer";

export function DebriefDrawerButton({
  label = "Submit Debrief",
  variant = "primary",
  debriefType = "staff",
  partnerId,
  className,
}: {
  label?: string;
  variant?: "primary" | "subtle";
  debriefType?: "staff" | "partner";
  partnerId?: string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const router = useRouter();
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "h-10 px-4 rounded-xl text-body font-extrabold inline-flex items-center justify-center gap-1.5",
          variant === "primary"
            ? "bg-emerald-600 hover:bg-emerald-500 text-white shadow-sm shadow-emerald-500/25"
            : "border border-[var(--color-edify-border)] hover:bg-slate-50 text-slate-700",
          className,
        )}
      >
        {variant === "subtle" && <ClipboardList size={14} />}
        {label}
        {variant === "primary" && <ArrowRight size={13} />}
      </button>
      <DailyDebriefDrawer
        open={open}
        onClose={() => setOpen(false)}
        debriefType={debriefType}
        partnerId={partnerId}
        // The realtime provider refreshes dashboards on the emitted event; also
        // refresh here so the promoter card flips to "submitted" immediately.
        onSubmitted={() => router.refresh()}
      />
    </>
  );
}

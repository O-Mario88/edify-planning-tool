"use client";

// IA Duplicate Review Queue — resolve flagged (never blocked) school duplicates.
//
// Each flag shows the newly-uploaded school, the existing school it resembles,
// the match score + band, and the explained reasons. IA decides: "Not a
// duplicate" (dismiss) or "Confirm duplicate" (acknowledge for follow-up).
// Nothing is auto-deleted or auto-merged — both schools stay live.

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Check, X, AlertTriangle, ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";
import { resolveDuplicate } from "@/lib/actions/intake-actions";

export type DuplicateFlagLite = {
  id: string;
  schoolId: string;
  schoolName: string;
  matchSchoolId: string;
  matchSchoolName: string;
  score: number;
  band: "Strong" | "Potential" | "None";
  reasons: string[];
  flaggedAt: string;
  flaggedBy: string;
};

export function DuplicateReviewQueue({ flags }: { flags: DuplicateFlagLite[] }) {
  if (flags.length === 0) {
    return (
      <section className="card p-6 text-center">
        <Check className="mx-auto text-emerald-600" size={28} />
        <h2 className="text-[13px] font-extrabold tracking-tight mt-2">No open duplicate flags</h2>
        <p className="text-[11.5px] muted max-w-md mx-auto mt-1">
          Every uploaded school has been checked against the roster. New look-alikes are flagged here for review —
          they&apos;re never blocked or auto-deleted.
        </p>
      </section>
    );
  }
  return (
    <div className="flex flex-col gap-2.5">
      {flags.map((f) => (
        <DuplicateCard key={f.id} flag={f} />
      ))}
    </div>
  );
}

const BAND_TONE = {
  Strong:    "bg-rose-100   text-rose-700",
  Potential: "bg-amber-100  text-amber-700",
  None:      "bg-slate-100  text-slate-600",
} as const;

function DuplicateCard({ flag }: { flag: DuplicateFlagLite }) {
  const router = useRouter();
  const [pending, start] = useTransition();
  const [msg, setMsg] = useState<string | null>(null);

  function resolve(status: "Dismissed" | "Confirmed") {
    setMsg(null);
    start(async () => {
      const res = await resolveDuplicate(flag.id, status);
      if (res.ok) {
        setMsg(status === "Dismissed" ? "Dismissed — kept as a distinct school." : "Confirmed as a duplicate.");
        router.refresh();
      } else if (res.reason === "FORBIDDEN") {
        setMsg("You don't have permission to resolve duplicates.");
      } else {
        setMsg("That flag was already resolved.");
      }
    });
  }

  return (
    <article className="card p-3.5">
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <AlertTriangle size={15} className={cn(flag.band === "Strong" ? "text-rose-600" : "text-amber-600")} />
          <span className={cn("inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold", BAND_TONE[flag.band])}>
            {flag.band} match · {flag.score}
          </span>
        </div>
        <span className="text-[10.5px] muted">flagged {flag.flaggedAt} · {flag.flaggedBy}</span>
      </div>

      {/* The two schools side by side. */}
      <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto_1fr] items-center gap-2">
        <div className="rounded-lg border border-[var(--color-edify-divider)] p-2.5">
          <div className="text-[10px] font-extrabold uppercase tracking-wide muted">Newly uploaded</div>
          <div className="text-body font-extrabold tracking-tight truncate">{flag.schoolName}</div>
          <div className="text-caption muted">ID {flag.schoolId}</div>
        </div>
        <ArrowRight size={16} className="mx-auto text-[var(--color-edify-muted)] hidden sm:block" />
        <div className="rounded-lg border border-[var(--color-edify-divider)] p-2.5">
          <div className="text-[10px] font-extrabold uppercase tracking-wide muted">Existing school</div>
          <div className="text-body font-extrabold tracking-tight truncate">{flag.matchSchoolName}</div>
          <div className="text-caption muted">ID {flag.matchSchoolId}</div>
        </div>
      </div>

      {flag.reasons.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1">
          {flag.reasons.map((r, i) => (
            <li key={i} className="inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-semibold bg-[var(--color-edify-soft)]/70 text-[var(--color-edify-text)]">
              {r}
            </li>
          ))}
        </ul>
      )}

      <div className="flex items-center justify-between gap-2 mt-3 pt-2.5 border-t border-[var(--color-edify-divider)]">
        <span className="text-[11px] muted truncate">{msg}</span>
        <div className="flex items-center gap-2 shrink-0">
          <Button variant="ghost" size="sm" Icon={X} onClick={() => resolve("Dismissed")} disabled={pending}>
            Not a duplicate
          </Button>
          <Button variant="primary" size="sm" Icon={Check} onClick={() => resolve("Confirmed")} disabled={pending}>
            {pending ? "Saving…" : "Confirm duplicate"}
          </Button>
        </div>
      </div>
    </article>
  );
}

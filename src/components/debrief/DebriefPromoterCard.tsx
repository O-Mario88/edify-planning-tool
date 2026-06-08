// DebriefPromoterCard — server-rendered card that mounts on every
// landing page where a CCEO / PL / Partner is expected to file a daily
// debrief. Shows status (not submitted / submitted / acknowledged) and
// a one-tap CTA to the form.
//
// Today this reads from a mock helper (`todaysDebriefStatusFor`) so the
// card has real-looking state. The next phase swaps the helper for a
// persistence layer without touching the card.

import Link from "next/link";
import { CheckCircle2, ClipboardList, Eye } from "lucide-react";
import { DebriefDrawerButton } from "./DebriefDrawerButton";
import {
  subtitleForRole,
  titleForRole,
} from "@/lib/debrief/prompts";
import type { DebriefStatus, DebriefSubmitterRole } from "@/lib/debrief/types";

type PromoterState =
  | { kind: "not-submitted" }
  | { kind: "submitted";    submittedAt: string; status: DebriefStatus; reviewer?: string }
  | { kind: "acknowledged"; submittedAt: string; reviewer: string };

export function DebriefPromoterCard({
  submitterRole,
  state,
}: {
  submitterRole: DebriefSubmitterRole;
  /** When omitted, defaults to a "not submitted" prompt — useful while
   *  the persistence layer isn't wired yet. */
  state?:        PromoterState;
}) {
  const s = state ?? { kind: "not-submitted" as const };
  const title    = titleForRole(submitterRole);
  const subtitle = subtitleForRole(submitterRole);

  return (
    <article className="card p-3.5 lg:p-5 flex items-start gap-4 flex-wrap lg:flex-nowrap">
      <span className="h-10 w-10 rounded-xl bg-emerald-50 text-emerald-700 grid place-items-center shrink-0">
        <ClipboardList size={18} />
      </span>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <h3 className="text-body-lg font-extrabold tracking-tight">{title}</h3>
          <StatusBadge state={s} />
        </div>
        <p className="text-[12px] muted mt-1 leading-snug max-w-[640px]">{subtitle}</p>
        {s.kind === "submitted" && (
          <p className="text-[11.5px] muted mt-1.5">
            Submitted at <span className="font-semibold text-[var(--color-edify-text)]">{s.submittedAt}</span>
            {s.reviewer ? <> · awaiting <span className="font-semibold text-[var(--color-edify-text)]">{s.reviewer}</span></> : null}
          </p>
        )}
        {s.kind === "acknowledged" && (
          <p className="text-[11.5px] muted mt-1.5">
            Acknowledged by <span className="font-semibold text-[var(--color-edify-text)]">{s.reviewer}</span> · submitted at <span className="font-semibold">{s.submittedAt}</span>
          </p>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0 w-full lg:w-auto">
        {s.kind === "not-submitted" ? (
          // Opens the floating Daily Debrief drawer (backend-submitting), not a
          // separate page. Partner roles file a partner debrief that routes to
          // their responsible CCEO first.
          <DebriefDrawerButton
            className="w-full lg:w-auto"
            debriefType={submitterRole === "Partner" ? "partner" : "staff"}
          />
        ) : (
          <Link
            href="/debriefs"
            className="h-10 w-full lg:w-auto px-4 rounded-xl border border-[var(--color-edify-border)] bg-white text-body font-semibold inline-flex items-center justify-center gap-1.5 hover:bg-[var(--color-edify-soft)]/60"
          >
            <Eye size={13} className="text-[var(--color-edify-muted)]" />
            View debrief
          </Link>
        )}
      </div>
    </article>
  );
}

function StatusBadge({ state }: { state: PromoterState }) {
  if (state.kind === "not-submitted") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-amber-50 border border-amber-200 text-amber-800 text-caption font-extrabold uppercase tracking-wider">
        Not submitted
      </span>
    );
  }
  if (state.kind === "submitted") {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-blue-50 border border-blue-200 text-blue-800 text-caption font-extrabold uppercase tracking-wider">
        {state.status}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 text-caption font-extrabold uppercase tracking-wider">
      <CheckCircle2 size={11} />
      Acknowledged
    </span>
  );
}

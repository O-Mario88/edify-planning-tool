"use client";

import { CheckCircle2, Inbox, Search } from "lucide-react";
import type { ListFilterKey } from "@/lib/messages-v2/access";

const COPY: Record<ListFilterKey, { headline: string; sub: string }> = {
  all:             { headline: "You're all clear.",                      sub: "No messages need your attention." },
  unread:          { headline: "All caught up.",                          sub: "No unread messages." },
  action_required: { headline: "No action-required messages right now.",  sub: "We'll surface anything that needs you here." },
  urgent:          { headline: "No urgent messages.",                     sub: "If anything critical comes in, you'll see it first." },
  debriefs:        { headline: "No debriefs in your inbox.",              sub: "Field and partner debriefs routed to you appear here." },
  evidence:        { headline: "No evidence messages.",                   sub: "Review notes and corrections will show up here." },
  payments:        { headline: "No payment messages.",                    sub: "Payment updates and finance notes appear here." },
  planning:        { headline: "No planning messages.",                   sub: "Scheduling and assignment notes appear here." },
  partner:         { headline: "No partner messages.",                    sub: "Notes from partner staff or about partner work appear here." },
  school_followup: { headline: "No school follow-up messages.",           sub: "Follow-Up notes from CCEOs and clusters appear here." },
  resolved:        { headline: "No resolved messages yet.",               sub: "Messages you've resolved will appear here." },
  archived:        { headline: "Nothing in the archive.",                 sub: "Archived messages appear here." },
};

export function MessageEmptyState({ filter, hasQuery = false }: { filter: ListFilterKey; hasQuery?: boolean }) {
  if (hasQuery) {
    return (
      <div className="px-6 py-10 text-center">
        <div className="mx-auto h-10 w-10 rounded-full bg-[var(--color-edify-soft)]/60 grid place-items-center text-[var(--color-edify-muted)]">
          <Search size={16} />
        </div>
        <h4 className="text-[13px] font-extrabold tracking-tight mt-3">No matches</h4>
        <p className="text-[11.5px] text-[var(--color-edify-muted)] mt-1 max-w-[260px] mx-auto leading-snug">
          Try a different sender, school, or keyword.
        </p>
      </div>
    );
  }
  const copy = COPY[filter];
  const Icon = filter === "all" || filter === "unread" ? CheckCircle2 : Inbox;
  return (
    <div className="px-6 py-12 text-center">
      <div className="mx-auto h-12 w-12 rounded-full bg-emerald-50 grid place-items-center text-emerald-700">
        <Icon size={20} />
      </div>
      <h4 className="text-body-lg font-extrabold tracking-tight mt-3">{copy.headline}</h4>
      <p className="text-[12px] text-[var(--color-edify-muted)] mt-1 max-w-[280px] mx-auto leading-snug">
        {copy.sub}
      </p>
    </div>
  );
}

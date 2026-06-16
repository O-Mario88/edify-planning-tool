// CommandStack — the unified "Today" rail.
//
// Pinned layout (per spec: actions BEFORE the role's KPI/chart content):
//   1. MissionHeader        — full-width hero (suppressed when the page
//                             already renders DashboardHero above us)
//   2. NextThreeActionsRow  — the three highest-leverage actions
//   3. Today rail           — ONE card containing:
//                               • left 8 cols: Action Inbox (tabs + bulk)
//                               • right 4 cols: Since-you-last-looked +
//                                 Done-for-today, stacked, divided by
//                                 a soft rule (NOT separate cards)
//
// The rail used to render those three pieces as three separate stacked
// cards. The eye walked a long uniform column and the dashboard read
// "assembled," not "intentional." The single-rail composition is the
// big perceptual lift: density up, hierarchy clear, all functionality
// preserved.
//
// Why this layout: actions come BEFORE everything else on the page.
// The role-specific dashboard content (KPI strips, charts, tables)
// renders BELOW so the user always sees "what to do next" before they
// see "the data behind it." Spec rule.
//
// Embedded mode: each child accepts `embedded` to drop its own card
// chrome. The rail owns the outer surface; children become sub-blocks.

import { cookies } from "next/headers";
import { Inbox } from "lucide-react";
import type { DemoUser } from "@/lib/auth";
import { buildRoleActionBoard } from "@/lib/actions/role-action-engine";
import { MissionHeader } from "./MissionHeader";
import { NextThreeActionsRow } from "./NextThreeActionsRow";
import { ChangedSinceCard } from "./ChangedSinceCard";
import { DoneForTodayChecklist } from "./DoneForTodayChecklist";
import { UnifiedInbox } from "./UnifiedInbox";
import { CollapsibleCard } from "@/components/ui/CollapsibleCard";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

export async function CommandStack({
  user,
  /** When the page already renders a DashboardHero above this stack,
   *  set `hideMission` so the duplicate greeting/quote doesn't repeat.
   *  The actions, change digest, done list, and inbox still render. */
  hideMission = false,
}: {
  user:         DemoUser;
  hideMission?: boolean;
}) {
  // The action rail (next-3 actions, inbox, change digest) is built from the
  // mock role-action engine, not the backend. In production render an empty
  // state instead — the page's own greeting hero still welcomes the user.
  if (!isMockAllowed()) {
    return (
      <div className="space-y-4">
        <InsufficientData surface="your action queue" />
      </div>
    );
  }
  // Read the last-viewed cookie. Pass the raw header into the engine
  // so it stays pure (no Next.js coupling in the engine).
  const jar = await cookies();
  const cookieHeader = jar.getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const board = buildRoleActionBoard({
    role: user.role,
    name: user.name,
    email: user.email,
    cookieHeader,
  });

  const inboxOpen = board.inbox.filter((i) =>
    i.inboxTab === "NeedsApproval" || i.inboxTab === "NeedsReview"
  ).length;

  return (
    <div className="space-y-4">
      {!hideMission && <MissionHeader header={board.header} />}
      <NextThreeActionsRow items={board.nextThree} />

      {/* Today rail — one collapsible card, two columns. Folds to its
          header (with the live counts in `meta`) to de-crowd the page. */}
      <CollapsibleCard
        id="today-queue"
        tier="strategic"
        eyebrow="Today"
        title={hideMission ? "Your Queue" : `${user.name.split(" ")[0]}'s queue`}
        description="Everything that needs you, what changed while you were gone, and what's left to clear today."
        icon={
          <span className="w-9 h-9 rounded-xl bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] grid place-items-center">
            <Inbox size={16} />
          </span>
        }
        meta={
          <span className="t-caption text-secondary tabular">
            {inboxOpen} open · {board.changedSince.length} changes · {board.doneToday.filter((d) => d.done).length}/{board.doneToday.length} done
          </span>
        }
      >
        <div className="grid grid-cols-12 gap-6">
          {/* Primary surface — the inbox where work happens. The tabs
              are the inbox's own self-label; no title row needed. */}
          <div className="col-span-12 lg:col-span-8">
            <UnifiedInbox items={board.inbox} embedded />
          </div>

          {/* Right rail — context (what changed) + closeout (done list).
              Separated by a soft rule so they read as paired sub-blocks
              of one surface, not two more cards. Each child renders its
              own micro-title + count meta in embedded mode. */}
          <aside className="col-span-12 lg:col-span-4 lg:border-l lg:border-[var(--color-edify-divider)] lg:pl-6">
            <ChangedSinceCard entries={board.changedSince} embedded />
            <div className="my-5 h-px bg-[var(--color-edify-divider)]" />
            <DoneForTodayChecklist items={board.doneToday} embedded />
          </aside>
        </div>
      </CollapsibleCard>
    </div>
  );
}

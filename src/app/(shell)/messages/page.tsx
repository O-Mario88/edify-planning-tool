// /messages — Inbox + Sent for every internal role (CCEO / PL / CD /
// RVP / HR / IA / Accountant / Admin). The same MessageCenterLayout
// the partner inbox uses; the access layer filters per-user so each
// role sees only what's addressed to them.
//
// Phase 2 migration note: this replaces the legacy chat-bubble thread
// model that lived in `lib/messages-mock.ts`. The legacy file is now
// orphaned and can be deleted in the next pass.

import Link from "next/link";
import { redirect } from "next/navigation";
import { PenSquare } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { MessageCenterLayout } from "@/components/messages/MessageCenterLayout";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { messagesForUser, type MessageFolder } from "@/lib/messages-v2/access";

// Internal roles only — partners read their own surface at
// /partner/messages. Anyone outside this set bounces to their role's
// landing page.
const ALLOWED = new Set([
  "CCEO",
  "CountryProgramLead",
  "CountryDirector",
  "RVP",
  "HumanResource",
  "ProgramAccountant",
  "ImpactAssessment",
  "Admin",
]);

export default async function MessagesPage({
  searchParams,
}: {
  searchParams: Promise<{ folder?: string }>;
}) {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect(ROLE_REDIRECT[user.role]);

  const params = await searchParams;
  const folder: MessageFolder = params.folder === "sent" ? "sent" : "inbox";
  const messages = messagesForUser(user, folder);

  return (
    <>
      <PageHeader
        title="Messages"
        subtitle="Internal communication — feedback, decisions, debriefs routed to you, and program coordination. Stays in the app."
        backFallbackHref="/dashboard"
      />
      <div className="px-4 sm:px-5 lg:px-6 pt-2 pb-12 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <FolderTabs current={folder} />
          <Link
            href="/messages/new"
            className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-body font-extrabold shadow-[0_1px_2px_rgba(15,23,32,0.06)] whitespace-nowrap"
          >
            <PenSquare size={13} />
            New message
          </Link>
        </div>
        <MessageCenterLayout
          messages={messages}
          role={user.role}
          detailHrefBase="/messages"
        />
      </div>
    </>
  );
}

function FolderTabs({ current }: { current: MessageFolder }) {
  return (
    <nav className="inline-flex items-center rounded-lg bg-[var(--color-edify-soft)]/60 p-0.5">
      {(["inbox", "sent"] as const).map((f) => {
        const isActive = current === f;
        return (
          <Link
            key={f}
            href={f === "inbox" ? "/messages" : "/messages?folder=sent"}
            className={
              "h-8 px-3.5 rounded-md text-[12px] font-semibold transition-colors capitalize " +
              (isActive
                ? "bg-white text-[var(--color-edify-text)] shadow-[0_1px_2px_rgba(15,23,32,0.06)]"
                : "text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]")
            }
          >
            {f === "inbox" ? "Inbox" : "Sent"}
          </Link>
        );
      })}
    </nav>
  );
}

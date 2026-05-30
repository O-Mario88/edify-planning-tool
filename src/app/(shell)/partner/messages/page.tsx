// /partner/messages — Inbox + Sent.
//
// Reads through the unified messages-v2 store and renders the shared
// MessageCenterLayout. Folder toggles via ?folder=inbox|sent. New
// message button routes to /partner/messages/new.

import Link from "next/link";
import { redirect } from "next/navigation";
import { PenSquare } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { MessageCenterLayout } from "@/components/messages/MessageCenterLayout";
import { messagesForUser, type MessageFolder } from "@/lib/messages-v2/access";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerMessagesPage({
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
      <PartnerSubPageHeader
        title="Messages"
        subtitle="Edify-to-partner communication — feedback, reminders, and coordination from your focal CCEO, Program Lead, and M&amp;E."
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <FolderTabs current={folder} />
          <Link
            href="/partner/messages/new"
            className="inline-flex items-center gap-1.5 h-9 px-3.5 rounded-lg bg-[var(--color-edify-primary)] hover:bg-[var(--color-edify-dark)] text-white text-body font-extrabold shadow-[0_1px_2px_rgba(15,23,32,0.06)] whitespace-nowrap"
          >
            <PenSquare size={13} />
            New message
          </Link>
        </div>
        <MessageCenterLayout
          messages={messages}
          role={user.role}
          detailHrefBase="/partner/messages"
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
            href={f === "inbox" ? "/partner/messages" : "/partner/messages?folder=sent"}
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

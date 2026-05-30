import { notFound, redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { MessageDetailPage } from "@/components/messages/MessageDetailPage";
import { messageByIdForUser } from "@/lib/messages-v2/access";
import { threadMessages } from "@/lib/messages-v2/mock";
import { replyMessageAction } from "../new/actions";
import { markReadOnView } from "@/app/(shell)/messages/[id]/status-actions";

// /partner/messages/[id] — Spark-Mail-style thread reader.

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerMessageDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect(ROLE_REDIRECT[user.role]);

  const { id } = await params;
  const message = messageByIdForUser(id, user);
  if (!message) return notFound();

  // Read the full thread so the page can render parent + replies in
  // one continuous reading surface (Spark-Mail-style). The permission
  // check above gates access to the parent — child messages in the
  // same thread are visible to the same participants by construction.
  const thread = threadMessages(message.threadId);

  // Auto mark-as-read for every message in the thread the user can
  // see. Idempotent — only flips status for recipients still in
  // `unread`. The mutator handles already-read recipients as no-op.
  for (const m of thread) {
    await markReadOnView(m.id);
  }

  return (
    <MessageDetailPage
      thread={thread}
      role={user.role}
      backHref="/partner/messages"
      backLabel="Messages"
      replyAction={replyMessageAction}
    />
  );
}

import { notFound, redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PageHeader } from "@/components/ui/PageHeader";
import { MessageDetailPage } from "@/components/messages/MessageDetailPage";
import { messageByIdForUser } from "@/lib/messages-v2/access";
import { threadMessages } from "@/lib/messages-v2/mock";
import { replyMessageAction } from "../new/actions";

// /messages/[id] — Spark-Mail-style thread reader for internal roles.
// Mirrors the partner detail page; the difference is just the back
// route + the role gate.

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

export default async function MessageDetailRoute({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect(ROLE_REDIRECT[user.role]);

  const { id } = await params;
  const message = messageByIdForUser(id, user);
  if (!message) return notFound();

  const thread = threadMessages(message.threadId);

  // Auto mark-as-read used to happen here, but Next.js 15 disallows
  // `revalidatePath` during render and the mutation pattern leaked
  // into the render path.  Read-state now updates through the explicit
  // user actions (Mark read / Acknowledge / Mark Resolved) on the
  // MessageActionBar — those are form-action server actions, which
  // run outside the render context and revalidate safely.

  return (
    <>
      {/* Canonical page chrome first; the reader below keeps its own
          sticky thread toolbar (back + category) for in-thread nav.
          Mounted here (not inside MessageDetailPage) because the same
          component serves the partner route with different chrome. */}
      <PageHeader
        title="Message"
        backFallbackHref="/messages"
        breadcrumbTrailingLabel={message.subject}
      />
      <MessageDetailPage
        thread={thread}
        role={user.role}
        backHref="/messages"
        backLabel="Messages"
        replyAction={replyMessageAction}
      />
    </>
  );
}

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PageHeader } from "@/components/ui/PageHeader";
import { LiveThread } from "@/components/messages/LiveThread";

// /messages/[id] — backend-wired thread reader for internal roles.
// [id] is a THREAD id: the backend resolves /messages/thread/:id (and reply)
// by thread id, so the same id drives the LiveThread fetch + reply. The mock
// thread store is gone — LiveThread reads the live backend, the same source the
// bell drawer + live inbox use.

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

  return (
    <>
      <PageHeader
        title="Message"
        backFallbackHref="/messages"
        breadcrumbTrailingLabel="Conversation"
      />
      <LiveThread threadId={id} />
    </>
  );
}

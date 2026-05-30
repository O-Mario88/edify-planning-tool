import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui/PageHeader";
import { MessageCompose } from "@/components/messages/MessageCompose";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { sendMessageAction } from "./actions";

// /partner/messages/new — new internal message composer.

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerNewMessagePage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect(ROLE_REDIRECT[user.role]);

  return (
    <>
      <PageHeader
        title="New message"
        subtitle="Send a message to any Edify staff or partner you're allowed to reach. Internal — stays in the app."
        backFallbackHref="/partner/messages"
      />
      <div className="px-4 sm:px-5 lg:px-6 pb-24 lg:pb-12">
        <MessageCompose
          senderRole={user.role}
          senderName={user.name}
          senderEmail={user.email}
          backHref="/partner/messages"
          sendAction={sendMessageAction}
        />
      </div>
    </>
  );
}

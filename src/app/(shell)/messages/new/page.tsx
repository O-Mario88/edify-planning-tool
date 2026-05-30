import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui/PageHeader";
import { MessageCompose } from "@/components/messages/MessageCompose";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { sendMessageAction } from "./actions";

// /messages/new — internal message composer for every internal role.

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

export default async function NewMessagePage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect(ROLE_REDIRECT[user.role]);

  return (
    <>
      <PageHeader
        title="New message"
        subtitle="Send a message to any Edify staff or partner you're allowed to reach. Internal — stays in the app."
        backFallbackHref="/messages"
      />
      <div className="px-4 sm:px-5 lg:px-6 pb-24 lg:pb-12">
        <MessageCompose
          senderRole={user.role}
          senderName={user.name}
          senderEmail={user.email}
          backHref="/messages"
          sendAction={sendMessageAction}
        />
      </div>
    </>
  );
}

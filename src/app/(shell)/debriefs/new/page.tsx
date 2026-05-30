import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui/PageHeader";
import { DebriefForm } from "@/components/debrief/DebriefForm";
import { getCurrentUser } from "@/lib/auth";
import { submitterRoleFor } from "@/lib/debrief/types";

// /debriefs/new — single canonical entry point for filing a debrief.
// The submitter variant is inferred from the signed-in user's role.
// Roles that don't file debriefs (CD / HR / RVP / IA / Accountant) get
// bounced back to /debriefs (the review index).
export default async function NewDebriefPage() {
  const user = await getCurrentUser();
  const role = submitterRoleFor(user.role);
  if (!role) redirect("/debriefs");

  return (
    <>
      <PageHeader
        title="Submit Debrief"
        subtitle="A short, honest read of what really happened today. We use this to support staff and improve programs — never to punish."
        backFallbackHref="/dashboard"
      />
      <div className="px-4 sm:px-5 lg:px-6 pb-24 lg:pb-10 max-w-[920px]">
        <DebriefForm submitterRole={role} submitterName={user.name} />
      </div>
    </>
  );
}

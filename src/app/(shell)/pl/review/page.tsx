import { redirect } from "next/navigation";
import { StubPage } from "@/components/shell/StubPage";
import { PlReviewQueue } from "@/components/pl/PlReviewQueue";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { isBackendEnabled } from "@/lib/api/backend";
import { InsufficientData } from "@/components/ui/InsufficientData";

const ALLOWED = new Set(["CountryProgramLead", "CountryDirector", "Admin"]);

export default async function PlReviewPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect(ROLE_REDIRECT[user.role]);

  return (
    <StubPage
      title="Completion review"
      subtitle="CCEO field completions awaiting your confirmation before IA verification."
    >
      {isBackendEnabled() ? <PlReviewQueue /> : <InsufficientData surface="PL completion review" />}
    </StubPage>
  );
}

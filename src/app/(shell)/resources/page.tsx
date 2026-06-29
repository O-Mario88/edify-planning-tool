import { StubPage } from "@/components/shell/StubPage";
export const revalidate = 60;
import { getCurrentUser } from "@/lib/auth";
import { ResourcesView } from "@/components/resources/ResourcesView";

// Resources hub.
//
// Three role-gated categories:
//   • Field Guides       — uploaded by Country Director (CD)
//   • Policies           — uploaded by Country Director (CD)
//   • Training Material  — uploaded by CCEO, IA, PL, or CD
//
// Anyone with shell access can READ everything. Upload buttons appear
// only for the categories the signed-in role is allowed to contribute
// to. Uploaded files persist client-side (localStorage) so demos hold
// across reloads; the future server backend will swap `resources-store`
// for an API client without touching this page.
export default async function ResourcesPage() {
  const user = await getCurrentUser();

  return (
    <StubPage
      title="Resources"
      subtitle="Field guides + policies are maintained by the Country Director. Training material is contributed by CCEOs, Impact Assessment, Program Leads, and the Country Director."
    >
      <ResourcesView role={user.role} userName={user.name} />
    </StubPage>
  );
}

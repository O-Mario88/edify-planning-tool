import { redirect } from "next/navigation";

// My Plan is now integrated into the Planning Tool — the "My Plan" ownership
// sections (Assigned to Me / Assigned to Partner / Awaiting Partner Schedule /
// Planned This Month) render inside /planning via <PlanningOwnershipSections>.
// This route redirects so old links/bookmarks land on the integrated tool.
export default function Page() {
  redirect("/planning");
}

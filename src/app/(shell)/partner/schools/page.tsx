// /partner/schools — Assigned Schools.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { MySchoolsGrid } from "@/components/partner/MySchoolsGrid";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerSchoolsPage({
  searchParams,
}: {
  searchParams: Promise<{ preview?: string }>;
}) {
  const user = await getCurrentUser();
  const params = await searchParams;
  const previewMode = process.env.NODE_ENV !== "production" && params.preview === "1";
  if (!previewMode && !ALLOWED.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  return (
    <>
      <PartnerSubPageHeader
        title="Assigned Schools"
        subtitle="The 24 schools across Mukono and Kayunga where your work is changing what schools can do for their pupils."
        filters={[
          { iconKey: "calendar", label: "All districts" },
          { iconKey: "filter",   label: "All SSA areas" },
        ]}
        kpis={[
          { label: "Schools assigned",  value: 24, iconKey: "building",  tone: "neutral", caption: "Across 2 districts"      },
          { label: "SSA-weak (≤ 5/10)", value: 8,  iconKey: "alert-oct", tone: "danger",  caption: "Need urgent support"      },
          { label: "Active activities", value: 18, iconKey: "activity",  tone: "good",    caption: "In flight right now"      },
          { label: "Improving",         value: 6,  iconKey: "trending",  tone: "good",    caption: "Score moved up this month" },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12">
        <MySchoolsGrid />
      </div>
    </>
  );
}

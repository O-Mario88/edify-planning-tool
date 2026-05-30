// /planning/core-schools — Core School Planning Console
//
// SSA-driven, gap-driven page for the 4×4 core support cycle. The page
// composes a sub-page header (with a back link to /planning), then hands
// off to <CoreSchoolsBoard /> which owns assign + toast state.

import Link from "next/link";
import { ArrowLeft, Calendar, MapPin, User, GraduationCap, Filter } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { CoreSchoolsBoard } from "@/components/planning/CoreSchoolsBoard";

export default function Page() {
  return (
    <>
      <PageHeader
        title="Core School Planning Console"
        subtitle="Every core school flows through SSA → 4 priority interventions → 4 visits + 4 trainings → follow-up SSA. This page shows where each school is stuck."
        Icon={GraduationCap}
        filters={[
          { Icon: Calendar, label: "FY26" },
          { Icon: MapPin,   label: "Region: Central" },
          { Icon: User,     label: "CCEO: All" },
          { Icon: Filter,   label: "Stage: All" },
        ]}
        searchPlaceholder="Search core schools"
      />
      <div className="px-4 sm:px-5 md:px-6">
        <Link
          href="/planning"
          className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-[var(--color-edify-muted)] hover:text-[var(--color-edify-text)]"
        >
          <ArrowLeft size={12} />
          Back to Planning Console
        </Link>
      </div>

      <div className="px-4 sm:px-5 md:px-6 pb-24 md:pb-8 pt-4">
        <CoreSchoolsBoard />
      </div>
    </>
  );
}

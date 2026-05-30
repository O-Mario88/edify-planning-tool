// /partner/impact — Impact Measurement.
//
// Did the school improve in the SSA intervention area the partner
// supported? This page connects partner activity directly to the
// next SSA result — baseline → activity → evidence → CCEO confirm →
// M&E verify → next SSA → delta → attribution.

import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { ROLE_REDIRECT } from "@/lib/auth-public";
import { PartnerSubPageHeader } from "@/components/partner/PartnerSubPageHeader";
import { PartnerImpactByArea } from "@/components/partner/PartnerImpactByArea";
import { PartnerImpactRecordsList } from "@/components/partner/PartnerImpactRecordsList";
import { partnerImpactRecords, summarise } from "@/lib/partner/partner-impact";

const ALLOWED = new Set([
  "PartnerAdmin", "PartnerFieldOfficer", "PartnerViewer", "Admin",
]);

export default async function PartnerImpactPage({
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

  const s = summarise(partnerImpactRecords);
  return (
    <>
      <PartnerSubPageHeader
        title="Impact Measurement"
        subtitle="Did the school improve in the SSA intervention area you supported? Baseline SSA → partner activity → evidence → next SSA → delta. Honest attribution, school-by-school."
        kpis={[
          { label: "Schools supported",  value: s.schoolsSupported,        iconKey: "building",  tone: "neutral", caption: "This impact window" },
          { label: "Improved",           value: s.schoolsImproved,         iconKey: "trending",  tone: "good",    caption: `${s.movedBandUpCount} moved up a band` },
          { label: "Avg SSA change",     value: s.avgChange > 0 ? `+${s.avgChange}` : s.avgChange.toFixed(1), iconKey: "sparkles", tone: s.avgChange > 0 ? "good" : "warn", caption: `Across ${s.schoolsWithNextSsa} measured` },
          { label: "Awaiting next SSA",  value: s.schoolsAwaiting,         iconKey: "clock",     tone: "warn",    caption: "In impact window" },
        ]}
      />
      <div className="px-4 sm:px-5 md:px-6 pt-5 pb-12 space-y-4">
        {/* Mini summary banner — turns abstract counts into a story */}
        <section className="card p-3.5 sm:p-5">
          <p className="text-[13.5px] sm:text-body-lg text-[var(--color-edify-text)] leading-relaxed max-w-[78ch]">
            Of <span className="font-extrabold">{s.schoolsSupported} schools</span> your team supported this
            window, <span className="font-extrabold">{s.schoolsWithNextSsa}</span> have completed a next SSA.
            <span className="font-extrabold text-emerald-700"> {s.schoolsImproved} improved</span>{" "}
            in the intervention area you worked on (
            <span className="font-extrabold">{s.strongImprovementCount} strong improvement</span>,{" "}
            <span className="font-extrabold">{s.movedBandUpCount} moved up a performance band</span>).{" "}
            {s.schoolsNoChange > 0 && <><span className="font-extrabold">{s.schoolsNoChange} stayed at the same score</span>; </>}
            {s.schoolsDeclined > 0 && <><span className="font-extrabold text-rose-700">{s.schoolsDeclined} declined</span> — review the records list for the recommended next decision. </>}
            The remaining <span className="font-extrabold">{s.schoolsAwaiting}</span> are inside the impact window
            and awaiting the next SSA.
          </p>
        </section>

        <PartnerImpactByArea />
        <PartnerImpactRecordsList />
      </div>
    </>
  );
}

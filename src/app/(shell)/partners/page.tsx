import { Handshake } from "lucide-react";
import { EntityIndex } from "@/components/shell/EntityIndex";
import { PartnersIndexClient } from "@/components/partners/PartnersIndexClient";
import { CceoPartnerWorkSection } from "@/components/partners/CceoPartnerWorkSection";
import { partnerTargetPerformance } from "@/lib/team-targets-mock";
import { getCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Partners index.
//
// Read access is open to everyone with shell access. ADD/EDIT is
// limited to:
//   • ImpactAssessment (M&E sets up the partnership + verifies scope)
//   • CountryDirector  (signs off on partner canon for the country)
//   • Admin            (system fallback)
//
// Each partner record carries the topics they train on — surfaced as
// chips on both the seed delivery partners and any new partners that
// IA/CD/Admin onboard through the form.
export default async function PartnersIndex({
  searchParams,
}: {
  searchParams: Promise<{ bucket?: string }>;
}) {
  const user = await getCurrentUser();
  const { bucket } = await searchParams;
  // "Established Delivery Partners" shows fabricated partners with invented
  // activity counts. Withhold until backed by real Partner records.
  if (!isMockAllowed()) return <InsufficientData surface="partners" />;
  const seedCount = partnerTargetPerformance.length;

  return (
    <EntityIndex
      title="Partners"
      Icon={Handshake}
      count={seedCount}
      searchPlaceholder="Search partners"
    >
      {/* CCEO-only: partner-work monitor (spec §15) — the six buckets
          from the shared engine, deep-linkable via ?bucket=<key> from
          the dashboard card's count strip. Other roles see the plain
          index unchanged. */}
      {user.role === "CCEO" && (
        <CceoPartnerWorkSection
          user={{ name: user.name, role: user.role, staffId: user.staffId }}
          initialBucket={bucket}
        />
      )}

      <PartnersIndexClient role={user.role} userName={user.name} />

      {/* Context note — moved to the foot of the page so the list leads. */}
      <p className="text-[11.5px] muted leading-relaxed pt-1">
        Delivery partners executing schools, trainings, and projects under Edify oversight. Each partner record
        carries the topics they train on.
      </p>
    </EntityIndex>
  );
}

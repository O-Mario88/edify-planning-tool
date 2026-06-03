import { TitleRegister } from "@/components/shell/TitleRegister";
import { PartnerClustersView } from "@/components/cluster/PartnerClustersView";
import { getCurrentPartner } from "@/lib/partner/partner-identity";

// Partner → "My Clusters". The clusters a CCEO has delegated to this partner to
// manage; the partner schedules cluster meetings here. Edify staff still run
// their own activities on the same clusters (shown as "Edify" meetings).
export default async function PartnerClustersPage() {
  const partner = await getCurrentPartner();

  return (
    <>
      <TitleRegister title="My Clusters" dateLabel="Partner" />
      <div className="px-4 sm:px-5 md:px-6 pt-4 pb-12 space-y-4">
        <header>
          <h1 className="text-[18px] font-extrabold tracking-tight">Clusters I manage</h1>
          <p className="text-[12.5px] muted mt-0.5 max-w-2xl">
            Clusters delegated to {partner?.name ?? "your organisation"} to manage. Schedule cluster meetings and
            School Improvement Training here. Account ownership stays with the assigning staff member.
          </p>
        </header>
        {partner ? (
          <PartnerClustersView partnerId={partner.id} />
        ) : (
          <div className="card rounded-2xl p-8 text-center text-[12.5px] muted">
            Sign in with a partner account to see clusters delegated to you.
          </div>
        )}
      </div>
    </>
  );
}

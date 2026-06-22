import { redirect } from "next/navigation";
import { ResponsiveDashboard } from "@/components/mobile/ResponsiveDashboard";
import { RoleBottomNav } from "@/components/mobile/RoleBottomNav";
import { MonthlyFundRequestView } from "@/components/funds/monthly-fund-request/MonthlyFundRequestView";
import { MonthlyFundRequestPageHeader } from "@/components/funds/monthly-fund-request/MonthlyFundRequestPageHeader";
import type { MfrViewerRole } from "@/components/funds/monthly-fund-request/MonthlyFundRequestHeader";
import { generateMonthlyFundRequest } from "@/lib/funds/monthly-fund-request-mock";
import { mfrStatus } from "@/lib/funds/mfr-status-store";
import { getCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { MonthlyFundRequestLive } from "@/components/funds/monthly-fund-request/MonthlyFundRequestLive";
import { ROLE_REDIRECT, type EdifyRole } from "@/lib/auth-public";

// Monthly Fund Request page.
//
// One country, one month. Auto-generated from approved monthly plans,
// reviewed by PL, augmented + approved by CD, then routed to RVP.
// Each role sees the same artefact through a different lens via the
// `viewerRole` prop:
//
//   • PL  — review program lines, return draft if needed, submit to CD
//   • CD  — review, add admin items, approve & submit to RVP
//   • RVP — sees ONLY CD-approved requests; approve / return / hold
//   • Accountant — prepares disbursement after RVP approval
//
// Middleware also restricts the route to these roles; the redirect
// below is defense-in-depth.

const ALLOWED: ReadonlySet<EdifyRole> = new Set([
  "CountryProgramLead",
  "CountryDirector",
  "RVP",
  "ProgramAccountant",
  "Admin",
]);

const ROLE_VIEW: Record<string, MfrViewerRole> = {
  CountryProgramLead: "PL",
  CountryDirector:    "CD",
  RVP:                "RVP",
  ProgramAccountant:  "Accountant",
  Admin:              "CD",
};

export default async function MonthlyFundRequestPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) {
    redirect(ROLE_REDIRECT[user.role]);
  }
  // The monthly country fund request is a hardcoded April-2026 mock artifact
  // (fabricated grand total, wrong period). Money for approval must be real —
  // withhold until derived from backend FundRequest + budget lines.
  if (!isMockAllowed()) {
    const body = (
      <>
        <MonthlyFundRequestPageHeader
          monthLabel={new Date().toLocaleString("en", { month: "long", year: "numeric" })}
          countryName="Uganda"
        />
        <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 pt-3 space-y-3 lg:space-y-4">
          <MonthlyFundRequestLive />
        </div>
        <RoleBottomNav />
      </>
    );
    return <ResponsiveDashboard mobile={body} desktop={body} />;
  }

  const viewerRole: MfrViewerRole = ROLE_VIEW[user.role] ?? "PL";

  // Computed fresh each render so CD admin-item edits (which mutate the
  // server-side overlay) flow into the budget rollup + grand total.
  const currentMonthlyFundRequest = generateMonthlyFundRequest();

  // The artifact carries one real, shared status that the approval-chain
  // actions advance (PL→CD→RVP→Accountant). We read the persisted status;
  // if it's never been acted on this session it starts at the chain head so
  // the full chain can be walked by acting as each role in order.
  const persistedStatus = mfrStatus(currentMonthlyFundRequest.id);
  const initial = {
    ...currentMonthlyFundRequest,
    status: persistedStatus ?? "UNDER_PL_REVIEW",
  };

  const body = (
    <>
      {/* Canonical page chrome: title + subtitle + search + bell +
          messages + avatar. Pulled in to match /approvals, /core-schools
          etc. so the MFR page reads with the same edge-to-edge header. */}
      <MonthlyFundRequestPageHeader
        monthLabel={initial.monthLabel}
        countryName={initial.countryName}
      />

      <div className="px-3 sm:px-4 lg:px-6 pb-24 lg:pb-6 pt-3 space-y-3 lg:space-y-4">
        <MonthlyFundRequestView initial={initial} viewerRole={viewerRole} />
      </div>
      <RoleBottomNav />
    </>
  );

  return <ResponsiveDashboard mobile={body} desktop={body} />;
}

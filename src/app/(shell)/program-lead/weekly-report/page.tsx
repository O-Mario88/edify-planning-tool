import { redirect } from "next/navigation";
import { PageHeader } from "@/components/ui/PageHeader";
import { ProgramLeadWeeklyReportEditor } from "@/components/field-intelligence/ProgramLeadWeeklyReportEditor";
import { getCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { programLeadWeeklyFieldReports } from "@/lib/field-intelligence-mock";

// Program Lead weekly report editor.
// Visibility: only Program Leads (or Admin masquerading) reach the editor.
// CCEOs, CD, RVP, IA, HR, Accountant, SPC do NOT see this page.

const ALLOWED = new Set(["CountryProgramLead", "Admin"]);

export default async function ProgramLeadWeeklyReportEditorPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect("/dashboard");

  // The editor opens a pre-filled, hand-mocked report (auto-filled team activity,
  // debriefs, achievement, barriers) — no live weekly-report backend. Never show a
  // PL a report pre-populated with fabricated figures they would submit as real.
  if (!isMockAllowed()) {
    return (
      <>
        <PageHeader
          title="Weekly Field Report Editor"
          subtitle="The system auto-fills team activity, debriefs, achievement, and barriers from your CCEOs' daily debriefs. You add the weekly reflection before submitting to the Country Director."
          backFallbackHref="/dashboard"
        />
        <div className="px-4 sm:px-5 md:px-6 pt-2 pb-10 md:pb-6">
          <InsufficientData surface="the weekly field report editor" detail="The auto-filled weekly report is withheld until the weekly-report backend is wired — no fabricated team activity, achievement, or barrier figures are pre-populated." />
        </div>
      </>
    );
  }

  // For the demo we open the editor for the PL's most recent report.
  // Production: lookup by (plId, current weekId).
  const myReport =
    programLeadWeeklyFieldReports.find((r) => r.programLeadName === user.name) ??
    programLeadWeeklyFieldReports[0];

  return (
    <>
      <PageHeader
        title="Weekly Field Report Editor"
        titleBadge={
          <span className="px-2 py-[2px] rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] text-[10px] font-bold uppercase tracking-wider whitespace-nowrap">
            Program Lead workspace
          </span>
        }
        subtitle="The system auto-fills team activity, debriefs submitted, raw/adjusted achievement, and barriers from your CCEOs' daily debriefs. You add the weekly reflection and confirm the decisions list before submitting to the Country Director."
        backFallbackHref="/dashboard"
      />
      <div className="px-4 sm:px-5 md:px-6 pt-2 pb-10 md:pb-6">
        <ProgramLeadWeeklyReportEditor r={myReport} />
      </div>
    </>
  );
}

import { redirect } from "next/navigation";
import { ProgramLeadWeeklyReportEditor } from "@/components/field-intelligence/ProgramLeadWeeklyReportEditor";
import { getCurrentUser } from "@/lib/auth";
import { programLeadWeeklyFieldReports } from "@/lib/field-intelligence-mock";

// Program Lead weekly report editor.
// Visibility: only Program Leads (or Admin masquerading) reach the editor.
// CCEOs, CD, RVP, IA, HR, Accountant, SPC do NOT see this page.

const ALLOWED = new Set(["CountryProgramLead", "Admin"]);

export default async function ProgramLeadWeeklyReportEditorPage() {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect("/dashboard");

  // For the demo we open the editor for the PL's most recent report.
  // Production: lookup by (plId, current weekId).
  const myReport =
    programLeadWeeklyFieldReports.find((r) => r.programLeadName === user.name) ??
    programLeadWeeklyFieldReports[0];

  return (
    <>
      <header className="pl-16 pr-4 pt-5 lg:pl-6 lg:pr-6 pb-4">
          <div className="text-[11px] muted font-bold uppercase tracking-wider">Program Lead workspace</div>
          <h1 className="page-title mt-0.5">
            Weekly Field Report Editor
          </h1>
          <p className="text-body muted mt-0.5 max-w-[760px]">
            The system auto-fills team activity, debriefs submitted, raw/adjusted achievement, and barriers from your CCEOs&apos; daily debriefs. You add the weekly reflection and confirm the decisions list before submitting to the Country Director.
          </p>
        </header>

        <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6">
          <ProgramLeadWeeklyReportEditor r={myReport} />
        </div>
      </>
  );
}

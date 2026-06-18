import Link from "next/link";
import { redirect, notFound } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { ProgramLeadWeeklyReportRenderer } from "@/components/field-intelligence/ProgramLeadWeeklyReportRenderer";
import { getCurrentUser } from "@/lib/auth";
import { isMockAllowed } from "@/lib/mock-policy";
import { InsufficientData } from "@/components/ui/InsufficientData";
import { programLeadWeeklyFieldReportById, reportEventLog } from "@/lib/field-intelligence-mock";

const ALLOWED = new Set(["CountryDirector", "Admin"]);

export default async function ProgramLeadWeeklyReportPage(props: { params: Promise<{ id: string }> }) {
  const user = await getCurrentUser();
  if (!ALLOWED.has(user.role)) redirect("/dashboard");

  // Fabricated weekly report (named PL, achievement figures, decisions) — no live
  // weekly-report backend. Withhold rather than render invented leadership data.
  if (!isMockAllowed()) {
    return (
      <>
        <header className="pl-16 pr-4 pt-5 lg:pl-6 lg:pr-6 pb-2">
          <Link
            href="/dashboards/director/weekly-debrief-reports"
            className="inline-flex items-center gap-1 text-[12px] font-extrabold text-[var(--color-edify-primary)] hover:underline"
          >
            <ChevronLeft size={12} />
            Back to report center
          </Link>
        </header>
        <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6">
          <InsufficientData surface="this weekly field report" detail="The Program-Lead weekly field report is withheld until the weekly-report backend is wired — no fabricated named report is shown." />
        </div>
      </>
    );
  }

  const { id } = await props.params;
  const report = programLeadWeeklyFieldReportById(id);
  if (!report) notFound();

  return (
    <>
      <header className="pl-16 pr-4 pt-5 lg:pl-6 lg:pr-6 pb-2">
          <Link
            href="/dashboards/director/weekly-debrief-reports"
            className="inline-flex items-center gap-1 text-[12px] font-extrabold text-[var(--color-edify-primary)] hover:underline"
          >
            <ChevronLeft size={12} />
            Back to report center
          </Link>
        </header>

        <div className="px-4 sm:px-5 md:px-6 pb-10 md:pb-6">
          <ProgramLeadWeeklyReportRenderer
            r={report}
            initialEvents={reportEventLog[report.id] ?? []}
            viewerRole={user.role}
            viewerName={user.name}
          />
        </div>
      </>
  );
}

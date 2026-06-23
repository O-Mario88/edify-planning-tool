import type { EdifyRole } from "@/lib/auth-public";
import type { BeBudgetBoard } from "@/lib/api/surfaces";
import { BudgetTemplateDashboard } from "./BudgetTemplateDashboard";

const SUBTITLES: Partial<Record<EdifyRole, string>> = {
  CountryDirector:
    "Country-wide budget intelligence — approve PL/IA/Accountant plans, add admin costs, escalate to RVP.",
  ProgramAccountant:
    "Treasury view of the country budget — scheduled activities costed from the Country Cost Register.",
  ImpactAssessment:
    "Country budget overview — IA can plan activities for any school; costs roll up here.",
  RVP:
    "Consolidated country summary — CD-approved plans awaiting your final sign-off.",
  CountryProgramLead:
    "Your team budget — CCEO fund requests you approve, plus your own plan and requests.",
  CCEO:
    "Your plan budget only — each activity costed from the catalogue; submit to your PL for approval.",
  Admin: "Full country budget template — all roles and categories.",
};

export function BudgetTemplateView({
  data,
  role,
}: {
  data: Omit<BeBudgetBoard, "live">;
  role: EdifyRole;
}) {
  return (
    <BudgetTemplateDashboard
      initial={data}
      role={role}
      subtitle={SUBTITLES[role]}
      compact={false}
    />
  );
}

import { Lock } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { CostSettingsCard } from "@/components/budget/CostSettingsCard";
import { activeFinancialYear } from "@/lib/fy-engine";
import { getCurrentUser } from "@/lib/auth";

export default async function CountryCostSettingsPage() {
  const me = await getCurrentUser();
  const fy = activeFinancialYear();

  // Role gate: only Country Director / Admin / Program Accountant view this in
  // full. The card itself is backend-driven (GET/POST /api/budget/cost-settings)
  // and the backend enforces the CD-only write (COST_SETTINGS_MANAGE) — this gate
  // controls who sees the register at all.
  const allowed = ["CountryDirector", "Admin", "ProgramAccountant"].includes(me.role);

  return (
    <StubPage
      title="Country Cost Settings"
      subtitle={`Unit costs for ${fy.label}. The Annual Budget Builder uses these prices for every formula. Final budget approval is BLOCKED if any required cost item is missing.`}
    >
      {!allowed && (
        <section className="card p-3.5 border-amber-200 bg-amber-50/60">
          <div className="flex items-start gap-3">
            <Lock size={18} className="text-amber-700 mt-1" />
            <div>
              <h2 className="text-[13px] font-extrabold tracking-tight">Read-only view</h2>
              <p className="text-[11.5px] muted">
                Only the Country Director, Admin, or Program Accountant may view this page in full. Your role
                is <span className="font-extrabold">{me.role}</span>. The cost register below is omitted.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Live, backend-driven CD rate card: create / edit-with-reason / version / history. */}
      {allowed && <CostSettingsCard />}

      {/* Role gate explainer */}
      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Role contract: </span>
        Only the Country Director (or Admin) may activate / approve cost settings.
        Program Accountant has read + draft-edit access. RVP reviews — does not edit.
        CCEOs and Program Leads cannot see this page. Every rate change bumps the
        version and lands in the audit history; approved plans keep the version they
        were approved against.
      </section>
    </StubPage>
  );
}

import { AlertTriangle, CheckCircle2, Lock } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { ActionButton } from "@/components/ui/ActionButton";
import {
  countryCostSettings,
  validateCountryCostSettings,
  formatUgxBig,
} from "@/lib/cost-settings-mock";
import { activeFinancialYear } from "@/lib/fy-engine";
import { getCurrentUser } from "@/lib/auth";
import { cn } from "@/lib/utils";

export default async function CountryCostSettingsPage() {
  const me     = await getCurrentUser();
  const fy     = activeFinancialYear();
  const verdict= validateCountryCostSettings();

  // Role gate: only Country Director / Admin / Program Accountant view this.
  const allowed = ["CountryDirector", "Admin", "ProgramAccountant"].includes(me.role);
  const canEdit = ["CountryDirector", "Admin"].includes(me.role);

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
                is <span className="font-extrabold">{me.role}</span>. The full register below is omitted.
              </p>
            </div>
          </div>
        </section>
      )}

      {/* Verdict */}
      <section className={cn(
        "card p-3.5 flex items-start gap-3",
        verdict.ready ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50",
      )}>
        <span className={cn(
          "h-10 w-10 rounded-xl grid place-items-center shrink-0",
          verdict.ready ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-700",
        )}>
          {verdict.ready ? <CheckCircle2 size={18} /> : <AlertTriangle size={18} />}
        </span>
        <div className="flex-1 min-w-0">
          <h2 className="text-body-lg font-extrabold tracking-tight">
            {verdict.ready ? "All required cost settings are Active" : "Cost settings incomplete"}
          </h2>
          <p className="text-[11.5px] muted">
            {verdict.active} of {verdict.total} cost items are Active for {fy.label}.
            {!verdict.ready && ` Budget approval is BLOCKED until the remaining ${verdict.missing.length} items become Active.`}
          </p>
          {!verdict.ready && (
            <ul className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-1 text-[11px]">
              {verdict.missing.map((m) => (
                <li key={m} className="inline-flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
                  {m}
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>

      {/* Settings table */}
      {allowed && (
        <section className="card p-3.5">
          <header className="flex items-baseline justify-between mb-2">
            <h2 className="text-body-lg font-extrabold tracking-tight">Country cost register — Uganda · {fy.label}</h2>
            <span className="text-caption muted">{countryCostSettings.length} cost items</span>
          </header>
          <div className="overflow-x-auto">
            <table className="w-full text-[12px] min-w-[820px]">
              <thead>
                <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                  <th scope="col" className="py-2 pr-2">Cost item</th>
                  <th scope="col" className="py-2 px-2 text-right">Unit cost</th>
                  <th scope="col" className="py-2 px-2">Currency</th>
                  <th scope="col" className="py-2 px-2">Effective from</th>
                  <th scope="col" className="py-2 px-2">Set by</th>
                  <th scope="col" className="py-2 px-2">Approved by</th>
                  <th scope="col" className="py-2 pl-2">Status</th>
                  {canEdit && <th scope="col" className="py-2 pl-2 text-right">Action</th>}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-edify-divider)]">
                {countryCostSettings.map((c) => (
                  <tr key={c.id} className="hover:bg-[var(--color-edify-soft)]/30">
                    <td className="py-2 pr-2 font-extrabold">{c.costItem}</td>
                    <td className="py-2 px-2 text-right tabular font-extrabold">{formatUgxBig(c.unitCost)}</td>
                    <td className="py-2 px-2">{c.currency}</td>
                    <td className="py-2 px-2 muted whitespace-nowrap">{c.effectiveFrom}</td>
                    <td className="py-2 px-2 muted">{c.setBy}</td>
                    <td className="py-2 px-2 muted">{c.approvedBy ?? "—"}</td>
                    <td className="py-2 pl-2">
                      <span className={cn(
                        "inline-flex items-center px-1.5 py-[2px] rounded-md text-[10px] font-extrabold whitespace-nowrap",
                        c.status === "Active"   && "bg-emerald-100 text-emerald-700",
                        c.status === "Draft"    && "bg-amber-100   text-amber-700",
                        c.status === "Archived" && "bg-slate-100   text-slate-700",
                      )}>{c.status}</span>
                    </td>
                    {canEdit && (
                      <td className="py-2 pl-2 text-right">
                        <ActionButton
                          label="Edit"
                          ariaLabel={`Edit cost setting for ${c.costItem}`}
                          className="text-[11px] font-semibold text-[var(--color-edify-primary)] hover:underline"
                          toast={{
                            tone: "info",
                            title: `Opened ${c.costItem} cost editor`,
                            body: "Rate edits propagate to new fund requests; existing approved plans keep the rate at approval time.",
                          }}
                        />
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Role gate explainer */}
      <section className="card p-3.5 text-[11.5px] muted">
        <span className="font-extrabold text-[var(--color-edify-text)]">Role contract: </span>
        Only the Country Director (or Admin) may activate / approve cost settings.
        Program Accountant has read + draft-edit access. RVP reviews — does not edit.
        CCEOs and Program Leads cannot see this page.
      </section>
    </StubPage>
  );
}

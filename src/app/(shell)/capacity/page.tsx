import { ShieldAlert } from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { getCurrentUser } from "@/lib/auth";
import { DEMO_USERS } from "@/lib/auth";
import { computeStaffCapacity, teamCapacityRollup } from "@/lib/planning/assignment-policy";
import { isLimitExplicit } from "@/lib/planning/staff-capacity-store";
import { SetLimitForm } from "@/components/admin/SetLimitForm";
import { cn } from "@/lib/utils";

export const dynamic = "force-dynamic";

// Staff Support Capacity management (spec §12). CD / IA set how many schools each
// staff member can directly support; once at limit, new school support must go to
// a partner. Read-only for everyone else.
const FIELD_ROLES = new Set(["CCEO", "CountryProgramLead"]);
const CAN_SET = new Set(["CountryDirector", "ImpactAssessment", "Admin"]);

function Stat({ label, value, caption, tone }: { label: string; value: number | string; caption?: string; tone?: "alert" | "warn" | "good" | "default" }) {
  const v = tone === "alert" ? "text-rose-600" : tone === "warn" ? "text-amber-600" : tone === "good" ? "text-emerald-600" : "text-[var(--text-primary)]";
  return (
    <div className="card px-3 py-2.5">
      <div className="text-[10px] font-semibold muted leading-tight">{label}</div>
      <div className={cn("text-[18px] font-extrabold tabular leading-none mt-1", v)}>{value}</div>
      {caption && <div className="text-[9.5px] muted mt-0.5">{caption}</div>}
    </div>
  );
}

function statusOf(used: number, max: number, near: boolean): { label: string; tone: string } {
  if (used > max) return { label: "Over Limit · Review", tone: "bg-rose-100 text-rose-700" };
  if (used >= max) return { label: "At Limit", tone: "bg-amber-100 text-amber-700" };
  if (near) return { label: "Near Limit", tone: "bg-amber-50 text-amber-700" };
  return { label: "Under Capacity", tone: "bg-emerald-50 text-emerald-700" };
}

export default async function CapacityPage() {
  const user = await getCurrentUser();
  const canSet = CAN_SET.has(user.role);

  const staff = Object.values(DEMO_USERS)
    .filter((u) => FIELD_ROLES.has(u.role))
    .map((u) => {
      const cap = computeStaffCapacity(u.staffId);
      return { ...u, cap, status: statusOf(cap.used, cap.max, cap.nearLimit), explicit: isLimitExplicit(u.staffId) };
    })
    .sort((a, b) => b.cap.used / b.cap.max - a.cap.used / a.cap.max);

  const atOrOver = staff.filter((s) => s.cap.used >= s.cap.max).length;
  const rollup = teamCapacityRollup(staff.map((s) => s.staffId));

  return (
    <>
      <PageHeader
        title="Staff Support Capacity"
        subtitle={`How many schools each staff member can directly support this FY. At the limit, new school support shifts to partners. ${canSet ? "You can set limits." : "View only — only CD / IA can change limits."}`}
      />
      <div className="px-3 sm:px-4 md:px-6 pt-2 pb-24 space-y-4">
      {!canSet && (
        <div className="card p-3 flex items-center gap-2 text-[12px] text-amber-700 bg-amber-50 border-amber-200">
          <ShieldAlert size={14} /> Setting limits is restricted to Country Director and Impact Assessment.
        </div>
      )}

      {/* Capacity analytics (spec §22) — staff are capped, partners are NOT. */}
      <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2.5">
        <Stat label="Direct support used" value={`${rollup.totalUsed}/${rollup.totalCapacity}`} caption="across field staff" />
        <Stat label="Staff at limit" value={rollup.atLimit} tone={rollup.atLimit ? "alert" : "default"} />
        <Stat label="Staff near limit" value={rollup.nearLimit} tone={rollup.nearLimit ? "warn" : "default"} />
        <Stat label="Partner-supported schools" value={rollup.partnerSupportedSchools} caption="no support limit" tone="good" />
        <Stat label="Field staff" value={rollup.staffCount} />
      </section>

      <div className="card p-3 text-[11.5px] muted flex items-center gap-2">
        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 text-emerald-700 px-2 py-0.5 text-[10.5px] font-bold border border-emerald-200">Partners</span>
        Partners have <b className="text-[var(--color-edify-text)]">no school-support limit</b> — they absorb support when staff reach capacity. Only staff (CCEO / PL) are capped.
      </div>

      {atOrOver > 0 && (
        <div className="card p-3 text-[12px]"><b>{atOrOver}</b> staff at or over their direct-support limit — new school support for them should be assigned to partners.</div>
      )}

      <section className="card p-0 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
                <th className="py-2.5 px-3">Staff</th>
                <th className="py-2.5 px-3">Role</th>
                <th className="py-2.5 px-3 text-right">Used</th>
                <th className="py-2.5 px-3 text-right">Limit</th>
                <th className="py-2.5 px-3 text-right">Remaining</th>
                <th className="py-2.5 px-3">Status</th>
                {canSet && <th className="py-2.5 px-3">Set limit</th>}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-edify-divider)]">
              {staff.map((s) => (
                <tr key={s.staffId} className="hover:bg-[var(--color-edify-soft)]/30">
                  <td className="py-2.5 px-3"><div className="font-bold">{s.name}</div><div className="text-[10.5px] muted">{s.scope}</div></td>
                  <td className="py-2.5 px-3 muted">{s.role === "CountryProgramLead" ? "Program Lead" : s.role}</td>
                  <td className="py-2.5 px-3 text-right tabular font-bold">{s.cap.used}</td>
                  <td className="py-2.5 px-3 text-right tabular">{s.cap.max}{!s.explicit && <span className="text-[9.5px] muted"> (default)</span>}</td>
                  <td className="py-2.5 px-3 text-right tabular">{s.cap.remaining}</td>
                  <td className="py-2.5 px-3"><span className={cn("text-[10px] font-bold px-1.5 py-[2px] rounded-full", s.status.tone)}>{s.status.label}</span></td>
                  {canSet && <td className="py-2.5 px-3"><SetLimitForm staffId={s.staffId} current={s.cap.max} /></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      </div>
    </>
  );
}

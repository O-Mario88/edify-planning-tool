import Link from "next/link";
import { Gauge } from "lucide-react";
import { cceosSupervisedBy } from "@/lib/org/supervision";
import { computeStaffCapacity, partnerSupportedSchools } from "@/lib/planning/assignment-policy";
import { cn } from "@/lib/utils";

// PL team capacity — each supervised CCEO's direct-support usage vs their limit,
// so the PL sees who's at capacity (and whose new work should shift to partners).
function statusOf(used: number, max: number, near: boolean) {
  if (used > max) return { label: "Over · Review", tone: "bg-rose-100 text-rose-700" };
  if (used >= max) return { label: "At Limit", tone: "bg-amber-100 text-amber-700" };
  if (near) return { label: "Near Limit", tone: "bg-amber-50 text-amber-700" };
  return { label: "Under", tone: "bg-emerald-50 text-emerald-700" };
}

export function TeamCapacityCard({ plStaffId }: { plStaffId: string }) {
  const team = cceosSupervisedBy(plStaffId).map((c) => ({ ...c, cap: computeStaffCapacity(c.staffId) }));
  if (team.length === 0) return null;
  const atLimit = team.filter((t) => t.cap.used >= t.cap.max).length;
  const partner = partnerSupportedSchools();

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Gauge size={14} /> Team Support Capacity</h2>
        <Link href="/capacity" className="text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">Manage</Link>
      </header>

      <div className="flex items-center gap-3 mb-2 text-[11.5px]">
        <span><b className="tabular">{atLimit}</b> of {team.length} CCEOs at limit</span>
        <span className="muted">Partner-supported: <b className="text-[var(--color-edify-text)] tabular">{partner}</b> <span className="text-[10px]">(no limit)</span></span>
      </div>

      <div className="overflow-x-auto -mx-1">
        <table className="w-full text-[12px]">
          <thead><tr className="text-left text-caption muted font-semibold uppercase tracking-wide border-b border-[var(--color-edify-border)]">
            <th className="py-1.5 px-1">CCEO</th><th className="py-1.5 px-1 text-right">Used</th><th className="py-1.5 px-1 text-right">Limit</th><th className="py-1.5 px-1 text-right">Left</th><th className="py-1.5 px-1">Status</th>
          </tr></thead>
          <tbody className="divide-y divide-[var(--color-edify-divider)]">
            {team.map((t) => {
              const st = statusOf(t.cap.used, t.cap.max, t.cap.nearLimit);
              return (
                <tr key={t.staffId} className="hover:bg-[var(--color-edify-soft)]/30">
                  <td className="py-1.5 px-1 font-bold">{t.name}</td>
                  <td className="py-1.5 px-1 text-right tabular font-bold">{t.cap.used}</td>
                  <td className="py-1.5 px-1 text-right tabular">{t.cap.max}</td>
                  <td className="py-1.5 px-1 text-right tabular">{t.cap.remaining}</td>
                  <td className="py-1.5 px-1"><span className={cn("text-[10px] font-bold px-1.5 py-[2px] rounded-full", st.tone)}>{st.label}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

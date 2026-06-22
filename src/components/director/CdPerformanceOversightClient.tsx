"use client";

import Link from "next/link";
import { useState } from "react";
import { Filter, UserCog, Handshake, ArrowUpRight } from "lucide-react";
import { TargetsLive } from "@/components/targets/TargetsLive";
import { SupportImprovementCard } from "@/components/analytics/SupportImprovementCard";
import { ScheduleBudgetCard } from "@/components/budget/ScheduleBudgetCard";
import type { BePartner, BeRosterRow } from "@/lib/api/surfaces";

type Props = {
  staff: BeRosterRow[];
  partners: BePartner[];
};

export function CdPerformanceOversightClient({ staff, partners }: Props) {
  const fieldStaff = staff.filter((s) => s.role === "CCEO" || s.role === "CountryProgramLead");
  const [staffId, setStaffId] = useState(fieldStaff[0]?.staffProfileId ?? "");
  const selected = fieldStaff.find((s) => s.staffProfileId === staffId);

  return (
    <section className="space-y-4">
      <div className="card p-3.5">
        <header className="flex items-center justify-between gap-2 flex-wrap mb-3">
          <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5">
            <Filter size={14} /> Individual performance oversight
          </h2>
          <span className="text-[10px] font-bold muted">Monitor targets, SSA movement &amp; budget from team plans — no field planning</span>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
          <label className="text-[11px] muted">
            <span className="inline-flex items-center gap-1 font-semibold mb-1"><UserCog size={12} /> Staff member</span>
            <select
              value={staffId}
              onChange={(e) => setStaffId(e.target.value)}
              className="w-full rounded-lg border border-slate-200 bg-transparent px-2.5 py-1.5 text-sm dark:border-slate-700"
            >
              {fieldStaff.length === 0 && <option value="">No field staff on roster</option>}
              {fieldStaff.map((s) => (
                <option key={s.staffProfileId} value={s.staffProfileId}>
                  {s.name} · {s.role} · {s.primaryDistrict ?? "Unassigned"}
                </option>
              ))}
            </select>
          </label>
          <div className="text-[11px] muted flex flex-col justify-end gap-1">
            {selected && (
              <>
                <span>{selected.schools} schools · {selected.supervisees} supervisees</span>
                <Link
                  href={`/staff/${selected.staffProfileId}`}
                  className="inline-flex items-center gap-1 text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline"
                >
                  Full profile — visits, training &amp; SSA by intervention <ArrowUpRight size={11} />
                </Link>
              </>
            )}
          </div>
        </div>

        {staffId ? (
          <TargetsLive title={`Target achievement — ${selected?.name ?? "staff"}`} staffId={staffId} />
        ) : (
          <p className="text-[12px] muted">Select a staff member to view target achievement (visits, training, core support, SSA).</p>
        )}
      </div>

      <SupportImprovementCard />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <ScheduleBudgetCard />
        <div className="card p-3.5">
          <header className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide muted mb-2">
            <Handshake className="h-3.5 w-3.5" /> Partner delivery
          </header>
          {partners.length === 0 ? (
            <p className="text-[12px] muted">No active partners in scope.</p>
          ) : (
            <ul className="divide-y divide-[var(--color-edify-divider)]">
              {partners.slice(0, 6).map((p) => (
                <li key={p.id} className="flex items-center justify-between gap-2 py-2 text-[12px]">
                  <div className="min-w-0">
                    <div className="font-bold truncate">{p.name}</div>
                    <div className="text-[11px] muted truncate">{p.regionName ?? "—"} · {p.certificationStatus ?? (p.isCertified ? "Certified" : "Pending")}</div>
                  </div>
                  <Link href={`/partners/${p.id}`} className="shrink-0 text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">
                    Monitor →
                  </Link>
                </li>
              ))}
            </ul>
          )}
          <Link href="/partners" className="mt-2 inline-flex items-center gap-1 text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">
            All partners <ArrowUpRight size={11} />
          </Link>
        </div>
      </div>
    </section>
  );
}

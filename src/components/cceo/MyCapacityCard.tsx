import Link from "next/link";
import { Gauge, Handshake } from "lucide-react";
import { computeStaffCapacity, partnerSupportedSchools } from "@/lib/planning/assignment-policy";
import { fetchStaffCapacity } from "@/lib/api/surfaces";
import { getCurrentUser } from "@/lib/auth";
import { cn } from "@/lib/utils";

// CCEO "My Direct Support Capacity" — how many schools I directly support vs my
// CD/IA-set limit. Reads the BACKEND capacity when enabled (the enforced source),
// falling back to the in-memory store. At the limit, new support goes to partners.
export async function MyCapacityCard({ staffId }: { staffId: string }) {
  const user = await getCurrentUser();
  const be = await fetchStaffCapacity(user);
  const cap = be.live
    ? { used: be.data.used, max: be.data.max, remaining: be.data.remaining, nearLimit: be.data.nearLimit }
    : computeStaffCapacity(staffId);
  const partner = partnerSupportedSchools(staffId);
  const pct = cap.max ? Math.min(100, Math.round((cap.used / cap.max) * 100)) : 0;
  const barTone = cap.used >= cap.max ? "bg-rose-500" : cap.nearLimit ? "bg-amber-500" : "bg-emerald-500";

  return (
    <section className="card p-3.5">
      <header className="flex items-center justify-between gap-2 mb-2">
        <h2 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Gauge size={14} /> My Direct Support Capacity</h2>
        <Link href="/capacity" className="text-[11px] font-bold text-[var(--color-edify-primary)] hover:underline">View all</Link>
      </header>

      <div className="flex items-end justify-between gap-2 mb-1.5">
        <div><span className="text-[26px] font-extrabold tabular leading-none">{cap.used}</span><span className="text-[14px] muted font-bold"> / {cap.max}</span><span className="text-[11px] muted"> schools</span></div>
        <div className="text-right"><div className="text-[18px] font-extrabold tabular leading-none">{cap.remaining}</div><div className="text-[10px] muted">remaining</div></div>
      </div>
      <div className="h-2 rounded-full bg-[var(--color-edify-soft)] overflow-hidden"><div className={cn("h-full rounded-full", barTone)} style={{ width: `${pct}%` }} /></div>

      <div className="mt-2.5 flex items-center justify-between gap-2 text-[11.5px]">
        <span className="inline-flex items-center gap-1 muted"><Handshake size={12} /> Partner-supported: <b className="text-[var(--color-edify-text)]">{partner}</b> <span className="text-[10px]">(no limit)</span></span>
      </div>

      {cap.used >= cap.max ? (
        <p className="mt-2 text-[11.5px] text-rose-700">You've reached your direct support limit — assign new school support to a partner to keep schools moving without exceeding your workload.</p>
      ) : cap.nearLimit ? (
        <p className="mt-2 text-[11.5px] text-amber-700">You're near your direct support limit ({pct}%). Consider partner delivery for new schools.</p>
      ) : (
        <p className="mt-2 text-[11.5px] muted">Under capacity — you can take on {cap.remaining} more school{cap.remaining === 1 ? "" : "s"} directly.</p>
      )}
    </section>
  );
}

import { Handshake, BadgeCheck, MapPin } from "lucide-react";
import { getCurrentUser } from "@/lib/auth";
import { fetchPartners } from "@/lib/api/surfaces";
import { InsufficientData } from "@/components/ui/InsufficientData";

// Live partner directory — the real Partner records in the backend (the orgs
// staff can assign work to). Empty when no partners are onboarded yet; never a
// fabricated roster with invented activity counts.

export async function LivePartnersList() {
  const user = await getCurrentUser();
  const res = await fetchPartners(user, false);
  if (!res.live) return <InsufficientData surface="partners" />;
  const partners = res.data;

  if (partners.length === 0) {
    return (
      <section className="card p-6 text-center">
        <Handshake className="mx-auto mb-2 text-[var(--color-edify-muted)]" size={22} />
        <p className="text-[13px] font-extrabold tracking-tight">No partners onboarded yet</p>
        <p className="text-[12px] muted mt-1">
          Impact Assessment or the Country Director onboards delivery partners. Once a
          partner is added, it appears here and becomes assignable from the Assign Support flow.
        </p>
      </section>
    );
  }

  return (
    <section className="card p-0 overflow-hidden">
      <header className="px-4 py-3 border-b border-[var(--color-edify-divider)] flex items-center justify-between gap-2">
        <h3 className="text-[13px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><Handshake size={14} /> Delivery partners <span className="muted font-semibold">· {partners.length}</span></h3>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend</span>
      </header>
      <div className="divide-y divide-[var(--color-edify-divider)]">
        {partners.map((p) => (
          <div key={p.id} className="px-4 py-3 flex items-center justify-between gap-3 text-[12px]">
            <div className="min-w-0">
              <div className="font-extrabold tracking-tight inline-flex items-center gap-1.5 truncate">
                {p.name}
                {p.isCertified && <BadgeCheck size={13} className="text-emerald-600 shrink-0" />}
              </div>
              <div className="muted inline-flex items-center gap-2 flex-wrap mt-0.5">
                {p.regionName && <span className="inline-flex items-center gap-1"><MapPin size={11} /> {p.regionName}</span>}
                {p.expertiseAreas && p.expertiseAreas.length > 0 && <span>{p.expertiseAreas.slice(0, 3).join(" · ")}</span>}
              </div>
            </div>
            <span className={`inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-bold ${p.activeStatus ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
              {p.activeStatus ? "Active" : "Inactive"}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

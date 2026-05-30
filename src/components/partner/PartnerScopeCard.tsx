// PartnerScopeCard — surfaces the partner's contract scope so it's
// clear to every partner user (and any Edify staff who lands here)
// what's in-bounds and what isn't.

import { MapPin, CheckCircle2, Calendar, Layers } from "lucide-react";
import type { PartnerScope } from "@/lib/partner/partner-types";

export function PartnerScopeCard({ scopes }: { scopes: PartnerScope[] }) {
  if (scopes.length === 0) return null;
  return (
    <section className="card p-3.5">
      <header className="flex items-center gap-2 mb-3">
        <span className="w-6 h-6 rounded-md bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-primary)] grid place-items-center">
          <Layers size={13} />
        </span>
        <h3 className="text-[13px] font-extrabold tracking-tight">Partner scope</h3>
        <span className="ml-auto text-caption text-[var(--color-edify-muted)] font-bold uppercase tracking-wide">
          {scopes.length} contract{scopes.length === 1 ? "" : "s"}
        </span>
      </header>
      <p className="text-[12px] muted leading-snug">
        Activities outside this scope are rejected automatically. Edify focal can extend the scope on request.
      </p>
      <ul className="mt-3 space-y-3">
        {scopes.map((s) => (
          <li key={s.id} className="rounded-xl border border-[var(--color-edify-divider)] p-3">
            <div className="flex items-start gap-2">
              <span className="inline-flex items-center gap-1 px-1.5 py-[1.5px] rounded-md bg-emerald-50 text-emerald-700 border border-emerald-200 text-[10px] font-bold uppercase tracking-wide">
                <CheckCircle2 size={10} /> {s.status}
              </span>
              <div className="text-body font-extrabold leading-tight">{s.contractName}</div>
            </div>
            <div className="grid grid-cols-2 gap-2 mt-2">
              <Detail Icon={MapPin}  label="Districts"  value={s.districtIds.length > 0 ? s.districtIds.map(stripDst).join(" · ") : (s.schoolIds.length > 0 ? `${s.schoolIds.length} schools` : "—")} />
              <Detail Icon={Calendar} label="Window"    value={`${s.startDate.slice(0, 10)} → ${s.endDate.slice(0, 10)}`} />
            </div>
            <div className="mt-2">
              <div className="text-[10px] uppercase tracking-wide muted font-bold mb-1">Allowed activities</div>
              <div className="flex flex-wrap gap-1">
                {s.allowedActivityKinds.map((k) => (
                  <span key={k} className="inline-flex items-center px-1.5 py-[1.5px] rounded-md bg-[var(--color-edify-soft)]/60 text-[var(--color-edify-text)] text-caption font-semibold">
                    {humaniseKind(k)}
                  </span>
                ))}
              </div>
            </div>
            <div className="mt-2">
              <div className="text-[10px] uppercase tracking-wide muted font-bold mb-1">Intervention areas</div>
              <div className="flex flex-wrap gap-1">
                {s.interventionAreas.map((i) => (
                  <span key={i} className="inline-flex items-center px-1.5 py-[1.5px] rounded-md bg-violet-50 text-violet-800 text-caption font-semibold">
                    {humaniseIntervention(i)}
                  </span>
                ))}
              </div>
            </div>
            <div className="text-[11px] muted mt-2">
              Verification default: <span className="font-extrabold text-[var(--color-edify-text)]">{s.defaultVerificationLevel}</span>
              {" · "}Reports every {s.reportingFrequencyDays} days
              {" · "}Funding: <span className="font-extrabold text-[var(--color-edify-text)]">{humaniseFunding(s.fundingModel)}</span>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Detail({ Icon, label, value }: { Icon: typeof MapPin; label: string; value: string }) {
  return (
    <div>
      <div className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide muted font-bold">
        <Icon size={10} /> {label}
      </div>
      <div className="text-[11.5px] font-semibold text-[var(--color-edify-text)]">{value}</div>
    </div>
  );
}

function stripDst(d: string): string {
  return d.startsWith("DST-") ? d.slice(4) : d;
}

function humaniseKind(k: string): string {
  return k.replace(/([A-Z])/g, " $1").trim();
}

function humaniseIntervention(i: string): string {
  return i.replace(/([A-Z])/g, " $1").trim();
}

function humaniseFunding(f: string): string {
  return f.replace(/([A-Z])/g, " $1").trim();
}

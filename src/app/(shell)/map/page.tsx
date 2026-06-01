import Link from "next/link";
import { MapPin, Building2, Filter, Map as MapIcon } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { schoolsMock, distinctShippingAddresses } from "@/lib/schools-mock";
import { cn } from "@/lib/utils";

// Schools across the country, grouped by shipping hub. Until a real
// Leaflet/Mapbox layer is wired up, the top of the page is a subtle
// ambient banner — the hub list below is the primary surface.
//
// Hubs are derived from the school data itself rather than re-listed here,
// so there is no second copy of the shipping-address list to drift.
const HUBS = distinctShippingAddresses(schoolsMock);

export default function MapPage() {
  const totalSchools = schoolsMock.length;
  const completed    = schoolsMock.filter((s) => s.ssaStatus === "Completed").length;
  const overdue      = schoolsMock.filter((s) => s.ssaStatus === "Overdue").length;
  const inProgress   = totalSchools - completed - overdue;

  return (
    <StubPage
      title="Map View"
      subtitle="Schools across the country, grouped by shipping hub. A Leaflet/Mapbox layer drops in once geocoded school data is imported — for now, browse by hub below."
    >
      {/* KPI strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Schools mapped"  value={String(totalSchools)} tone="bg-violet-100  text-violet-700" />
        <Kpi label="SSA completed"   value={String(completed)}    tone="bg-emerald-100 text-emerald-700" />
        <Kpi label="In progress"     value={String(inProgress)}   tone="bg-amber-100   text-amber-700" />
        <Kpi label="SSA overdue"     value={String(overdue)}      tone="bg-rose-100    text-rose-700" />
      </section>

      {/* Ambient banner — real Leaflet/Mapbox view drops in once schools
          have geocoded coordinates. */}
      <section
        className="rounded-2xl border border-[var(--color-edify-border)] overflow-hidden bg-[linear-gradient(180deg,#eef4f7_0%,#dceaf1_100%)]"
        aria-label="Map placeholder"
      >
        <div className="h-24 flex items-center justify-center gap-3 px-4">
          <span className="h-10 w-10 rounded-xl bg-white/70 text-[var(--color-edify-primary)] grid place-items-center shrink-0">
            <MapIcon size={18} />
          </span>
          <div className="min-w-0">
            <div className="text-body font-extrabold tracking-tight">Interactive map coming soon</div>
            <div className="text-[11px] muted truncate">
              Hub coverage shown below — Leaflet / Mapbox layer drops in once geocoded school data is imported.
            </div>
          </div>
        </div>
      </section>

      {/* Hub-grouped list */}
      <section className="card p-3.5">
        <div className="flex items-center gap-2 flex-wrap mb-3">
          <button type="button" className="h-8 px-3 rounded-full border border-[var(--color-edify-border)] text-[12px] font-semibold inline-flex items-center gap-1.5 hover:bg-[var(--color-edify-soft)]/40">
            <Filter size={12} /> All districts
          </button>
          <button type="button" className="h-8 px-3 rounded-full border border-[var(--color-edify-border)] text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/40">All segments</button>
          <button type="button" className="h-8 px-3 rounded-full border border-[var(--color-edify-border)] text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/40">All SSA states</button>
          <span className="ml-auto text-[11.5px] muted">{totalSchools} schools across {HUBS.length} hubs</span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {HUBS.map((hub) => {
            const hubSchools = schoolsMock.filter((s) => s.shippingAddress === hub);
            if (hubSchools.length === 0) return null;
            return (
              <div key={hub} className="rounded-xl border border-[var(--color-edify-border)] p-3 bg-[var(--color-edify-soft)]/30">
                <div className="flex items-baseline justify-between mb-2">
                  <h3 className="text-body font-extrabold tracking-tight inline-flex items-center gap-1.5">
                    <MapPin size={12} className="text-[var(--color-edify-primary)]" />
                    {hub}
                  </h3>
                  <span className="text-caption muted">{hubSchools.length} schools</span>
                </div>
                <ul className="space-y-1">
                  {hubSchools.map((s) => {
                    const dotColor =
                      s.ssaStatus === "Completed" ? "#10b981" :
                      s.ssaStatus === "Overdue"   ? "#ef4444" :
                                                    "#f59e0b";
                    return (
                      <li key={s.schoolId}>
                        <Link
                          href={`/schools/${s.schoolId}`}
                          className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white"
                        >
                          <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: dotColor }} />
                          <Building2 size={12} className="text-[var(--color-edify-muted)] shrink-0" />
                          <span className="text-[12px] font-semibold truncate flex-1">{s.schoolName}</span>
                          <span className="text-caption muted tabular shrink-0">SSA {s.ssaScore}%</span>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      </section>
    </StubPage>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="card p-3.5">
      <div className="flex items-center gap-2 mb-2">
        <span className={cn("h-9 w-9 rounded-full grid place-items-center", tone)}>
          <MapPin size={14} />
        </span>
        <span className="text-[11.5px] muted font-semibold">{label}</span>
      </div>
      <div className="text-[24px] font-extrabold tabular leading-none">{value}</div>
    </div>
  );
}

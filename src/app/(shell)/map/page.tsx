import Link from "next/link";
import { MapPin, Building2, Filter } from "lucide-react";
import { StubPage } from "@/components/shell/StubPage";
import { schoolsMock, distinctShippingAddresses } from "@/lib/schools-mock";
import { cn } from "@/lib/utils";
import { isMockAllowed } from "@/lib/mock-policy";
import { ProductiveEmptyState } from "@/components/ui/ProductiveEmptyState";

// Schools across the country. The top is a library-free "coverage map": each
// school is a pin, anchored to its region's zone on an abstract canvas and
// coloured by SSA status. A geographic Leaflet/Mapbox layer can replace the
// canvas later once schools carry real lat/lng — the pin model + colours stay.
const HUBS = distinctShippingAddresses(schoolsMock);

// Region → anchor (% of canvas) roughly mirroring Uganda's layout.
const REGION_ANCHOR: Record<string, { x: number; y: number }> = {
  north:   { x: 50, y: 20 },
  central: { x: 49, y: 50 },
  east:    { x: 77, y: 56 },
  west:    { x: 23, y: 60 },
  other:   { x: 50, y: 50 },
};

function regionKey(region?: string): keyof typeof REGION_ANCHOR {
  const r = (region ?? "").toLowerCase();
  if (r.includes("north")) return "north";
  if (r.includes("east")) return "east";
  if (r.includes("west")) return "west";
  if (r.includes("central")) return "central";
  return "other";
}

// Deterministic 0..1 hash from a string (stable pin scatter, no Math.random).
function hash01(s: string, salt: number): number {
  let h = salt;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return (h % 1000) / 1000;
}

function ssaColor(status: string): string {
  return status === "Completed" ? "#10b981" : status === "Overdue" ? "#ef4444" : "#f59e0b";
}

export default function MapPage() {
  // The coverage map + SSA counts are not yet backed by live school records;
  // never show the mock universe as production data.
  if (!isMockAllowed())
    return (
      <ProductiveEmptyState
        Icon={MapPin}
        title="The coverage map isn't connected to live geography data yet"
        description="School pins and district coverage are withheld until they trace to live source records."
        actionLabel="Open Analytics"
        actionHref="/analytics"
        links={[{ label: "Schools", href: "/schools" }]}
        note="No fabricated pins are shown."
      />
    );
  const totalSchools = schoolsMock.length;
  const completed    = schoolsMock.filter((s) => s.ssaStatus === "Completed").length;
  const overdue      = schoolsMock.filter((s) => s.ssaStatus === "Overdue").length;
  const inProgress   = totalSchools - completed - overdue;

  // Render up to 160 pins for a clean canvas; counts above stay exact.
  const pins = schoolsMock.slice(0, 160).map((s) => {
    const a = REGION_ANCHOR[regionKey(s.region)];
    const jx = (hash01(s.schoolId, 7) - 0.5) * 30;   // ±15%
    const jy = (hash01(s.schoolId, 13) - 0.5) * 26;  // ±13%
    return {
      id: s.schoolId,
      name: s.schoolName,
      district: s.district,
      score: s.ssaScore,
      color: ssaColor(s.ssaStatus),
      x: Math.max(3, Math.min(97, a.x + jx)),
      y: Math.max(6, Math.min(94, a.y + jy)),
    };
  });

  return (
    <StubPage
      title="Map View"
      subtitle="Coverage across the country — every school as a pin, coloured by SSA status. Click a pin to open the school."
    >
      {/* KPI strip */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Schools mapped"  value={String(totalSchools)} tone="bg-violet-100  text-violet-700" />
        <Kpi label="SSA completed"   value={String(completed)}    tone="bg-emerald-100 text-emerald-700" />
        <Kpi label="In progress"     value={String(inProgress)}   tone="bg-amber-100   text-amber-700" />
        <Kpi label="SSA overdue"     value={String(overdue)}      tone="bg-rose-100    text-rose-700" />
      </section>

      {/* Coverage canvas — region-anchored pins. */}
      <section className="card p-0 overflow-hidden">
        <div className="flex items-center justify-between gap-2 px-3.5 py-2.5 border-b border-[var(--color-edify-divider)]">
          <h2 className="text-[12.5px] font-extrabold tracking-tight">Coverage map</h2>
          <div className="flex items-center gap-3 text-[10.5px] muted">
            <Legend color="#10b981" label="Completed" />
            <Legend color="#f59e0b" label="In progress" />
            <Legend color="#ef4444" label="Overdue" />
          </div>
        </div>
        <div
          className="relative w-full bg-[radial-gradient(120%_120%_at_50%_0%,#eef4f7_0%,#dceaf1_60%,#cfe0e9_100%)] dark:bg-[radial-gradient(120%_120%_at_50%_0%,rgba(30,45,60,0.6)_0%,rgba(16,26,38,0.8)_100%)]"
          style={{ aspectRatio: "16 / 8" }}
          aria-label={`Coverage map showing ${pins.length} of ${totalSchools} schools by region`}
        >
          {/* faint grid */}
          <div className="absolute inset-0 opacity-[0.5] [background-image:linear-gradient(to_right,rgba(0,0,0,0.04)_1px,transparent_1px),linear-gradient(to_bottom,rgba(0,0,0,0.04)_1px,transparent_1px)] [background-size:9%_12%]" aria-hidden />
          {/* region labels */}
          {(["north","central","east","west"] as const).map((k) => (
            <span key={k} className="absolute -translate-x-1/2 -translate-y-1/2 text-[9px] font-extrabold uppercase tracking-[0.14em] text-[var(--color-edify-muted)]/70 select-none"
              style={{ left: `${REGION_ANCHOR[k].x}%`, top: `${Math.max(4, REGION_ANCHOR[k].y - 17)}%` }} aria-hidden>
              {k === "north" ? "Northern" : k === "east" ? "Eastern" : k === "west" ? "Western" : "Central"}
            </span>
          ))}
          {/* pins */}
          {pins.map((p) => (
            <Link
              key={p.id}
              href={`/schools/${p.id}`}
              title={`${p.name} · ${p.district} · SSA ${p.score}%`}
              aria-label={`${p.name}, ${p.district}, SSA ${p.score} percent — open school`}
              className="absolute -translate-x-1/2 -translate-y-1/2 h-2.5 w-2.5 rounded-full ring-1 ring-white/80 shadow-[0_1px_2px_rgba(0,0,0,0.25)] hover:h-3.5 hover:w-3.5 hover:z-10 transition-all"
              style={{ left: `${p.x}%`, top: `${p.y}%`, backgroundColor: p.color }}
            />
          ))}
        </div>
        <div className="px-3.5 py-2 text-[10.5px] muted border-t border-[var(--color-edify-divider)]">
          Showing {pins.length} of {totalSchools} schools. Pin position is by region; a geocoded street-level layer drops in when lat/lng data is imported.
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
                  {hubSchools.map((s) => (
                    <li key={s.schoolId}>
                      <Link
                        href={`/schools/${s.schoolId}`}
                        className="flex items-center gap-2 px-2 py-1.5 rounded-md hover:bg-white"
                      >
                        <span className="h-2 w-2 rounded-full shrink-0" style={{ backgroundColor: ssaColor(s.ssaStatus) }} />
                        <Building2 size={12} className="text-[var(--color-edify-muted)] shrink-0" />
                        <span className="text-[12px] font-semibold truncate flex-1">{s.schoolName}</span>
                        <span className="text-caption muted tabular shrink-0">SSA {s.ssaScore}%</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      </section>
    </StubPage>
  );
}

function Legend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="h-2 w-2 rounded-full" style={{ backgroundColor: color }} /> {label}
    </span>
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

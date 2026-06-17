"use client";

// Uganda Geo-Analytics Map — a leadership intelligence surface, not decoration.
//
// Real district BOUNDARY geometry (COD-AB, simplified, /public/geo/districts.geojson)
// is joined by official pcode to LIVE per-district analytics (/api/analytics/geo-map,
// role-scoped + filter-aware). Renders as a themeable SVG with three layers:
//
//   • Choropleth  — districts coloured by a chosen metric (a rate or a count).
//   • Bubbles     — proportional symbols at district centroids: SIZE = school
//                   count, COLOUR = health status. Two channels, two metrics —
//                   "where is the work, and is it healthy there?" (the premium view).
//   • Pins        — EXACT school points, shown automatically the moment schools
//                   have uploaded coordinates (none → layer is simply empty).
//
// Hover → rich preview popover; click → full district analytics drawer; zoom/pan.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Map as MapIcon, ZoomIn, ZoomOut, Maximize2, X, ArrowRight, AlertTriangle, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { isFilterActive, useActiveFilters } from "@/hooks/use-active-filters";
import { ErrorState, LoadingState } from "@/components/ui/DataStates";
import { cn } from "@/lib/utils";
import type { BeGeoMap, BeGeoDistrict, BeGeoSchoolPoint } from "@/lib/api/surfaces";

type GeoFeature = { properties: { pcode: string; name: string; region: string }; geometry: { type: string; coordinates: number[][][] | number[][][][] } };
type GeoJson = { bbox: [number, number, number, number]; features: GeoFeature[] };

const METRICS: { key: keyof BeGeoDistrict; label: string; higherIsBetter: boolean; fmt?: (v: number) => string }[] = [
  { key: "schools", label: "Total Schools", higherIsBetter: true },
  { key: "coreSchools", label: "Core Schools", higherIsBetter: true },
  { key: "clientSchools", label: "Client Schools", higherIsBetter: true },
  { key: "clustered", label: "Clustered", higherIsBetter: true },
  { key: "avgSsa", label: "SSA Average", higherIsBetter: true, fmt: (v) => v.toFixed(1) },
  { key: "criticalCount", label: "Critical SSA Schools", higherIsBetter: false },
  { key: "ssaPending", label: "SSA Pending", higherIsBetter: false },
  { key: "activitiesCompleted", label: "Activities Completed", higherIsBetter: true },
];

const W = 1000;
const RAMP_GOOD = ["#e6f5f0", "#a7e8d2", "#5fd3ab", "#22b07f", "#0f7a57"];
const RAMP_BAD = ["#fde8e8", "#f9c2c2", "#f08a8a", "#dc4f4f", "#a82626"];
const NO_DATA = "var(--color-edify-soft)";

const STATUS_META: Record<BeGeoDistrict["status"], { label: string; cls: string; fill: string }> = {
  healthy: { label: "Healthy", cls: "bg-emerald-50 text-emerald-700 border-emerald-200", fill: "#22b07f" },
  needs_attention: { label: "Needs Attention", cls: "bg-amber-50 text-amber-700 border-amber-200", fill: "#f59e0b" },
  high_risk: { label: "High Risk", cls: "bg-rose-50 text-rose-700 border-rose-200", fill: "#e11d48" },
  insufficient_data: { label: "No SSA yet", cls: "bg-slate-100 text-slate-500 border-slate-200", fill: "#94a3b8" },
};
// Faint status tint for the choropleth underlay in Bubbles view.
const STATUS_TINT: Record<BeGeoDistrict["status"], string> = {
  healthy: "#eafaf3", needs_attention: "#fef6e7", high_risk: "#fdeef0", insufficient_data: "var(--color-edify-soft)",
};
const PIN_FILL: Record<string, string> = { core: "#0f7a57", client: "#0284c7", potential_core: "#7c3aed" };

function geoQs(sel: ReturnType<typeof useActiveFilters>): string {
  const p = new URLSearchParams();
  if (isFilterActive(sel.region)) p.set("region", sel.region);
  if (isFilterActive(sel.district)) p.set("district", sel.district);
  if (isFilterActive(sel.cluster)) p.set("cluster", sel.cluster);
  const q = p.toString();
  return q ? `?${q}` : "";
}

type ViewMode = "choropleth" | "bubbles";

export function UgandaGeoMap() {
  const selection = useActiveFilters();
  const qs = geoQs(selection);
  const [geo, setGeo] = useState<GeoJson | null>(null);
  const [data, setData] = useState<BeGeoMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [metricKey, setMetricKey] = useState<keyof BeGeoDistrict>("schools");
  const [viewMode, setViewMode] = useState<ViewMode>("bubbles");
  const [showPins, setShowPins] = useState(true);
  const [hover, setHover] = useState<{ d: BeGeoDistrict | null; name: string; x: number; y: number } | null>(null);
  const [pinned, setPinned] = useState<BeGeoDistrict | null>(null);
  const [view, setView] = useState({ scale: 1, tx: 0, ty: 0 });
  const drag = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null);

  useEffect(() => {
    fetch("/geo/districts.geojson").then((r) => r.json()).then(setGeo).catch(() => setError("Could not load map geometry"));
  }, []);

  const load = useCallback(() => {
    setLoading(true); setError(null);
    fetch(`/api/analytics/geo-map${qs}`, { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) setData(j as BeGeoMap); else setError(j.error || "Could not load map data"); })
      .catch(() => setError("Could not reach the server"))
      .finally(() => setLoading(false));
  }, [qs]);
  useEffect(load, [load]);

  const metric = METRICS.find((m) => m.key === metricKey)!;
  const byPcode = useMemo(() => new Map((data?.districts ?? []).map((d) => [d.pcode, d])), [data]);

  const proj = useMemo(() => {
    if (!geo) return null;
    const [minLng, minLat, maxLng, maxLat] = geo.bbox;
    const lngSpan = maxLng - minLng, latSpan = maxLat - minLat;
    const H = Math.round((W * latSpan) / lngSpan);
    const px = (lng: number) => ((lng - minLng) / lngSpan) * W;
    const py = (lat: number) => ((maxLat - lat) / latSpan) * H;
    return { H, px, py };
  }, [geo]);

  const paths = useMemo(() => {
    if (!geo || !proj) return [];
    const ring = (coords: number[][]) => coords.map(([lng, lat], i) => `${i === 0 ? "M" : "L"}${proj.px(lng).toFixed(1)},${proj.py(lat).toFixed(1)}`).join("") + "Z";
    return geo.features.map((f) => {
      const g = f.geometry;
      let d = "";
      if (g.type === "Polygon") d = (g.coordinates as number[][][]).map(ring).join("");
      else if (g.type === "MultiPolygon") d = (g.coordinates as number[][][][]).flatMap((poly) => poly.map(ring)).join("");
      return { pcode: f.properties.pcode, name: f.properties.name, d };
    });
  }, [geo, proj]);

  // Choropleth colour scale for the active metric.
  const scale = useMemo(() => {
    const vals = (data?.districts ?? []).map((d) => d[metricKey]).filter((v): v is number => typeof v === "number");
    const min = vals.length ? Math.min(...vals) : 0;
    const max = vals.length ? Math.max(...vals) : 1;
    const ramp = metric.higherIsBetter ? RAMP_GOOD : RAMP_BAD;
    const colorFor = (v: number | null | undefined) => {
      if (v == null) return NO_DATA;
      if (max === min) return ramp[ramp.length - 1];
      const t = (v - min) / (max - min);
      return ramp[Math.min(ramp.length - 1, Math.floor(t * ramp.length))];
    };
    return { min, max, ramp, colorFor };
  }, [data, metricKey, metric.higherIsBetter]);

  // Bubble radius scale — AREA-proportional (r ∝ √value) so a district with 4×
  // the schools reads as 4× the area, not 4× the radius. Sized by the metric.
  const bubbleR = useMemo(() => {
    const vals = (data?.districts ?? []).map((d) => d[metricKey]).filter((v): v is number => typeof v === "number" && v > 0);
    const max = vals.length ? Math.max(...vals) : 1;
    const MIN_R = 5, MAX_R = 30;
    return (v: number | null | undefined) => (v == null || v <= 0 ? 0 : MIN_R + (MAX_R - MIN_R) * Math.sqrt(v / max));
  }, [data, metricKey]);

  const onWheel = (e: React.WheelEvent) => { e.preventDefault(); setView((v) => ({ ...v, scale: Math.min(8, Math.max(1, v.scale * (e.deltaY < 0 ? 1.15 : 0.87))) })); };
  const zoom = (f: number) => setView((v) => ({ ...v, scale: Math.min(8, Math.max(1, v.scale * f)) }));
  const reset = () => setView({ scale: 1, tx: 0, ty: 0 });

  if (error) return <section className="card p-3.5"><ErrorState message={error} onRetry={load} /></section>;
  if (!geo || (!data && loading)) return <section className="card p-3.5"><LoadingState /></section>;

  const s = data?.summary;
  const points = data?.schoolPoints ?? [];

  return (
    <section className="card p-0 overflow-hidden">
      <header className="px-4 py-3 border-b border-[var(--color-edify-divider)] flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-[14px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><MapIcon size={15} className="text-[var(--color-edify-primary)]" /> Uganda Geo-Analytics</h3>
          {s && <p className="text-[11.5px] muted">{s.schools.toLocaleString()} schools · {s.districts} districts · {s.subRegions} sub-regions · <span className="text-rose-600 font-semibold">{s.highRiskDistricts} high-risk</span></p>}
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend · COD-AB</span>
      </header>

      {/* Controls: view mode · metric · pins */}
      <div className="px-4 py-2.5 border-b border-[var(--color-edify-divider)] flex items-center gap-x-3 gap-y-2 flex-wrap">
        <div className="inline-flex rounded-lg border border-[var(--color-edify-border)] overflow-hidden">
          {(["bubbles", "choropleth"] as ViewMode[]).map((v) => (
            <button key={v} onClick={() => setViewMode(v)} className={cn("px-2.5 py-1 text-[11px] font-semibold capitalize", viewMode === v ? "bg-[var(--color-edify-primary)] text-white" : "hover:bg-[var(--color-edify-soft)]/50")}>{v}</button>
          ))}
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-[10px] uppercase tracking-wider font-bold muted">{viewMode === "bubbles" ? "Size by" : "Colour by"}</span>
          {METRICS.map((m) => (
            <button key={String(m.key)} onClick={() => setMetricKey(m.key)}
              className={cn("px-2 py-1 rounded-md text-[11px] font-semibold border transition-colors",
                metricKey === m.key ? "bg-[var(--color-edify-primary)] text-white border-[var(--color-edify-primary)]" : "bg-transparent border-[var(--color-edify-border)] hover:bg-[var(--color-edify-soft)]/50")}>
              {m.label}
            </button>
          ))}
        </div>
        <label className="inline-flex items-center gap-1.5 text-[11px] font-semibold cursor-pointer ml-auto">
          <input type="checkbox" checked={showPins} onChange={(e) => setShowPins(e.target.checked)} className="accent-[var(--color-edify-primary)]" />
          School pins {points.length > 0 && <span className="muted">({points.length})</span>}
        </label>
      </div>

      <div className="relative">
        <div className="absolute top-3 right-3 z-10 flex flex-col gap-1">
          <button onClick={() => zoom(1.3)} aria-label="Zoom in" className="h-7 w-7 rounded-md bg-[var(--surface-1)] border border-[var(--color-edify-border)] inline-flex items-center justify-center hover:bg-[var(--color-edify-soft)]"><ZoomIn size={14} /></button>
          <button onClick={() => zoom(0.77)} aria-label="Zoom out" className="h-7 w-7 rounded-md bg-[var(--surface-1)] border border-[var(--color-edify-border)] inline-flex items-center justify-center hover:bg-[var(--color-edify-soft)]"><ZoomOut size={14} /></button>
          <button onClick={reset} aria-label="Reset view" className="h-7 w-7 rounded-md bg-[var(--surface-1)] border border-[var(--color-edify-border)] inline-flex items-center justify-center hover:bg-[var(--color-edify-soft)]"><Maximize2 size={13} /></button>
        </div>

        {/* Legend */}
        <div className="absolute bottom-3 left-3 z-10 bg-[var(--surface-1)]/90 backdrop-blur border border-[var(--color-edify-border)] rounded-lg px-2.5 py-2 text-[10px]">
          {viewMode === "choropleth" ? (
            <>
              <div className="font-bold uppercase tracking-wide muted mb-1">{metric.label}</div>
              <div className="flex items-center gap-1">
                <span className="muted">{metric.fmt ? metric.fmt(scale.min) : scale.min}</span>
                <div className="flex">{scale.ramp.map((c, i) => <span key={i} className="w-5 h-2.5" style={{ background: c }} />)}</div>
                <span className="muted">{metric.fmt ? metric.fmt(scale.max) : scale.max}</span>
              </div>
            </>
          ) : (
            <>
              <div className="font-bold uppercase tracking-wide muted mb-1">Bubble size = {metric.label}</div>
              <div className="flex items-center gap-2.5">
                {(["healthy", "needs_attention", "high_risk"] as const).map((k) => (
                  <span key={k} className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: STATUS_META[k].fill }} /> {STATUS_META[k].label}</span>
                ))}
              </div>
            </>
          )}
        </div>

        <svg viewBox={`0 0 ${W} ${proj!.H}`} className="w-full h-auto max-h-[560px] select-none touch-none" style={{ background: "var(--surface-1)" }}
          onWheel={onWheel}
          onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty }; }}
          onMouseUp={() => (drag.current = null)}
          onMouseLeave={() => { drag.current = null; setHover(null); }}
          onMouseMove={(e) => { if (drag.current) { const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y; setView((v) => ({ ...v, tx: drag.current!.tx + dx, ty: drag.current!.ty + dy })); } }}>
          <g transform={`translate(${view.tx} ${view.ty}) scale(${view.scale})`}>
            {/* Choropleth / status underlay */}
            {paths.map((p) => {
              const d = byPcode.get(p.pcode);
              const fill = !d ? NO_DATA : viewMode === "choropleth" ? scale.colorFor(d[metricKey] as number | null) : STATUS_TINT[d.status];
              const isActive = pinned?.pcode === p.pcode;
              return (
                <path key={p.pcode} d={p.d} fill={fill}
                  stroke={isActive ? "var(--color-edify-primary)" : "var(--surface-1)"} strokeWidth={(isActive ? 2 : 0.5) / view.scale}
                  className="cursor-pointer transition-[fill] duration-150 hover:opacity-80"
                  onMouseMove={(e) => { const r = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect(); setHover({ d: d ?? null, name: p.name, x: e.clientX - r.left, y: e.clientY - r.top }); }}
                  onClick={() => d && setPinned(d)} />
              );
            })}

            {/* Proportional bubbles — size = metric, colour = health status */}
            {viewMode === "bubbles" && data?.districts.map((d) => {
              if (d.centroidLat == null || d.centroidLng == null) return null;
              const r = bubbleR(d[metricKey] as number | null);
              if (r <= 0) return null;
              return (
                <circle key={d.districtId} cx={proj!.px(d.centroidLng)} cy={proj!.py(d.centroidLat)} r={r / view.scale * Math.min(view.scale, 1.6)}
                  fill={STATUS_META[d.status].fill} fillOpacity={0.62} stroke="#fff" strokeWidth={1 / view.scale}
                  className="cursor-pointer hover:fill-opacity-80"
                  onMouseMove={(e) => { const rect = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect(); setHover({ d, name: d.district, x: e.clientX - rect.left, y: e.clientY - rect.top }); }}
                  onClick={() => setPinned(d)} />
              );
            })}

            {/* Exact school pins — auto-appear when schools have coordinates */}
            {showPins && points.map((pt: BeGeoSchoolPoint) => (
              <circle key={pt.schoolId} cx={proj!.px(pt.lng)} cy={proj!.py(pt.lat)} r={3 / view.scale}
                fill={PIN_FILL[pt.type] ?? "#64748b"} stroke="#fff" strokeWidth={0.6 / view.scale}>
                <title>{pt.name}</title>
              </circle>
            ))}
          </g>
        </svg>

        {hover && (
          <div className="absolute z-20 pointer-events-none bg-[var(--surface-1)] border border-[var(--color-edify-border)] rounded-lg shadow-lg px-3 py-2 text-[11.5px] min-w-[170px]"
            style={{ left: Math.min(hover.x + 12, W - 60), top: hover.y + 12, transform: hover.x > 520 ? "translateX(-110%)" : undefined }}>
            <div className="font-extrabold tracking-tight">{hover.name}</div>
            {hover.d ? (
              <>
                <div className="muted text-[10.5px] mb-1">{hover.d.subRegion ?? "—"} · {hover.d.region}</div>
                <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 tabular">
                  <span className="muted">Schools</span><span className="text-right font-bold">{hover.d.schools}</span>
                  <span className="muted">Core</span><span className="text-right font-bold">{hover.d.coreSchools}</span>
                  <span className="muted">SSA avg</span><span className="text-right font-bold">{hover.d.avgSsa ?? "—"}</span>
                  <span className="muted">Critical</span><span className="text-right font-bold text-rose-600">{hover.d.criticalCount}</span>
                </div>
                <span className={cn("mt-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border", STATUS_META[hover.d.status].cls)}>{STATUS_META[hover.d.status].label}</span>
              </>
            ) : <div className="muted text-[10.5px]">No schools in scope</div>}
          </div>
        )}
      </div>

      {pinned && <DistrictDrawer d={pinned} onClose={() => setPinned(null)} />}
    </section>
  );
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-edify-divider)] px-2.5 py-1.5">
      <div className="text-[9.5px] uppercase tracking-wide muted font-bold">{label}</div>
      <div className={cn("text-[15px] font-extrabold tabular", tone)}>{value}</div>
    </div>
  );
}

function DistrictDrawer({ d, onClose }: { d: BeGeoDistrict; onClose: () => void }) {
  const sm = STATUS_META[d.status];
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-label={`${d.district} district analytics`}>
      <button className="absolute inset-0 bg-black/30" aria-label="Close" onClick={onClose} />
      <aside className="relative w-full sm:w-[420px] max-w-full h-full bg-[var(--surface-1)] border-l border-[var(--color-edify-border)] shadow-2xl overflow-y-auto">
        <header className="sticky top-0 bg-[var(--surface-1)] border-b border-[var(--color-edify-divider)] px-4 py-3 flex items-start justify-between gap-2 z-10">
          <div>
            <h3 className="text-[15px] font-extrabold tracking-tight">{d.district}</h3>
            <p className="text-[11.5px] muted">{d.subRegion ?? "—"} sub-region · {d.region} region</p>
            <span className={cn("mt-1 inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold border", sm.cls)}>
              {d.status === "high_risk" ? <AlertTriangle size={11} /> : d.status === "healthy" ? <ShieldCheck size={11} /> : null}{sm.label}
            </span>
          </div>
          <button onClick={onClose} aria-label="Close" className="h-7 w-7 rounded-md hover:bg-[var(--color-edify-soft)] inline-flex items-center justify-center"><X size={16} /></button>
        </header>
        <div className="p-4 space-y-4">
          <section>
            <h4 className="text-[11px] uppercase tracking-wider font-bold muted mb-2">School portfolio</h4>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Schools" value={d.schools} />
              <Stat label="Core" value={d.coreSchools} />
              <Stat label="Client" value={d.clientSchools} />
              <Stat label="Clustered" value={d.clustered} />
              <Stat label="Unclustered" value={d.unclustered} tone={d.unclustered ? "text-rose-600" : undefined} />
              <Stat label="SSA done" value={`${d.ssaPct}%`} />
            </div>
          </section>
          <section>
            <h4 className="text-[11px] uppercase tracking-wider font-bold muted mb-2">SSA performance</h4>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="SSA avg" value={d.avgSsa ?? "—"} tone={d.avgSsa != null ? (d.avgSsa < 5 ? "text-rose-600" : d.avgSsa < 7 ? "text-amber-600" : "text-emerald-600") : undefined} />
              <Stat label="Critical" value={d.criticalCount} tone={d.criticalCount ? "text-rose-600" : undefined} />
              <Stat label="SSA pending" value={d.ssaPending} />
            </div>
          </section>
          <section>
            <h4 className="text-[11px] uppercase tracking-wider font-bold muted mb-2">Execution</h4>
            <div className="grid grid-cols-3 gap-2"><Stat label="Activities done" value={d.activitiesCompleted} /></div>
          </section>
          <section className="space-y-1.5">
            <h4 className="text-[11px] uppercase tracking-wider font-bold muted mb-1">Quick actions</h4>
            <Action href={`/analytics?district=${encodeURIComponent(d.district)}`} label="Filter analytics to this district" />
            <Action href={`/schools?district=${encodeURIComponent(d.district)}`} label="View schools in district" />
            <Action href={`/coverage?district=${encodeURIComponent(d.district)}`} label="View coverage & support needs" />
          </section>
        </div>
      </aside>
    </div>
  );
}

function Action({ href, label }: { href: string; label: string }) {
  return (
    <Link href={href} className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-[var(--color-edify-divider)] text-[12px] font-semibold hover:bg-[var(--color-edify-soft)]/50">
      {label} <ArrowRight size={13} className="text-[var(--color-edify-muted)]" />
    </Link>
  );
}

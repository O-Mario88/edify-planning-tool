"use client";

// Uganda Geo-Analytics Map — a leadership intelligence surface, not decoration.
//
// Real district BOUNDARY geometry (COD-AB, /public/geo/districts.geojson) joined
// by official pcode to (a) static district meta — region/sub-region/centroid for
// ALL 135 districts (/public/geo/district-meta.json) and (b) LIVE per-district
// analytics (/api/analytics/geo-map, role-scoped + filter-aware).
//
// Three views: Bubbles (size = count, colour = health status), Choropleth
// (colour = a metric), and Sub-regions (each district filled by its sub-region,
// grouped into region hue families). Strong borders + always-on labels for
// regions/sub-regions/districts, so the map reads without hovering. Hover → rich
// preview; click → full district analytics drawer; zoom / pan.

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Map as MapIcon, ZoomIn, ZoomOut, Maximize2, ArrowRight, AlertTriangle, ShieldCheck, TrendingDown, Building2, Briefcase, Network, Gauge, MapPin, Layers } from "lucide-react";
import Link from "next/link";
import { isFilterActive, useActiveFilters } from "@/hooks/use-active-filters";
import { ErrorState, LoadingState } from "@/components/ui/DataStates";
import { Modal } from "@/components/ui/Modal";
import { cn } from "@/lib/utils";
import type { BeGeoMap, BeGeoDistrict, BeGeoSchoolPoint, BeGeoCluster, BeGeoDistrictDetail, BeGeoSummary } from "@/lib/api/surfaces";

type GeoFeature = { properties: { pcode: string; name: string; region: string }; geometry: { type: string; coordinates: number[][][] | number[][][][] } };
type GeoJson = { bbox: [number, number, number, number]; features: GeoFeature[] };
type DistrictMeta = { pcode: string; name: string; region: string; subRegion: string | null; lat: number | null; lng: number | null };

// Hover card content — district (default / low zoom) or sub-county (zoomed in).
type HoverState =
  | { kind: "district"; x: number; y: number; d: BeGeoDistrict | null; name: string; sub: string | null; region: string | null }
  | { kind: "subcounty"; x: number; y: number; name: string; districtPcode: string; districtId: string | null; districtName: string; sub: string | null; region: string | null };

// What the detail panel / drawer is focused on. Defaults to the whole country.
type Focus =
  | { kind: "country" }
  | { kind: "district"; d: BeGeoDistrict }
  | { kind: "subcounty"; name: string; districtId: string | null; districtName: string; sub: string | null; region: string | null };

// lg breakpoint — desktop shows the detail inline (75/25 split); mobile/tablet
// opens it as a floating drawer.
function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const update = () => setIsDesktop(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return isDesktop;
}

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
const BORDER = "#64748b"; // slate-500 — strong, always-visible district borders

// Sub-region palette: each REGION is a hue family, each sub-region a distinct
// shade within it — so the map reads regions AND sub-regions at a glance.
const SUBREGION_COLOR: Record<string, string> = {
  // Central — blues
  "Kampala Capital City": "#3b82f6", Buganda: "#93c5fd",
  // Eastern — teals/greens
  Busoga: "#5eead4", Bukedi: "#2dd4bf", Bugisu: "#14b8a6", Sebei: "#0d9488", Teso: "#99f6e4",
  // Northern — ambers
  Acholi: "#fbbf24", Lango: "#f59e0b", Karamoja: "#fcd34d", "West Nile": "#fde68a", Madi: "#d97706",
  // Western — violets
  Bunyoro: "#c4b5fd", Tooro: "#a78bfa", Rwenzori: "#8b5cf6", Ankole: "#ddd6fe", Kigezi: "#7c3aed",
};
const subRegionColor = (sr: string | null | undefined) => (sr && SUBREGION_COLOR[sr]) || NO_DATA;

const STATUS_META: Record<BeGeoDistrict["status"], { label: string; cls: string; fill: string }> = {
  healthy: { label: "Healthy", cls: "bg-emerald-50 text-emerald-700 border-emerald-200", fill: "#22b07f" },
  needs_attention: { label: "Needs Attention", cls: "bg-amber-50 text-amber-700 border-amber-200", fill: "#f59e0b" },
  high_risk: { label: "High Risk", cls: "bg-rose-50 text-rose-700 border-rose-200", fill: "#e11d48" },
  insufficient_data: { label: "No SSA yet", cls: "bg-slate-100 text-slate-500 border-slate-200", fill: "#94a3b8" },
};
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

type ViewMode = "subregions" | "bubbles" | "choropleth";

export function UgandaGeoMap() {
  const selection = useActiveFilters();
  const qs = geoQs(selection);
  const [geo, setGeo] = useState<GeoJson | null>(null);
  const [meta, setMeta] = useState<DistrictMeta[] | null>(null);
  const [data, setData] = useState<BeGeoMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [metricKey, setMetricKey] = useState<keyof BeGeoDistrict>("schools");
  const [viewMode, setViewMode] = useState<ViewMode>("subregions");
  const [showPins, setShowPins] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [hover, setHover] = useState<HoverState | null>(null);
  const [focus, setFocus] = useState<Focus>({ kind: "country" });
  const isDesktop = useIsDesktop();
  // District detail (clusters + sub-counties) — lazy-fetched per district + cached.
  const detailCache = useRef<Map<string, BeGeoDistrictDetail>>(new Map());
  const [, bumpCache] = useState(0);
  // Clicking focuses the detail; on mobile/tablet it also opens the floating drawer.
  const pin = (f: Focus) => setFocus(f);
  const [view, setView] = useState({ scale: 1, tx: 0, ty: 0 });
  const [subCounties, setSubCounties] = useState<{ features: { properties: { pcode: string; name: string; district: string; lat: number; lng: number }; geometry: { type: string; coordinates: number[][][] | number[][][][] } }[] } | null>(null);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null);
  const lastDragMoved = useRef(false);
  const svgRef = useRef<SVGSVGElement>(null);
  // Zoom level at which sub-county boundaries (admin4) progressively appear —
  // Google-Maps-style level-of-detail. Loaded lazily on first zoom-in.
  const SUBCOUNTY_ZOOM = 2.4;

  useEffect(() => {
    Promise.all([
      fetch("/geo/districts.geojson").then((r) => r.json()),
      fetch("/geo/district-meta.json").then((r) => r.json()),
    ]).then(([g, m]) => { setGeo(g); setMeta(m); }).catch(() => setError("Could not load map geometry"));
  }, []);

  // Lazy-load sub-county geometry the first time the user zooms past the threshold.
  useEffect(() => {
    if (view.scale >= SUBCOUNTY_ZOOM && !subCounties) {
      fetch("/geo/subcounties.geojson").then((r) => r.json()).then(setSubCounties).catch(() => {});
    }
  }, [view.scale, subCounties]);

  // Lazily fetch + cache a district's detail (clusters + sub-county breakdown).
  // Used by the hover card (cluster list / sub-county figures) and the detail
  // panel. No-ops when already cached or in flight.
  const inFlight = useRef<Set<string>>(new Set());
  const ensureDetail = useCallback((id: string | null | undefined) => {
    if (!id || detailCache.current.has(id) || inFlight.current.has(id)) return;
    inFlight.current.add(id);
    fetch(`/api/analytics/geo-map/district/${encodeURIComponent(id)}`, { credentials: "include" })
      .then((r) => r.json())
      .then((j) => { if (j.live) { detailCache.current.set(id, j as BeGeoDistrictDetail); bumpCache((n) => n + 1); } })
      .catch(() => {})
      .finally(() => inFlight.current.delete(id));
  }, []);
  const hoverDistrictId = hover?.kind === "district" ? hover.d?.districtId ?? null : hover?.kind === "subcounty" ? hover.districtId : null;
  useEffect(() => { ensureDetail(hoverDistrictId); }, [hoverDistrictId, ensureDetail]);
  const focusDistrictId = focus.kind === "district" ? focus.d.districtId : focus.kind === "subcounty" ? focus.districtId : null;
  useEffect(() => { ensureDetail(focusDistrictId); }, [focusDistrictId, ensureDetail]);

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
  const metaByPcode = useMemo(() => new Map((meta ?? []).map((m) => [m.pcode, m])), [meta]);

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

  // Sub-county boundary paths (admin4) — built once the geometry is loaded.
  const subCountyPaths = useMemo(() => {
    if (!subCounties || !proj) return [];
    const ring = (coords: number[][]) => coords.map(([lng, lat], i) => `${i === 0 ? "M" : "L"}${proj.px(lng).toFixed(1)},${proj.py(lat).toFixed(1)}`).join("") + "Z";
    return subCounties.features.map((f) => {
      const g = f.geometry;
      const d = g.type === "Polygon"
        ? (g.coordinates as number[][][]).map(ring).join("")
        : (g.coordinates as number[][][][]).flatMap((poly) => poly.map(ring)).join("");
      return { pcode: f.properties.pcode, name: f.properties.name, district: f.properties.district, lat: f.properties.lat, lng: f.properties.lng, d };
    });
  }, [subCounties, proj]);

  // Sub-region label anchors — centroid = mean of member-district centroids.
  const subRegionLabels = useMemo(() => {
    if (!meta || !proj) return [];
    const groups = new Map<string, { sum: [number, number]; n: number }>();
    for (const m of meta) {
      if (!m.subRegion || m.lat == null || m.lng == null) continue;
      const g = groups.get(m.subRegion) ?? { sum: [0, 0], n: 0 };
      g.sum[0] += m.lng; g.sum[1] += m.lat; g.n++; groups.set(m.subRegion, g);
    }
    return [...groups.entries()].map(([name, g]) => ({ name, x: proj.px(g.sum[0] / g.n), y: proj.py(g.sum[1] / g.n) }));
  }, [meta, proj]);

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

  const bubbleR = useMemo(() => {
    const vals = (data?.districts ?? []).map((d) => d[metricKey]).filter((v): v is number => typeof v === "number" && v > 0);
    const max = vals.length ? Math.max(...vals) : 1;
    const MIN_R = 5, MAX_R = 30;
    return (v: number | null | undefined) => (v == null || v <= 0 ? 0 : MIN_R + (MAX_R - MIN_R) * Math.sqrt(v / max));
  }, [data, metricKey]);

  // Zoom toward a focal point (Google-Maps feel): keep the map point under the
  // cursor fixed while scaling. focalX/Y are in viewBox units (0..W, 0..H).
  const MAX_ZOOM = 14;
  const zoomAt = (factor: number, focalX: number, focalY: number) => {
    setView((v) => {
      const scale = Math.min(MAX_ZOOM, Math.max(1, v.scale * factor));
      if (scale === v.scale) return v;
      // map point currently under the focal point: (focal - t) / oldScale
      const mapX = (focalX - v.tx) / v.scale;
      const mapY = (focalY - v.ty) / v.scale;
      let tx = focalX - mapX * scale;
      let ty = focalY - mapY * scale;
      // Clamp so the map can't be panned entirely off-screen.
      const H = proj!.H;
      tx = Math.min(0, Math.max(W - W * scale, tx));
      ty = Math.min(0, Math.max(H - H * scale, ty));
      return { scale, tx, ty };
    });
  };
  const focalFromEvent = (e: React.WheelEvent | React.MouseEvent) => {
    const r = svgRef.current?.getBoundingClientRect();
    if (!r) return { fx: W / 2, fy: proj!.H / 2 };
    return { fx: ((e.clientX - r.left) / r.width) * W, fy: ((e.clientY - r.top) / r.height) * proj!.H };
  };
  const onWheel = (e: React.WheelEvent) => { e.preventDefault(); const { fx, fy } = focalFromEvent(e); zoomAt(e.deltaY < 0 ? 1.2 : 1 / 1.2, fx, fy); };
  const zoom = (f: number) => zoomAt(f, W / 2, proj!.H / 2);
  const reset = () => setView({ scale: 1, tx: 0, ty: 0 });

  // Visible viewBox region (map units) → cull sub-counties to the zoomed area.
  const visible = { x0: -view.tx / view.scale, x1: (W - view.tx) / view.scale, y0: -view.ty / view.scale, y1: ((proj?.H ?? 0) - view.ty) / view.scale };
  const inView = (lng: number | null, lat: number | null) => {
    if (lng == null || lat == null || !proj) return false;
    const x = proj.px(lng), y = proj.py(lat);
    const mx = (visible.x1 - visible.x0) * 0.15, my = (visible.y1 - visible.y0) * 0.15;
    return x >= visible.x0 - mx && x <= visible.x1 + mx && y >= visible.y0 - my && y <= visible.y1 + my;
  };
  const showSubCounties = view.scale >= SUBCOUNTY_ZOOM && subCountyPaths.length > 0;

  if (error) return <section className="card p-3.5"><ErrorState message={error} onRetry={load} /></section>;
  if (!geo || !meta || (!data && loading)) return <section className="card p-3.5"><LoadingState /></section>;

  const s = data?.summary;
  const points = data?.schoolPoints ?? [];
  // Every labeled district is clickable. Districts with live analytics open their
  // full drawer; districts with no schools in scope still open a drawer showing
  // their geography + an honest "no schools in scope yet" state (never a dead click).
  const districtFor = (pcode: string, name: string): BeGeoDistrict => {
    const d = byPcode.get(pcode);
    if (d) return d;
    const m = metaByPcode.get(pcode);
    return {
      districtId: pcode, pcode, district: m?.name ?? name, region: m?.region ?? "", subRegion: m?.subRegion ?? null,
      centroidLat: m?.lat ?? null, centroidLng: m?.lng ?? null,
      schools: 0, coreSchools: 0, clientSchools: 0, clustered: 0, unclustered: 0, clusters: 0,
      ssaDone: 0, ssaPending: 0, ssaPct: 0, avgSsa: null, coreAvgSsa: null, clientAvgSsa: null, criticalCount: 0, coreCriticalCount: 0, clientCriticalCount: 0, activitiesCompleted: 0,
      status: "insufficient_data", interventions: [], weakestInterventions: [],
    };
  };
  const fillFor = (pcode: string) => {
    const d = byPcode.get(pcode);
    if (viewMode === "subregions") return subRegionColor(metaByPcode.get(pcode)?.subRegion);
    if (!d) return NO_DATA;
    return viewMode === "choropleth" ? scale.colorFor(d[metricKey] as number | null) : STATUS_TINT[d.status];
  };

  const focusDetail = focusDistrictId ? detailCache.current.get(focusDistrictId) : undefined;

  return (
    <div className="lg:grid lg:grid-cols-4 lg:gap-4 lg:items-start">
    <section className="card p-0 overflow-hidden lg:col-span-3">
      <header className="px-4 py-3 border-b border-[var(--color-edify-divider)] flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 className="text-[14px] font-extrabold tracking-tight inline-flex items-center gap-1.5"><MapIcon size={15} className="text-[var(--color-edify-primary)]" /> Uganda Geo-Analytics</h3>
          {s && <p className="text-[11.5px] muted">{s.schools.toLocaleString()} schools · {s.districts} districts · {s.subRegions} sub-regions · <span className="text-rose-600 font-semibold">{s.highRiskDistricts} high-risk</span></p>}
        </div>
        <span className="inline-flex items-center gap-1 rounded-full bg-[var(--color-edify-soft)] text-[var(--color-edify-primary)] px-2 py-0.5 text-[10px] font-bold border border-[var(--color-edify-border)]">Live · backend · COD-AB</span>
      </header>

      <div className="px-4 py-2.5 border-b border-[var(--color-edify-divider)] flex items-center gap-x-3 gap-y-2 flex-wrap">
        <div className="inline-flex rounded-lg border border-[var(--color-edify-border)] overflow-hidden">
          {(["subregions", "bubbles", "choropleth"] as ViewMode[]).map((v) => (
            <button key={v} onClick={() => setViewMode(v)} className={cn("px-2.5 py-1 text-[11px] font-semibold capitalize", viewMode === v ? "bg-[var(--color-edify-primary)] text-white" : "hover:bg-[var(--color-edify-soft)]/50")}>{v === "subregions" ? "Sub-regions" : v}</button>
          ))}
        </div>
        {viewMode !== "subregions" && (
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
        )}
        <div className="flex items-center gap-3 ml-auto">
          <label className="inline-flex items-center gap-1.5 text-[11px] font-semibold cursor-pointer">
            <input type="checkbox" checked={showLabels} onChange={(e) => setShowLabels(e.target.checked)} className="accent-[var(--color-edify-primary)]" /> Labels
          </label>
          <label className="inline-flex items-center gap-1.5 text-[11px] font-semibold cursor-pointer">
            <input type="checkbox" checked={showPins} onChange={(e) => setShowPins(e.target.checked)} className="accent-[var(--color-edify-primary)]" /> Pins {points.length > 0 && <span className="muted">({points.length})</span>}
          </label>
        </div>
      </div>

      <div className="relative">
        <div className="absolute top-3 right-3 z-10 flex flex-col gap-1">
          <button onClick={() => zoom(1.3)} aria-label="Zoom in" className="h-7 w-7 rounded-md bg-[var(--surface-1)] border border-[var(--color-edify-border)] inline-flex items-center justify-center hover:bg-[var(--color-edify-soft)]"><ZoomIn size={14} /></button>
          <button onClick={() => zoom(0.77)} aria-label="Zoom out" className="h-7 w-7 rounded-md bg-[var(--surface-1)] border border-[var(--color-edify-border)] inline-flex items-center justify-center hover:bg-[var(--color-edify-soft)]"><ZoomOut size={14} /></button>
          <button onClick={reset} aria-label="Reset view" className="h-7 w-7 rounded-md bg-[var(--surface-1)] border border-[var(--color-edify-border)] inline-flex items-center justify-center hover:bg-[var(--color-edify-soft)]"><Maximize2 size={13} /></button>
        </div>

        <div className="absolute bottom-3 left-3 z-10 bg-[var(--surface-1)]/90 backdrop-blur border border-[var(--color-edify-border)] rounded-lg px-2.5 py-2 text-[10px] max-w-[60%]">
          {viewMode === "subregions" ? (
            <>
              <div className="font-bold uppercase tracking-wide muted mb-1">Sub-regions by region</div>
              <div className="flex flex-wrap gap-x-2.5 gap-y-1">
                {["Buganda", "Busoga", "Acholi", "Lango", "Ankole", "Kigezi"].map((k) => (
                  <span key={k} className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-sm" style={{ background: SUBREGION_COLOR[k] }} /> {k}</span>
                ))}
                <span className="muted">+ {Object.keys(SUBREGION_COLOR).length - 6} more</span>
              </div>
            </>
          ) : viewMode === "choropleth" ? (
            <>
              <div className="font-bold uppercase tracking-wide muted mb-1">{metric.label}</div>
              <div className="flex items-center gap-1"><span className="muted">{metric.fmt ? metric.fmt(scale.min) : scale.min}</span><div className="flex">{scale.ramp.map((c, i) => <span key={i} className="w-5 h-2.5" style={{ background: c }} />)}</div><span className="muted">{metric.fmt ? metric.fmt(scale.max) : scale.max}</span></div>
            </>
          ) : (
            <>
              <div className="font-bold uppercase tracking-wide muted mb-1">Bubble size = {metric.label}</div>
              <div className="flex items-center gap-2.5">{(["healthy", "needs_attention", "high_risk"] as const).map((k) => (<span key={k} className="inline-flex items-center gap-1"><span className="w-2.5 h-2.5 rounded-full" style={{ background: STATUS_META[k].fill }} /> {STATUS_META[k].label}</span>))}</div>
            </>
          )}
        </div>

        <svg ref={svgRef} viewBox={`0 0 ${W} ${proj!.H}`} className="w-full h-auto max-h-[600px] select-none touch-none" style={{ background: "var(--surface-1)" }}
          onWheel={onWheel}
          onMouseDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false }; }}
          onMouseUp={() => { lastDragMoved.current = drag.current?.moved ?? false; drag.current = null; }}
          onMouseLeave={() => { drag.current = null; setHover(null); }}
          onMouseMove={(e) => { if (drag.current) { const dx = e.clientX - drag.current.x, dy = e.clientY - drag.current.y; if (Math.abs(dx) + Math.abs(dy) > 3) drag.current.moved = true; setView((v) => ({ ...v, tx: drag.current!.tx + dx, ty: drag.current!.ty + dy })); } }}>
          {/* Blank-canvas backdrop — clicking empty map area (not a district/sub-county)
              resets the detail back to the whole country. Behind everything; a real
              pan (moved) doesn't count as a click. */}
          <rect x={0} y={0} width={W} height={proj!.H} fill="var(--surface-1)"
            onClick={() => { if (!lastDragMoved.current) setFocus({ kind: "country" }); }} />
          <g transform={`translate(${view.tx} ${view.ty}) scale(${view.scale})`}>
            {/* District polygons — strong borders, always visible */}
            {paths.map((p) => {
              const d = byPcode.get(p.pcode);
              const m = metaByPcode.get(p.pcode);
              const isActive = focus.kind === "district" && focus.d.pcode === p.pcode;
              return (
                <path key={p.pcode} data-pcode={p.pcode} d={p.d} fill={fillFor(p.pcode)}
                  stroke={isActive ? "var(--color-edify-primary)" : BORDER} strokeWidth={(isActive ? 2.5 : 0.9) / view.scale} strokeLinejoin="round"
                  className="cursor-pointer transition-[fill] duration-150 hover:brightness-95"
                  onMouseMove={(e) => { const r = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect(); setHover({ kind: "district", d: d ?? null, name: p.name, sub: m?.subRegion ?? d?.subRegion ?? null, region: m?.region ?? d?.region ?? null, x: e.clientX - r.left, y: e.clientY - r.top }); }}
                  onClick={() => pin({ kind: "district", d: districtFor(p.pcode, p.name) })} />
              );
            })}

            {/* Sub-county polygons (admin4) — appear on zoom-in (Google-Maps LOD),
                culled to the districts in view. Transparent fill makes each
                hoverable: hovering shows the SUB-COUNTY's details instead of the
                district; clicking still opens the parent district drawer. */}
            {showSubCounties && subCountyPaths.map((sc) => {
              const dm = metaByPcode.get(sc.district);
              if (!dm || !inView(dm.lng, dm.lat)) return null;
              return (
                <path key={sc.pcode} d={sc.d} fill="transparent" stroke="#475569" strokeOpacity={0.8} strokeWidth={0.7 / view.scale} strokeLinejoin="round"
                  className="cursor-pointer hover:fill-[#3f6b94]/10"
                  onMouseMove={(e) => { const r = (e.currentTarget.ownerSVGElement as SVGSVGElement).getBoundingClientRect(); setHover({ kind: "subcounty", name: sc.name, districtPcode: sc.district, districtId: byPcode.get(sc.district)?.districtId ?? null, districtName: dm.name, sub: dm.subRegion, region: dm.region, x: e.clientX - r.left, y: e.clientY - r.top }); }}
                  onClick={() => pin({ kind: "subcounty", name: sc.name, districtId: byPcode.get(sc.district)?.districtId ?? null, districtName: dm.name, sub: dm.subRegion, region: dm.region })} />
              );
            })}

            {/* Proportional bubbles — size = metric, colour = status */}
            {viewMode === "bubbles" && data?.districts.map((d) => {
              if (d.centroidLat == null || d.centroidLng == null) return null;
              const r = bubbleR(d[metricKey] as number | null);
              if (r <= 0) return null;
              return (
                <circle key={d.districtId} cx={proj!.px(d.centroidLng)} cy={proj!.py(d.centroidLat)} r={r}
                  fill={STATUS_META[d.status].fill} fillOpacity={0.62} stroke="#fff" strokeWidth={1 / view.scale}
                  className="cursor-pointer" onClick={() => pin({ kind: "district", d })} />
              );
            })}

            {/* School pins — auto-appear when schools have coordinates */}
            {showPins && points.map((pt: BeGeoSchoolPoint) => (
              <circle key={pt.schoolId} cx={proj!.px(pt.lng)} cy={proj!.py(pt.lat)} r={3 / view.scale} fill={PIN_FILL[pt.type] ?? "#64748b"} stroke="#fff" strokeWidth={0.6 / view.scale}><title>{pt.name}</title></circle>
            ))}

            {/* Labels — districts (small) + sub-regions (bold). White halo for legibility. */}
            {showLabels && (
              <g style={{ pointerEvents: "none" }}>
                {meta!.map((m) => (m.lat == null || m.lng == null ? null : (
                  <text key={m.pcode} x={proj!.px(m.lng)} y={proj!.py(m.lat)} textAnchor="middle"
                    fontSize={7 / view.scale} fontWeight={600} fill="#1e293b" stroke="#fff" strokeWidth={1.6 / view.scale}
                    style={{ paintOrder: "stroke" }}>{m.name}</text>
                )))}
                {/* Sub-county labels — only when zoomed in (sub-counties shown), culled to view. */}
                {showSubCounties && subCountyPaths.map((sc) => (!inView(sc.lng, sc.lat) ? null : (
                  <text key={`sc-${sc.pcode}`} x={proj!.px(sc.lng)} y={proj!.py(sc.lat)} textAnchor="middle"
                    fontSize={4.5 / view.scale} fontWeight={500} fill="#475569" stroke="#fff" strokeWidth={1.1 / view.scale}
                    style={{ paintOrder: "stroke" }}>{sc.name}</text>
                )))}
                {subRegionLabels.map((sr) => (
                  <text key={sr.name} x={sr.x} y={sr.y} textAnchor="middle"
                    fontSize={13 / view.scale} fontWeight={800} fill="#0f172a" stroke="#fff" strokeWidth={3 / view.scale}
                    style={{ paintOrder: "stroke", textTransform: "uppercase", letterSpacing: "0.04em" }}>{sr.name}</text>
                ))}
              </g>
            )}
          </g>
        </svg>

        {hover && (
          <div className="absolute z-20 pointer-events-none rounded-xl shadow-2xl ring-1 ring-black/10 overflow-hidden text-white"
            style={{ left: hover.x + 14, top: hover.y + 12, transform: `${hover.x > 520 ? "translateX(-105%)" : ""} ${hover.y > 300 ? "translateY(calc(-100% - 26px))" : ""}`.trim() || undefined, minWidth: 220, maxWidth: 270, background: "linear-gradient(160deg,#4a7aa7,#34597d)" }}>
            {hover.kind === "subcounty" ? (() => {
              const det = hover.districtId ? detailCache.current.get(hover.districtId) : undefined;
              const sc = det?.subCounties.find((s) => s.name === hover.name);
              return (
                <div className="px-3.5 py-3">
                  <div className="text-[10px] uppercase tracking-wider text-white/60 font-bold inline-flex items-center gap-1"><MapPin size={10} /> Sub-county · {hover.districtName}</div>
                  <div className="text-[14px] font-extrabold tracking-tight mt-0.5">{hover.name}</div>
                  {sc ? (
                    <>
                      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px]">
                        <HRow icon={<Building2 size={12} />} label="Schools" value={sc.schools} />
                        <HRow icon={<Briefcase size={12} />} label="Client" value={sc.clientSchools} />
                        <HRow icon={<ShieldCheck size={12} />} label="Core" value={sc.coreSchools} />
                        <HRow icon={<Network size={12} />} label="Clusters" value={sc.clusters} />
                        <HRow icon={<Gauge size={12} />} label="Core SSA" value={sc.coreAvgSsa ?? "—"} />
                        <HRow icon={<Gauge size={12} />} label="Client SSA" value={sc.clientAvgSsa ?? "—"} />
                        <HRow icon={<AlertTriangle size={12} />} label="Core crit." value={sc.coreCriticalCount} />
                        <HRow icon={<AlertTriangle size={12} />} label="Client crit." value={sc.clientCriticalCount} />
                      </div>
                      {sc.weakest && (
                        <div className="mt-2 pt-2 border-t border-white/15 text-[11px] inline-flex items-center gap-1.5"><TrendingDown size={11} className="text-rose-200" /> Weakest: <b>{sc.weakest.label}</b> ({sc.weakest.avg.toFixed(1)})</div>
                      )}
                    </>
                  ) : (
                    <div className="mt-2 space-y-1.5 text-[11.5px]">
                      <HRow icon={<Building2 size={12} />} label="District" value={hover.districtName} />
                      <HRow icon={<Layers size={12} />} label="Sub-region" value={hover.sub ?? "—"} />
                      <div className="text-[10.5px] text-white/60">{hover.districtId == null ? "No schools recorded in this district" : det ? "No schools recorded in this sub-county" : "Loading sub-county figures…"}</div>
                    </div>
                  )}
                </div>
              );
            })() : (
              <div className="px-3.5 py-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="text-[14px] font-extrabold tracking-tight leading-tight">{hover.name}</div>
                    <div className="text-[10.5px] text-white/70 mt-0.5 inline-flex items-center gap-1"><MapPin size={10} /> {hover.sub ?? "—"}{hover.region ? ` · ${hover.region}` : ""}</div>
                  </div>
                  {hover.d && <span className="shrink-0 inline-flex items-center gap-1 rounded-md bg-white/15 px-1.5 py-0.5 text-[9.5px] font-bold"><span className="w-1.5 h-1.5 rounded-full" style={{ background: STATUS_META[hover.d.status].fill }} />{STATUS_META[hover.d.status].label}</span>}
                </div>
                {hover.d ? (
                  <>
                    <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11.5px]">
                      <HRow icon={<Building2 size={12} />} label="Schools" value={hover.d.schools} />
                      <HRow icon={<Briefcase size={12} />} label="Client" value={hover.d.clientSchools} />
                      <HRow icon={<ShieldCheck size={12} />} label="Core" value={hover.d.coreSchools} />
                      <HRow icon={<Network size={12} />} label="Clusters" value={hover.d.clusters} />
                      <HRow icon={<Gauge size={12} />} label="Core SSA" value={hover.d.coreAvgSsa ?? "—"} />
                      <HRow icon={<Gauge size={12} />} label="Client SSA" value={hover.d.clientAvgSsa ?? "—"} />
                      <HRow icon={<AlertTriangle size={12} />} label="Core crit." value={hover.d.coreCriticalCount} />
                      <HRow icon={<AlertTriangle size={12} />} label="Client crit." value={hover.d.clientCriticalCount} />
                    </div>
                    {(() => {
                      const cl = detailCache.current.get(hover.d.districtId)?.clusters;
                      return (
                        <div className="mt-2 pt-2 border-t border-white/15">
                          <div className="text-[9.5px] uppercase tracking-wider text-white/60 font-bold inline-flex items-center gap-1 mb-1"><Network size={10} /> Clusters</div>
                          {cl == null ? (
                            <div className="text-[10.5px] text-white/60">Loading…</div>
                          ) : cl.length === 0 ? (
                            <div className="text-[10.5px] text-white/70">No clusters formed yet</div>
                          ) : (
                            <div className="space-y-0.5">
                              {cl.slice(0, 5).map((c) => (
                                <div key={c.id} className="flex items-center justify-between gap-2 text-[11px]">
                                  <span className="truncate inline-flex items-center gap-1"><Layers size={10} className="text-white/60 shrink-0" /> {c.name}</span>
                                  <span className="shrink-0 font-bold tabular text-white/90">{c.schools} sch.</span>
                                </div>
                              ))}
                              {cl.length > 5 && <div className="text-[10px] text-white/60">+ {cl.length - 5} more</div>}
                            </div>
                          )}
                        </div>
                      );
                    })()}
                  </>
                ) : <div className="mt-1.5 text-[10.5px] text-white/70">No schools in scope · click for geography</div>}
              </div>
            )}
          </div>
        )}
      </div>

      </section>

      {/* Desktop: inline detail panel (25%) — defaults to the whole country, switches
          to a district / sub-county on click. */}
      <aside className="hidden lg:block lg:col-span-1">
        <div className="card p-0 overflow-hidden lg:sticky lg:top-4 max-h-[78vh] overflow-y-auto">
          <DetailBody focus={focus} summary={s ?? null} detail={focusDetail} onClear={() => setFocus({ kind: "country" })} />
        </div>
      </aside>

      {/* Mobile / tablet: the same detail as a sleek floating drawer on click. */}
      {!isDesktop && focus.kind !== "country" && (
        <Modal open onClose={() => setFocus({ kind: "country" })} variant="drawer-right" size="md" dim={false}
          title={focus.kind === "district" ? focus.d.district : focus.name}
          description={focus.kind === "district" ? `${focus.d.subRegion ?? "—"} sub-region · ${focus.d.region} region` : `${focus.districtName} district · ${focus.sub ?? "—"}`}>
          <DetailBody focus={focus} summary={s ?? null} detail={focusDetail} onClear={() => setFocus({ kind: "country" })} headerless />
        </Modal>
      )}
    </div>
  );
}

// Row in the steel-blue hover card: icon · label · value (white theme).
function HRow({ icon, label, value }: { icon: ReactNode; label: string; value: ReactNode }) {
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      <span className="text-white/55 shrink-0">{icon}</span>
      <span className="text-white/70 truncate">{label}</span>
      <span className="ml-auto font-extrabold tabular shrink-0">{value}</span>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-edify-divider)] px-2.5 py-1.5">
      <div className="text-[9.5px] uppercase tracking-wide muted font-bold">{label}</div>
      <div className={cn("text-[16px] font-extrabold tabular", tone)}>{value}</div>
    </div>
  );
}

function ssaTone(v: number | null): string | undefined {
  if (v == null) return undefined;
  return v < 5 ? "text-rose-600" : v < 7 ? "text-amber-600" : "text-emerald-600";
}
function barColor(v: number): string {
  return v < 5 ? "#e11d48" : v < 7 ? "#f59e0b" : v < 9 ? "#22b07f" : "#0f7a57";
}

function SectionTitle({ children }: { children: ReactNode }) {
  return <h4 className="text-[11px] uppercase tracking-wider font-bold muted mb-2">{children}</h4>;
}

// The 8-intervention bar list (shared by country / district panels).
function InterventionBars({ interventions, scopeLabel }: { interventions: { key: string; label: string; avg: number | null }[]; scopeLabel: string }) {
  if (interventions.every((i) => i.avg == null)) return <p className="text-[12px] muted">No SSA scores yet — per-intervention performance appears once schools are assessed.</p>;
  return (
    <div className="space-y-1.5">
      {interventions.map((iv) => (
        <div key={iv.key} className="flex items-center gap-2 text-[11.5px]">
          <span className="w-[42%] shrink-0 truncate font-medium">{iv.label}</span>
          <div className="flex-1 h-2.5 rounded-full bg-[var(--color-edify-soft)] overflow-hidden">
            {iv.avg != null && <div className="h-full rounded-full" style={{ width: `${(iv.avg / 10) * 100}%`, background: barColor(iv.avg) }} />}
          </div>
          <span className={cn("w-7 text-right font-extrabold tabular", ssaTone(iv.avg))}>{iv.avg == null ? "—" : iv.avg.toFixed(1)}</span>
        </div>
      ))}
      <p className="text-[10.5px] muted pt-0.5">Average score (0–10) per intervention across {scopeLabel}.</p>
    </div>
  );
}

function StrugglingList({ weakest, scopeNoun }: { weakest: { key: string; label: string; avg: number }[]; scopeNoun: string }) {
  if (weakest.length === 0) return <p className="text-[12px] muted">No SSA scores yet — interventions appear once schools are assessed.</p>;
  return (
    <div className="space-y-1.5">
      {weakest.map((w, i) => (
        <div key={w.key} className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-rose-200 bg-rose-50/50">
          <span className="text-[12px] font-semibold inline-flex items-center gap-2"><span className="text-rose-600 font-extrabold">#{i + 1}</span> {w.label}</span>
          <span className="text-[13px] font-extrabold tabular text-rose-600">{w.avg.toFixed(1)}</span>
        </div>
      ))}
      <p className="text-[11px] muted">The interventions with the lowest {scopeNoun} SSA average — the focus for support.</p>
    </div>
  );
}

// Detail panel body — country (default) / district / sub-county. Used inline on
// desktop (75/25 split) and inside the floating drawer on mobile/tablet.
function DetailBody({ focus, summary, detail, onClear, headerless }: {
  focus: Focus; summary: BeGeoSummary | null; detail?: BeGeoDistrictDetail; onClear: () => void; headerless?: boolean;
}) {
  const head = (eyebrow: string, title: string, subtitle: string, badge?: ReactNode) => (
    <header className="px-4 py-3 border-b border-[var(--color-edify-divider)]">
      <div className="flex items-center justify-between gap-2">
        <div className="text-[10px] uppercase tracking-wider muted font-bold">{eyebrow}</div>
        {focus.kind !== "country" && <button onClick={onClear} className="text-[10.5px] font-semibold text-[var(--color-edify-primary)] hover:underline">← Country</button>}
      </div>
      <h3 className="text-[15px] font-extrabold tracking-tight mt-0.5">{title}</h3>
      <p className="text-[11.5px] muted">{subtitle}</p>
      {badge}
    </header>
  );

  // ── Country (default) ──
  if (focus.kind === "country") {
    if (!summary) return <div className="p-4 text-[12px] muted">Loading…</div>;
    return (
      <div>
        {!headerless && head("Geo-analytics", "Uganda", "Country overview — click a district for detail")}
        <div className="p-4 space-y-5">
          <section>
            <SectionTitle>Portfolio</SectionTitle>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Schools" value={summary.schools} />
              <Stat label="Client" value={summary.clientSchools} />
              <Stat label="Core" value={summary.coreSchools} />
              <Stat label="Districts" value={summary.districts} />
              <Stat label="Clusters" value={summary.clusters} />
              <Stat label="High-risk" value={summary.highRiskDistricts} tone={summary.highRiskDistricts ? "text-rose-600" : undefined} />
            </div>
          </section>
          <section>
            <SectionTitle>SSA performance</SectionTitle>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Core SSA" value={summary.coreAvgSsa ?? "—"} tone={ssaTone(summary.coreAvgSsa)} />
              <Stat label="Client SSA" value={summary.clientAvgSsa ?? "—"} tone={ssaTone(summary.clientAvgSsa)} />
              <Stat label="Core critical" value={summary.coreCriticalSchools} tone={summary.coreCriticalSchools ? "text-rose-600" : undefined} />
              <Stat label="Client critical" value={summary.clientCriticalSchools} tone={summary.clientCriticalSchools ? "text-rose-600" : undefined} />
              <Stat label="SSA pending" value={summary.ssaPending} />
            </div>
          </section>
          <section><SectionTitle>SSA by intervention</SectionTitle><InterventionBars interventions={summary.interventions} scopeLabel="all assessed schools" /></section>
          <section>
            <h4 className="text-[11px] uppercase tracking-wider font-bold muted mb-2 inline-flex items-center gap-1.5"><TrendingDown size={13} className="text-rose-500" /> Struggling nationwide</h4>
            <StrugglingList weakest={summary.weakestInterventions} scopeNoun="national" />
          </section>
          <section className="space-y-1.5"><SectionTitle>Quick actions</SectionTitle><Action href="/schools" label="View all schools" /><Action href="/coverage" label="Coverage & support needs" /></section>
        </div>
      </div>
    );
  }

  // ── Sub-county ──
  if (focus.kind === "subcounty") {
    const sc = detail?.subCounties.find((s) => s.name === focus.name);
    return (
      <div>
        {!headerless && head(`Sub-county · ${focus.districtName}`, focus.name, `${focus.sub ?? "—"} sub-region · ${focus.region ?? "—"} region`)}
        <div className="p-4 space-y-5">
          {sc ? (
            <>
              <section>
                <SectionTitle>School portfolio</SectionTitle>
                <div className="grid grid-cols-3 gap-2">
                  <Stat label="Schools" value={sc.schools} />
                  <Stat label="Client" value={sc.clientSchools} />
                  <Stat label="Core" value={sc.coreSchools} />
                  <Stat label="Clusters" value={sc.clusters} />
                  <Stat label="Core SSA" value={sc.coreAvgSsa ?? "—"} tone={ssaTone(sc.coreAvgSsa)} />
                  <Stat label="Client SSA" value={sc.clientAvgSsa ?? "—"} tone={ssaTone(sc.clientAvgSsa)} />
                  <Stat label="Core critical" value={sc.coreCriticalCount} tone={sc.coreCriticalCount ? "text-rose-600" : undefined} />
                  <Stat label="Client critical" value={sc.clientCriticalCount} tone={sc.clientCriticalCount ? "text-rose-600" : undefined} />
                </div>
              </section>
              {sc.weakest && (
                <section>
                  <h4 className="text-[11px] uppercase tracking-wider font-bold muted mb-2 inline-flex items-center gap-1.5"><TrendingDown size={13} className="text-rose-500" /> Weakest intervention</h4>
                  <div className="flex items-center justify-between gap-2 px-3 py-2 rounded-lg border border-rose-200 bg-rose-50/50">
                    <span className="text-[12px] font-semibold">{sc.weakest.label}</span>
                    <span className="text-[13px] font-extrabold tabular text-rose-600">{sc.weakest.avg.toFixed(1)}</span>
                  </div>
                </section>
              )}
            </>
          ) : (
            <p className="text-[12px] muted">{focus.districtId == null ? "No schools recorded in this district yet." : detail ? "No schools recorded in this sub-county yet." : "Loading sub-county figures…"}</p>
          )}
          <section className="space-y-1.5"><SectionTitle>Quick actions</SectionTitle><Action href={`/analytics?district=${encodeURIComponent(focus.districtName)}`} label={`Open ${focus.districtName} district`} /><Action href={`/schools?district=${encodeURIComponent(focus.districtName)}`} label="View schools in district" /></section>
        </div>
      </div>
    );
  }

  // ── District ──
  const d = focus.d;
  const clusters = detail?.clusters;
  return (
    <div>
      {!headerless && head(`${d.subRegion ?? "—"} · ${d.region}`, d.district, `${d.subRegion ?? "—"} sub-region · ${d.region} region`,
        <span className={cn("mt-1.5 inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[10.5px] font-bold border", STATUS_META[d.status].cls)}>
          {d.status === "high_risk" ? <AlertTriangle size={11} /> : d.status === "healthy" ? <ShieldCheck size={11} /> : null}{STATUS_META[d.status].label}
        </span>)}
      <div className="p-4 space-y-5">
        <section>
          <SectionTitle>School portfolio</SectionTitle>
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Schools" value={d.schools} />
            <Stat label="Client" value={d.clientSchools} />
            <Stat label="Core" value={d.coreSchools} />
            <Stat label="Clusters" value={d.clusters} />
            <Stat label="Clustered" value={d.clustered} />
            <Stat label="Unclustered" value={d.unclustered} tone={d.unclustered ? "text-rose-600" : undefined} />
          </div>
        </section>
        <section>
          <SectionTitle>SSA performance</SectionTitle>
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Core SSA" value={d.coreAvgSsa ?? "—"} tone={ssaTone(d.coreAvgSsa)} />
            <Stat label="Client SSA" value={d.clientAvgSsa ?? "—"} tone={ssaTone(d.clientAvgSsa)} />
            <Stat label="Core critical" value={d.coreCriticalCount} tone={d.coreCriticalCount ? "text-rose-600" : undefined} />
            <Stat label="Client critical" value={d.clientCriticalCount} tone={d.clientCriticalCount ? "text-rose-600" : undefined} />
            <Stat label="SSA pending" value={d.ssaPending} />
          </div>
        </section>
        <section><SectionTitle>SSA by intervention</SectionTitle><InterventionBars interventions={d.interventions} scopeLabel="the district's assessed schools" /></section>
        <section>
          <h4 className="text-[11px] uppercase tracking-wider font-bold muted mb-2 inline-flex items-center gap-1.5"><TrendingDown size={13} className="text-rose-500" /> Struggling across the district</h4>
          <StrugglingList weakest={d.weakestInterventions} scopeNoun="district-wide" />
        </section>
        <section>
          <SectionTitle>Clusters in this district {clusters && <span className="muted font-semibold">· {clusters.length}</span>}</SectionTitle>
          {clusters == null ? (
            <p className="text-[12px] muted">Loading clusters…</p>
          ) : clusters.length === 0 ? (
            <p className="text-[12px] muted">No clusters formed in this district yet. Clusters appear here once schools are grouped, each with its own SSA average and weakest intervention.</p>
          ) : (
            <div className="divide-y divide-[var(--color-edify-divider)] rounded-lg border border-[var(--color-edify-divider)] overflow-hidden">
              {clusters.map((c) => (
                <div key={c.id} className="px-3 py-2 flex items-center justify-between gap-3 text-[12px]">
                  <div className="min-w-0">
                    <div className="font-extrabold tracking-tight truncate">{c.name}</div>
                    <div className="muted text-[10.5px] truncate">{c.schools} school{c.schools === 1 ? "" : "s"}{c.weakest ? ` · weakest: ${c.weakest.label} (${c.weakest.avg.toFixed(1)})` : ""}</div>
                  </div>
                  <span className={cn("text-[14px] font-extrabold tabular shrink-0", ssaTone(c.avgSsa))}>{c.avgSsa ?? "—"}</span>
                </div>
              ))}
            </div>
          )}
        </section>
        <section>
          <SectionTitle>Execution</SectionTitle>
          <div className="grid grid-cols-3 gap-2"><Stat label="Activities done" value={d.activitiesCompleted} /><Stat label="SSA complete" value={`${d.ssaPct}%`} /></div>
        </section>
        <section className="space-y-1.5">
          <SectionTitle>Quick actions</SectionTitle>
          <Action href={`/analytics?district=${encodeURIComponent(d.district)}`} label="Filter analytics to this district" />
          <Action href={`/schools?district=${encodeURIComponent(d.district)}`} label="View schools in district" />
          <Action href={`/coverage?district=${encodeURIComponent(d.district)}`} label="View coverage & support needs" />
        </section>
      </div>
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

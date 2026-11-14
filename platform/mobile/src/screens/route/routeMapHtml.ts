/**
 * The map page the app shows in a WebView: MapLibre over OpenFreeMap's
 * keyless tiles. MapLibre is fetched from jsDelivr at an exact version and
 * checked against its SHA-384 before it runs (the same files as the npm
 * release), so no unchecked code reaches the page. The app sends the stops
 * with `window.edifyRender(json)`; the page answers taps with postMessage.
 */

export const MAPLIBRE_VERSION = '6.16.0';
const CDN = `https://cdn.jsdelivr.net/npm/maplibre-gl@${MAPLIBRE_VERSION}/dist`;
const INTEGRITY = {
  main: 'sha384-uLwQnFL74rrONqIWx/ubL4wcAtA2h08tbMDZd9U4KbQ7GhaA7S1XKepHU89UkU7C',
  worker: 'sha384-FgyfFzov+/WGwlmjlowNT14eHNk/fCYPBsD/J2FkqC+Pef7/36bn0gdsHaB/Oso/',
  css: 'sha384-S+OnE5M4U3Qc2nR0RgljGrVs06xqfRg8L7uFk/pOF5+sRuSDG4oKkqKZmFrx7w09',
} as const;
const STYLES = {
  streets: 'https://tiles.openfreemap.org/styles/liberty',
  light: 'https://tiles.openfreemap.org/styles/positron',
} as const;

/** One pin as the page draws it. */
export interface MapPin {
  id: string;
  order: string;
  name: string;
  detail: string;
  lat: number;
  lng: number;
  tone: string;
}

export interface MapScene {
  pins: MapPin[];
  /** The road line [lng, lat], or none (the stops are then joined by a dashed straight line). */
  path: [number, number][];
  legend: { label: string; tone: string }[];
  /** Join the pins with a line when there is no road line (a route); false for schools around one school. */
  join?: boolean;
  /** The pin drawn on top and named first (the school the map is about). */
  primaryId?: string;
}

export function mapHtml(): string {
  return `<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<style>
html,body,#map{margin:0;height:100%;width:100%;background:#eef2f3;font-family:-apple-system,system-ui,sans-serif}
.pin{position:relative;width:30px;height:38px;border:0;background:none;padding:0}
.drop{position:absolute;left:0;top:0;width:30px;height:30px;border-radius:50% 50% 50% 0;transform:rotate(-45deg);display:grid;place-items:center;border:2.5px solid #fff;box-shadow:0 2px 6px rgba(15,23,42,.35);color:#fff;font:700 14px system-ui}
.drop span{transform:rotate(45deg);line-height:1}
.card{position:absolute;top:-6px;left:36px;width:max-content;max-width:150px;background:#fff;border-radius:10px;padding:5px 9px;box-shadow:0 2px 8px rgba(15,23,42,.2);color:#0f172a;font:600 13px/1.25 system-ui;text-align:left}
.card small{display:block;font-weight:500;color:#334155}
.pin[data-label=left] .card{left:auto;right:36px}
.pin[data-label=below] .card{left:50%;top:40px;transform:translateX(-50%)}
.pin[data-label=above] .card{left:50%;top:auto;bottom:40px;transform:translateX(-50%)}
.pin[data-label=hidden] .card{display:none}
.ctl{position:absolute;display:flex;flex-direction:column;background:#fff;border-radius:12px;box-shadow:0 2px 8px rgba(15,23,42,.2);overflow:hidden}
.ctl button{width:46px;height:46px;border:0;background:#fff;font:600 22px system-ui;color:#0f172a}
.ctl button+button{border-top:1px solid #e2e8f0}
.legend{position:absolute;left:10px;bottom:12px;background:#fff;border-radius:12px;padding:8px 12px;box-shadow:0 2px 8px rgba(15,23,42,.2);font:500 13px system-ui;color:#0f172a}
.legend:empty{display:none}
.legend div{display:flex;align-items:center;gap:8px;padding:2px 0}
.legend i{width:12px;height:12px;border-radius:50%}
.credit{position:absolute;right:10px;bottom:66px;background:rgba(255,255,255,.85);border-radius:6px;padding:2px 6px;font:500 10px system-ui;color:#334155}
.credit a{color:inherit;text-decoration:none}
.msg{position:absolute;inset:0;display:grid;place-items:center;padding:24px;text-align:center;font:500 15px system-ui;color:#334155;background:#eef2f3}
</style></head><body><div id="map"></div>
<div class="ctl" style="left:10px;top:10px" data-overlay><button id="zin" aria-label="Zoom in">+</button><button id="zout" aria-label="Zoom out">−</button><button id="fit" aria-label="Show the whole route">◎</button></div>
<div class="ctl" style="right:10px;bottom:12px" data-overlay><button id="layers" aria-label="Change the map style">≋</button></div>
<div class="legend" id="legend" data-overlay></div>
<div class="credit" data-overlay>© <a href="https://openfreemap.org" target="_blank">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank">OpenMapTiles</a> © <a href="https://www.openstreetmap.org/copyright" target="_blank">OSM</a></div>
<script type="module">
const post = (m) => window.ReactNativeWebView ? window.ReactNativeWebView.postMessage(JSON.stringify(m)) : window.parent.postMessage(JSON.stringify(m), '*');
const checked = async (url, integrity) => { const r = await fetch(url, { integrity }); if (!r.ok) throw new Error(url); return r; };
let map, markers = [], scene = null, extent = null, style = 'streets';
const STYLES = ${JSON.stringify(STYLES)};
const overlaps = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
function place() {
  const frame = document.getElementById('map').getBoundingClientRect();
  const taken = [...document.querySelectorAll('[data-overlay]')].map((o) => o.getBoundingClientRect());
  const drops = markers.map((m) => m.getElement().querySelector('.drop').getBoundingClientRect());
  // The primary pin is named first.
  const order = markers.map((m, i) => i).sort((a, b) => (markers[b].getElement().dataset.primary ? 1 : 0) - (markers[a].getElement().dataset.primary ? 1 : 0));
  order.forEach((i) => {
    const m = markers[i];
    const pin = m.getElement(); const card = pin.querySelector('.card');
    for (const side of ['right', 'left', 'below', 'above']) {
      pin.dataset.label = side; const box = card.getBoundingClientRect();
      const inside = box.left >= frame.left + 4 && box.right <= frame.right - 4 && box.top >= frame.top + 4 && box.bottom <= frame.bottom - 4;
      if (inside && !drops.some((d, j) => j !== i && overlaps(d, box)) && !taken.some((t) => overlaps(t, box))) { taken.push(box); return; }
    }
    pin.dataset.label = 'hidden';
  });
}
function fit() {
  if (!extent) return;
  // Room for the cards over the map, never more than the map can give.
  const c = map.getContainer(); const v = Math.min(120, c.clientHeight / 4), h = Math.min(80, c.clientWidth / 5);
  map.fitBounds(extent, { padding: { top: v, bottom: v, left: h, right: h }, maxZoom: 14, duration: 300 });
}
function line() {
  if (!scene) return { type: 'FeatureCollection', features: [] };
  const road = scene.path.length > 1;
  const coords = road ? scene.path : scene.join === false ? [] : scene.pins.map((p) => [p.lng, p.lat]);
  return { type: 'FeatureCollection', features: coords.length < 2 ? [] : [{ type: 'Feature', properties: { road }, geometry: { type: 'LineString', coordinates: coords } }] };
}
function layers() {
  if (!map.getSource('route')) {
    map.addSource('route', { type: 'geojson', data: line() });
    map.addLayer({ id: 'casing', type: 'line', source: 'route', paint: { 'line-color': '#fff', 'line-width': 8 }, layout: { 'line-join': 'round', 'line-cap': 'round' } });
    map.addLayer({ id: 'road', type: 'line', source: 'route', filter: ['==', ['get', 'road'], true], paint: { 'line-color': '#1d6fe0', 'line-width': 4.5 }, layout: { 'line-join': 'round', 'line-cap': 'round' } });
    map.addLayer({ id: 'straight', type: 'line', source: 'route', filter: ['==', ['get', 'road'], false], paint: { 'line-color': '#1d6fe0', 'line-width': 3.5, 'line-dasharray': [1.5, 1.5] } });
  } else map.getSource('route').setData(line());
}
function draw(Marker, LngLatBounds) {
  markers.forEach((m) => m.remove()); markers = [];
  const bounds = new LngLatBounds();
  // The primary pin last, so it is drawn on top.
  const ordered = [...scene.pins.filter((p) => p.id !== scene.primaryId), ...scene.pins.filter((p) => p.id === scene.primaryId)];
  for (const p of ordered) {
    const el = document.createElement('button'); el.className = 'pin'; el.setAttribute('aria-label', p.order + ': ' + p.name);
    const drop = document.createElement('span'); drop.className = 'drop'; drop.style.background = p.tone;
    const n = document.createElement('span'); n.textContent = p.order; drop.append(n);
    const card = document.createElement('span'); card.className = 'card'; card.textContent = p.name;
    if (p.detail) { const s = document.createElement('small'); s.textContent = p.detail; card.append(s); }
    el.append(drop, card);
    if (p.id === scene.primaryId) el.dataset.primary = '1';
    el.addEventListener('click', (e) => { e.stopPropagation(); post({ type: 'select', id: p.id }); });
    markers.push(new Marker({ element: el, anchor: 'bottom' }).setLngLat([p.lng, p.lat]).addTo(map));
    bounds.extend([p.lng, p.lat]);
  }
  const legend = document.getElementById('legend'); legend.replaceChildren();
  for (const l of scene.legend) { const d = document.createElement('div'); const i = document.createElement('i'); i.style.background = l.tone; d.append(i, document.createTextNode(l.label)); legend.append(d); }
  extent = bounds.isEmpty() ? null : [bounds.getSouthWest().toArray(), bounds.getNorthEast().toArray()];
  layers();
  // No pins: back to the wide view, not wherever the last scene left it.
  if (extent) fit(); else map.easeTo({ center: [32.58, 0.35], zoom: 9, duration: 300 });
  setTimeout(place, 350);
}
try {
  const css = await (await checked('${CDN}/maplibre-gl.css', '${INTEGRITY.css}')).text();
  const s = document.createElement('style'); s.textContent = css; document.head.append(s);
  const main = URL.createObjectURL(await (await checked('${CDN}/maplibre-gl.mjs', '${INTEGRITY.main}')).blob());
  const worker = URL.createObjectURL(new Blob([await (await checked('${CDN}/maplibre-gl-worker.mjs', '${INTEGRITY.worker}')).text()], { type: 'text/javascript' }));
  const { Map, Marker, LngLatBounds, setWorkerUrl } = await import(main);
  setWorkerUrl(worker);
  map = new Map({ container: 'map', style: STYLES.streets, center: [32.58, 0.35], zoom: 9, attributionControl: false });
  map.on('load', () => { layers(); window.edifyRender = (json) => { scene = JSON.parse(json); draw(Marker, LngLatBounds); }; post({ type: 'ready' }); });
  map.on('moveend', () => requestAnimationFrame(place));
  document.getElementById('zin').onclick = () => map.zoomIn();
  document.getElementById('zout').onclick = () => map.zoomOut();
  document.getElementById('fit').onclick = fit;
  document.getElementById('layers').onclick = () => { style = style === 'streets' ? 'light' : 'streets'; map.setStyle(STYLES[style]); map.once('idle', () => layers()); };
} catch (e) {
  document.body.insertAdjacentHTML('beforeend', '<div class="msg">The map could not load. Your route is in the list, with every distance and time.</div>');
  post({ type: 'failed' });
}
</script></body></html>`;
}

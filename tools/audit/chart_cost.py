"""Re-render the CD performance chart with option variants and time each."""

import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "out"
keys = json.loads((OUT / "sessions.json").read_text())
PROBE = r"""
async (variant) => {
  const el = document.querySelector('#cdDashPerfChart');
  const comp = Alpine.$data(el.closest('[x-data]'));
  if (!window.__chartBase) window.__chartBase = JSON.parse(JSON.stringify(comp.chart.opts));
  const base = window.__chartBase;
  const cfg = JSON.parse(JSON.stringify(base));
  cfg.chart = cfg.chart || {};
  if (variant === 'no-animations') cfg.chart.animations = { enabled: false };
  if (variant === 'no-datalabels') cfg.dataLabels = { enabled: false };
  if (variant === 'no-anim-no-labels') { cfg.chart.animations = { enabled: false }; cfg.dataLabels = { enabled: false }; }
  if (variant === 'labels-one-series') cfg.dataLabels = Object.assign({}, cfg.dataLabels, { enabledOnSeries: [2] });
  if (variant === 'no-markers') cfg.markers = { size: 0 };
  if (variant === 'no-tooltip-legend') { cfg.legend = { show: false }; cfg.tooltip = { enabled: false }; }
  const times = [];
  for (let i = 0; i < 3; i++) {
    if (comp.chart) comp.chart.destroy();
    await new Promise(r => setTimeout(r, 60));
    const t = performance.now();
    comp.chart = window.EdifyChartSystem._renderDetachedNow(el, cfg);
    await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
    times.push(Math.round(performance.now() - t));
  }
  const svgText = el.querySelectorAll('text').length;
  return { variant, times, min: Math.min(...times), texts: svgText, points: (base.labels || []).length, series: (base.series || []).length, anim: JSON.stringify(base.chart && base.chart.animations), dl: JSON.stringify(base.dataLabels) };
}
"""
with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies(
        [{"name": "sessionid", "value": keys["cd"], "domain": "localhost", "path": "/"}]
    )
    page = ctx.new_page()
    page.goto("http://localhost:8000/dashboard?view=operations", wait_until="load")
    page.wait_for_timeout(2500)
    for v in (
        "as-is",
        "no-animations",
        "no-datalabels",
        "labels-one-series",
        "no-markers",
        "no-tooltip-legend",
        "as-is",
    ):
        r = page.evaluate(PROBE, v)
        print(
            f"{v:20s} min {r['min']:4d}ms  runs={r['times']}  texts={r['texts']} points={r['points']} series={r['series']}"
            + (f"  anim={r['anim']} dl={r['dl']}" if v == "as-is" else "")
        )
    b.close()

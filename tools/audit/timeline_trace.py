"""Chrome timeline trace: where the main thread goes (style, layout, script, parse)."""
import json, sys
from collections import defaultdict
from pathlib import Path
from playwright.sync_api import sync_playwright
OUT = Path(__file__).resolve().parent / "out"
role, url = sys.argv[1], sys.argv[2]
keys = json.loads((OUT / "sessions.json").read_text())
events = []
with sync_playwright() as p:
    b = p.chromium.launch(); ctx = b.new_context(viewport={"width": 1440, "height": 900})
    ctx.add_cookies([{"name": "sessionid", "value": keys[role], "domain": "localhost", "path": "/"}])
    page = ctx.new_page(); cdp = ctx.new_cdp_session(page)
    cdp.on("Tracing.dataCollected", lambda d: events.extend(d["value"]))
    done = []
    cdp.on("Tracing.tracingComplete", lambda d: done.append(1))
    cdp.send("Tracing.start", {"categories": "devtools.timeline,disabled-by-default-devtools.timeline,disabled-by-default-devtools.timeline.stack,blink.user_timing", "transferMode": "ReportEvents"})
    page.goto("http://localhost:8000" + url, wait_until="load"); page.wait_for_timeout(2500)
    cdp.send("Tracing.end")
    while not done: page.wait_for_timeout(100)
    css = page.evaluate("Array.from(document.styleSheets).map(s => { let n = 0; try { n = s.cssRules.length } catch (e) {} return [(s.href || 'inline').split('/').slice(-1)[0].split('?')[0], n] })")
    b.close()
by = defaultdict(float); count = defaultdict(int); top = []
for e in events:
    if e.get("ph") != "X" or "dur" not in e: continue
    name = e["name"]; dur = e["dur"] / 1000
    if name in ("UpdateLayoutTree", "Layout", "FunctionCall", "EvaluateScript", "ParseHTML", "ParseAuthorStyleSheet", "Paint", "PrePaint", "HitTest", "TimerFire", "EventDispatch", "v8.compile", "Animation", "RunMicrotasks", "XHRReadyStateChange"):
        by[name] += dur; count[name] += 1
        if dur > 20:
            a = e.get("args", {}).get("data", {}) or e.get("args", {}).get("beginData", {}) or {}
            detail = a.get("url", "") or a.get("functionName", "") or ""
            detail = detail.split("/")[-1].split("?")[0][:40]
            st = a.get("stackTrace") or []
            if st: detail += " <- " + ",".join(f"{f.get('functionName') or '?'}@{f.get('url','').split('/')[-1].split('?')[0][:18]}:{f.get('lineNumber')}" for f in st[:2])
            top.append((dur, name, e["ts"], detail, a.get("elementCount", ""), a.get("dirtyObjects", "") or a.get("totalObjects", "")))
agg = defaultdict(lambda: [0.0, 0])
for e in events:
    if e.get("ph") != "X" or e["name"] not in ("UpdateLayoutTree", "Layout") or "dur" not in e: continue
    a = e.get("args", {}).get("beginData", {}) or e.get("args", {}).get("data", {}) or {}
    st = a.get("stackTrace") or []
    origin = ",".join(f"{f.get('functionName') or '?'}@{f.get('url','').split('/')[-1].split('?')[0][:20]}:{f.get('lineNumber')}" for f in st[:2]) or "(no stack)"
    agg[(e["name"], origin)][0] += e["dur"] / 1000; agg[(e["name"], origin)][1] += 1
print("style/layout by origin (ms, count):")
for (name, origin), (ms, n) in sorted(agg.items(), key=lambda kv: -kv[1][0])[:14]:
    print(f"  {ms:6.0f}ms x{n:3d}  {name:16s} {origin}")
print("totals (ms):", {k: (round(v), count[k]) for k, v in sorted(by.items(), key=lambda kv: -kv[1])})
print("stylesheets (rules):", css)
t0 = min(e["ts"] for e in events if e.get("ph") == "X") if events else 0
for dur, name, ts, detail, ec, dirty in sorted(top, key=lambda t: t[2]):
    print(f"  +{(ts - t0)/1000:6.0f}ms  {dur:6.1f}ms  {name:18s} {detail}  {('elements='+str(ec)) if ec else ''} {('dirty='+str(dirty)) if dirty else ''}")

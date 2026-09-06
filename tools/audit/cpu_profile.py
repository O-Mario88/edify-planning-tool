"""CPU-profile page loads and name the functions behind long tasks."""

import json
import sys
from collections import defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000"
SCRATCH = Path(__file__).resolve().parent / "out"


def main():
    role = sys.argv[1]
    pages = sys.argv[2:]
    keys = json.loads((SCRATCH / "sessions.json").read_text())
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.add_cookies([{"name": "sessionid", "value": keys[role], "domain": "localhost", "path": "/"}])
        page = ctx.new_page()
        for url in pages:
            cdp = ctx.new_cdp_session(page)
            cdp.send("Profiler.enable")
            cdp.send("Profiler.setSamplingInterval", {"interval": 500})
            cdp.send("Profiler.start")
            page.goto(BASE + url, wait_until="load")
            page.wait_for_timeout(2500)
            profile = cdp.send("Profiler.stop")["profile"]
            cdp.detach()
            nodes = {n["id"]: n for n in profile["nodes"]}
            self_time = defaultdict(float)
            deltas = profile.get("timeDeltas", [])
            samples = profile.get("samples", [])
            for sample, delta in zip(samples, deltas):
                n = nodes[sample]["callFrame"]
                key = (n["functionName"] or "(anonymous)", n["url"].split("/")[-1].split("?")[0][:40], n.get("lineNumber", 0))
                self_time[key] += delta / 1000.0
            total = sum(self_time.values())
            top = sorted(self_time.items(), key=lambda kv: -kv[1])[:12]
            print(f"\n### {url} sampled {total:.0f}ms")
            for (fn, src, line), ms in top:
                if ms < 15 or fn in ("(root)", "(idle)", "(program)", "(garbage collector)"):
                    continue
                print(f"  {ms:6.0f}ms  {fn}  [{src}:{line}]")
        browser.close()


if __name__ == "__main__":
    main()

"""Before/after screenshots of the local web, compared pixel by pixel
(docs/migration/187). It signs in to the LOCAL web only, reads pages, and
writes nothing anywhere but the folder it is given.

    VISUAL_PASSWORD=<local seed password> python platform/tools/visual-check/visual_check.py \\
        capture --out <folder> [--roles CCEO,Admin] [--pages /home,/dashboard] \\
        [--sizes desktop,phone,narrow,tablet] [--theme dark] [--css-root <public dir>]
    python platform/tools/visual-check/visual_check.py compare <before> <after> [--tolerance 8]

Animations and the caret are frozen, so two captures of the same code match.
--css-root serves every /static/**/*.css from another tree's public folder,
to preview a stylesheet change before it is committed. compare reports each
screen that differs: its pixel count, how many differ by more than the
tolerance, and where; a screen counts as changed only when some pixel
differs by more than the tolerance (anti-aliasing moves a few pixels by
less).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ui-sweep"))

SIZES = {
    "desktop": (1440, 900),
    "tablet": (768, 1024),
    "phone": (390, 844),
    "narrow": (320, 640),
}
FREEZE = "*,*::before,*::after{animation:none!important;transition:none!important;caret-color:transparent!important}"
LOCAL = {"localhost", "127.0.0.1", "::1"}


def settle(page, go) -> None:
    """Load, then wait for the network to go quiet; a page that keeps a live
    connection open (the realtime stream) never does, so after the wait it is
    taken as it stands."""
    go()
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001 - a live connection keeps the network busy
        pass
    page.wait_for_timeout(1500)


def sign_in(page, base: str, email: str, password: str) -> None:
    """Sign in, and make sure it took: a capture of the sign-in page in place
    of the page asked for is never a screenshot of that page."""
    for attempt in range(2):
        settle(page, lambda: page.goto(base + "/login", wait_until="load"))
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', password)
        page.click('form[action="/auth/sign-in"] button[type="submit"]')
        try:
            page.wait_for_url(lambda url: urlparse(url).path != "/login", timeout=30000)
            settle(page, lambda: None)
            return
        except Exception:  # noqa: BLE001 - tried again once, then refused
            page.wait_for_timeout(5000 * (attempt + 1))
    raise SystemExit(
        f"{email} could not sign in to {base}: no screenshot was taken for it"
    )


def capture(args) -> None:
    import sweep
    from playwright.sync_api import sync_playwright

    if urlparse(args.base).hostname not in LOCAL:
        raise SystemExit("refused: the base must be this machine")
    password = os.environ.get("VISUAL_PASSWORD", "")
    if not password:
        raise SystemExit("VISUAL_PASSWORD is required (the local seed password)")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    roles = args.roles.split(",") if args.roles else list(sweep.ACCOUNTS)
    pages = args.pages.split(",")
    manifest = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for role in roles:
            for size in args.sizes.split(","):
                w, h = SIZES[size]
                ctx = browser.new_context(
                    viewport={"width": w, "height": h},
                    device_scale_factor=1,
                    reduced_motion="reduce",
                )
                page = ctx.new_page()
                # A development server compiles a page on its first load.
                page.set_default_timeout(90000)
                if args.css_root:
                    root = Path(args.css_root)

                    def serve(route, request, root=root):
                        path = urlparse(request.url).path
                        f = root / path.lstrip("/")
                        if path.startswith("/static/") and f.exists():
                            route.fulfill(
                                status=200, content_type="text/css", body=f.read_text()
                            )
                        else:
                            route.continue_()

                    page.route("**/static/**/*.css*", serve)
                sign_in(page, args.base, sweep.ACCOUNTS[role], password)
                for path in pages:
                    settle(
                        page,
                        lambda path=path: page.goto(
                            args.base + path, wait_until="load"
                        ),
                    )
                    if urlparse(page.url).path == "/login":
                        raise SystemExit(
                            f"{role} was signed out before {path}: no screenshot was taken"
                        )
                    page.add_style_tag(content=FREEZE)
                    if args.theme == "dark":
                        page.evaluate(
                            "document.documentElement.classList.add('theme-dark')"
                        )
                    page.wait_for_timeout(250)
                    name = f"{role.replace(' ', '_')}_{size}_{path.strip('/').replace('/', '_') or 'root'}.png"
                    page.screenshot(path=str(out / name), full_page=True)
                    manifest.append(
                        {
                            "file": name,
                            "role": role,
                            "size": size,
                            "path": path,
                            "landed": urlparse(page.url).path,
                        }
                    )
                ctx.close()
        browser.close()
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"{len(manifest)} screens in {out}")


def compare(args) -> int:
    from PIL import Image, ImageChops

    before, after = Path(args.before), Path(args.after)
    changed = 0
    shots = sorted(before.glob("*.png"))
    for a in shots:
        b = after / a.name
        if not b.exists():
            print(f"MISSING {a.name}")
            changed += 1
            continue
        ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
        if ia.size != ib.size:
            print(f"SIZE {a.name} {ia.size} -> {ib.size}")
            changed += 1
            continue
        grey = ImageChops.difference(ia, ib).convert("L")
        hist = grey.histogram()
        moved = sum(hist[1:])
        strong = sum(hist[args.tolerance + 1 :])
        if strong:
            box = grey.point(lambda v, t=args.tolerance: 255 if v > t else 0).getbbox()
            print(
                f"CHANGED {a.name}: {moved} px differ, {strong} by more than {args.tolerance}, at {box}"
            )
            changed += 1
        elif moved:
            print(f"noise   {a.name}: {moved} px differ by {args.tolerance} or less")
    print(f"{changed} of {len(shots)} screens changed")
    return 1 if changed else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--base", default="http://localhost:3000")
    cap.add_argument("--out", required=True)
    cap.add_argument("--roles", default="")
    cap.add_argument("--pages", default="/home")
    cap.add_argument("--sizes", default="desktop,phone")
    cap.add_argument("--theme", default="light")
    cap.add_argument("--css-root", default="")
    cmp = sub.add_parser("compare")
    cmp.add_argument("before")
    cmp.add_argument("after")
    cmp.add_argument("--tolerance", type=int, default=8)
    args = parser.parse_args()
    if args.command == "capture":
        capture(args)
        return 0
    return compare(args)


if __name__ == "__main__":
    sys.exit(main())

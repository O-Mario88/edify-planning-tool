#!/usr/bin/env python3
"""Golden-master snapshots of every page, per role, for parity proofs.

A performance change is only acceptable when it changes nothing a user can see
or receive. This records what each route returns to each role — the status, the
redirect target, and the response body with its per-request noise masked — so a
second build can be compared against the first, byte for byte.

Identical HTML against the same unchanged CSS and JavaScript renders the same
pixels, so a clean comparison is both the functional and the visual parity
proof for the server-rendered surface. Exports are compared by content: an
.xlsx by its sheet XML (the zip's own timestamps masked), CSV and JSON as text.

    # the baseline build, on a fresh copy of the database
    scripts/parity_snapshot.py capture --out /tmp/parity/base
    # the candidate build, on another fresh copy of the same database
    scripts/parity_snapshot.py capture --out /tmp/parity/final
    scripts/parity_snapshot.py compare /tmp/parity/base /tmp/parity/final

`--extra` adds query-string variants (tabs, pages, periods, HTMX fragments) for
the routes a change touches; `--only` narrows the route list with a regex.

Run it against disposable copies of a seeded database, never production: some
GET routes stamp last-seen times, so each capture needs its own fresh copy.
"""

from __future__ import annotations

import argparse
import difflib
import gzip
import hashlib
import io
import json
import os
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# Per-request values that differ between two runs of the same build on the
# same data. Everything else must match exactly.
_MASKS = (
    # CSRF tokens (form fields, meta tags, hx-headers JSON, JS strings).
    (re.compile(rb"(csrfmiddlewaretoken\"?\s+value=\")[^\"]+"), rb"\1<csrf>"),
    (re.compile(rb"(name=\"csrf-token\"\s+content=\")[^\"]+"), rb"\1<csrf>"),
    (re.compile(rb"(X-CSRFToken\\?\"?\s*:\s*\\?[\"'])[A-Za-z0-9]+"), rb"\1<csrf>"),
    (
        re.compile(rb"(csrf[_-]?token\"?\s*[:=]\s*[\"'])[A-Za-z0-9]+", re.I),
        rb"\1<csrf>",
    ),
    (re.compile(rb"(X-CSRFTOKEN\"\]\s*=\s*\")[A-Za-z0-9]+", re.I), rb"\1<csrf>"),
    # A fresh authenticator-app secret is drawn for every enrolment page view.
    (re.compile(rb"(secret=)[A-Z2-7]+"), rb"\1<totp>"),
    (re.compile(rb"(data-app-secret>)[A-Z2-7 ]+"), rb"\1<totp>"),
    # CSP nonces and request correlation ids.
    (re.compile(rb"nonce=\"[^\"]+\""), rb'nonce="<nonce>"'),
    (re.compile(rb"\b[0-9a-f]{32}\b"), rb"<hex32>"),
    # Wall-clock times with seconds (dates are stable within one day).
    (
        re.compile(rb"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:?\d\d)?"),
        rb"<iso-ts>",
    ),
    (re.compile(rb"\b\d\d:\d\d:\d\d\b"), rb"<hh:mm:ss>"),
    # Minute stamps ("Updated 20:27", "Generated ... 20:28 EAT"): two captures
    # of the same build an hour apart differ in these and nothing else.
    (re.compile(rb"\b\d\d:\d\d\b"), rb"<hh:mm>"),
    # Relative ages ("3 minutes ago", "just now").
    (
        re.compile(
            rb"\b\d+(?:\xc2\xa0)?\s?(?:second|minute|min|hour)s?(?:,\s*\d+\s?\w+)?\s+ago\b"
        ),
        rb"<ago>",
    ),
    # Build/release stamps on static URLs stay; the service worker cache key does too.
)


_CUID = re.compile(rb"\bc([0-9a-z]{8})[0-9a-z]{12,16}\b")


def mask(body: bytes, created_after_ms: int = 0) -> bytes:
    for pattern, replacement in _MASKS:
        body = pattern.sub(replacement, body)
    if created_after_ms:
        # Records a GET created during this capture (lazily opened drafts,
        # notifications) carry fresh ids on every run. A CUID encodes its
        # creation time, so ids minted after the capture began are masked and
        # every id that already existed in the database is still compared.
        def fresh(match):
            try:
                minted = int(match.group(1), 36)
            except ValueError:
                return match.group(0)
            return b"<new-id>" if minted >= created_after_ms else match.group(0)

        body = _CUID.sub(fresh, body)
    return body


def normalise_xlsx(data: bytes) -> bytes:
    """Sheet, style and shared-string XML of a workbook, docProps masked."""
    out = io.BytesIO()
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for name in sorted(zf.namelist()):
                if name.startswith("docProps/"):
                    continue
                out.write(b"== " + name.encode() + b"\n")
                out.write(zf.read(name))
                out.write(b"\n")
    except zipfile.BadZipFile:
        return data
    return out.getvalue()


def body_of(response, created_after_ms: int = 0) -> bytes:
    if getattr(response, "streaming", False):
        data = b"".join(response.streaming_content)
    else:
        data = response.content
    ctype = response.get("Content-Type", "")
    if "spreadsheetml" in ctype or data[:2] == b"PK":
        data = normalise_xlsx(data)
    return mask(data, created_after_ms)


def key_for(role: str, url: str, htmx: bool) -> str:
    raw = f"{role} {'HX ' if htmx else ''}{url}"
    return hashlib.sha1(raw.encode(), usedforsecurity=False).hexdigest()[:16]


def capture(args) -> int:
    import django

    django.setup()
    from django.contrib.auth import get_user_model
    from django.test import Client

    sys.path.insert(0, str(ROOT / "scripts"))
    from route_timing_sweep import ROLE_ACCOUNTS, argument_free_routes

    wanted = [r for r in (args.roles or "").split(",") if r]
    roles = {k: v for k, v in ROLE_ACCOUNTS.items() if not wanted or k in wanted}
    routes = argument_free_routes()
    if args.only:
        routes = [r for r in routes if re.search(args.only, r)]
    extras = [e for e in (args.extra or "").split(" ") if e]
    urls = [(r, False) for r in routes] + [(e, False) for e in extras]
    if args.htmx:
        urls += [(u, True) for u, _ in list(urls)]

    import time

    started_ms = int(time.time() * 1000)
    out = pathlib.Path(args.out)
    (out / "bodies").mkdir(parents=True, exist_ok=True)
    index = []
    User = get_user_model()
    for role, email in roles.items():
        user = User.objects.filter(email=email).first()
        if user is None:
            print(f"skip {role}: no account {email}", file=sys.stderr)
            continue
        client = Client(raise_request_exception=False)
        client.force_login(user)
        for url, htmx in urls:
            headers = {"HTTP_ACCEPT": "text/html"}
            if htmx:
                headers["HTTP_HX_REQUEST"] = "true"
            try:
                response = client.get(url, **headers)
                status = response.status_code
                body = body_of(response, started_ms)
                location = response.get("Location", "")
                hx = {
                    k: response.get(k, "")
                    for k in ("HX-Redirect", "HX-Trigger", "HX-Push-Url", "HX-Retarget")
                    if response.get(k)
                }
                ctype = response.get("Content-Type", "")
            except Exception as exc:  # noqa: BLE001
                status, body, location, hx, ctype = (
                    "EXC",
                    repr(exc).encode(),
                    "",
                    {},
                    "",
                )
            key = key_for(role, url, htmx)
            with gzip.open(out / "bodies" / f"{key}.gz", "wb") as sink:
                sink.write(body)
            index.append(
                {
                    "key": key,
                    "role": role,
                    "url": url,
                    "htmx": htmx,
                    "status": status,
                    "location": location,
                    "hx": hx,
                    "content_type": ctype,
                    "sha": hashlib.sha256(body).hexdigest(),
                    "bytes": len(body),
                }
            )
    (out / "index.json").write_text(json.dumps(index, indent=0))
    print(f"captured {len(index)} responses into {out}")
    return 0


def compare(args) -> int:
    a_dir, b_dir = pathlib.Path(args.a), pathlib.Path(args.b)
    a = {r["key"]: r for r in json.loads((a_dir / "index.json").read_text())}
    b = {r["key"]: r for r in json.loads((b_dir / "index.json").read_text())}
    ignore = re.compile(args.ignore) if args.ignore else None
    missing = sorted(set(a) - set(b))
    added = sorted(set(b) - set(a))
    diffs = []
    for key in sorted(set(a) & set(b)):
        ra, rb = a[key], b[key]
        if ignore and ignore.search(ra["url"]):
            continue
        fields = [
            f
            for f in ("status", "location", "hx", "content_type", "sha")
            if ra[f] != rb[f]
        ]
        if fields:
            diffs.append((ra, rb, fields))
    print(
        f"compared {len(set(a) & set(b))} responses: {len(diffs)} differ, "
        f"{len(missing)} only in {a_dir.name}, {len(added)} only in {b_dir.name}"
    )
    for ra, rb, fields in diffs[: args.limit]:
        print(
            f"\n--- {ra['role']} {'HX ' if ra['htmx'] else ''}{ra['url']}: {', '.join(fields)}"
        )
        if "status" in fields or "location" in fields:
            print(
                f"    {ra['status']} {ra['location']}  ->  {rb['status']} {rb['location']}"
            )
        if "sha" in fields:
            with gzip.open(a_dir / "bodies" / f"{ra['key']}.gz") as fa:
                la = fa.read().decode("utf-8", "replace").splitlines()
            with gzip.open(b_dir / "bodies" / f"{rb['key']}.gz") as fb:
                lb = fb.read().decode("utf-8", "replace").splitlines()
            for n, line in enumerate(difflib.unified_diff(la, lb, lineterm="", n=1)):
                if n > args.lines:
                    print("    ...")
                    break
                print("    " + line[:220])
    for key in missing[:20]:
        print(f"only in {a_dir.name}: {a[key]['role']} {a[key]['url']}")
    for key in added[:20]:
        print(f"only in {b_dir.name}: {b[key]['role']} {b[key]['url']}")
    return 1 if (diffs or missing or added) else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("--out", required=True)
    cap.add_argument("--only", default="")
    cap.add_argument("--roles", default=os.environ.get("SWEEP_ROLES", ""))
    cap.add_argument("--extra", default="", help="space-separated extra URLs")
    cap.add_argument(
        "--htmx", action="store_true", help="also request each URL as HTMX"
    )
    cmp_ = sub.add_parser("compare")
    cmp_.add_argument("a")
    cmp_.add_argument("b")
    cmp_.add_argument("--ignore", default="", help="regex of URLs to leave out")
    cmp_.add_argument("--limit", type=int, default=40)
    cmp_.add_argument("--lines", type=int, default=30)
    args = parser.parse_args()
    return capture(args) if args.cmd == "capture" else compare(args)


if __name__ == "__main__":
    sys.exit(main())

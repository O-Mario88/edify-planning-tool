"""The coverage ledger (docs/migration/185): every user-facing surface, for
every role that may open it, on every platform it is drawn on, with its
primary task, the proposed change, its acceptance check and its status.

    python platform/tools/coverage-ledger/build.py --probe <probe output> \\
        --native <native paths json> [--status <status json>]

Sources, reconciled:
  docs/platform-page-inventory.json        every routed page and fragment
  docs/migration/179-stage-a/permissions-matrix.csv  route x role access
  the Go coverage probe's output           which routes Go draws (GO), which
                                           are detail routes (DETAIL), and the
                                           rest (the existing web's fallback)
  the app's native page paths              (apps.mobile_feed NATIVE_PAGES)
  platform/web/src/app                     Next routes drawn by their own page
  routes.json (beside this file)           the owner brief's named routes
  status.json (beside this file)           what has been verified or changed

Writes docs/migration/185-coverage-ledger.json and the summary in
docs/migration/185-coverage-ledger.md. Reads files only.
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
PLATFORMS = {"desktop-web": "1440x900", "phone-web": "390x844 (also 320, tablet)", "native": "device"}
STATUSES = ("pending", "verified as-is", "changed and verified", "blocked")


def canonical(route: str) -> str:
    """A trailing-slash twin is an alias of the route without it."""
    return route.rstrip("/") or "/"


def next_routes() -> set[str]:
    app = ROOT / "platform/web/src/app"
    out = set()
    for page in app.rglob("page.tsx"):
        rel = page.parent.relative_to(app).as_posix()
        parts = [p for p in rel.split("/") if not (p.startswith("(") and p.endswith(")"))]
        if parts and parts[0].startswith("[..."):
            continue
        route = "/" + "/".join(re.sub(r"^\[(.+)\]$", r"<\1>", p) for p in parts)
        out.add(canonical(route))
    return out


def probe(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text().splitlines():
        m = re.match(r"^(GO|DETAIL|STATIC|ERR)\s+(\S+)", line)
        if m:
            out.setdefault(canonical(m.group(2)), m.group(1))
    return out


def permissions() -> dict[str, list[str]]:
    with open(ROOT / "docs/migration/179-stage-a/permissions-matrix.csv") as f:
        rows = list(csv.reader(f))
    roles = rows[0][1:]
    return {canonical(r[0]): [role for role, v in zip(roles, r[1:]) if v.strip() == "1"] for r in rows[1:]}


def parent_of(route: str, pages: list[str]) -> str:
    best = ""
    for p in pages:
        if p != "/" and (route == p or route.startswith(p + "/")) and len(p) > len(best):
            best = p
    return best or "/"


def build(args) -> dict:
    inventory = json.loads((ROOT / "docs/platform-page-inventory.json").read_text())["pages"]
    named = json.loads((HERE / "routes.json").read_text())
    status_file = Path(args.status) if args.status else HERE / "status.json"
    status = json.loads(status_file.read_text()) if status_file.exists() else {}
    served = probe(Path(args.probe))
    native = {canonical(p) for p in json.loads(Path(args.native).read_text())}
    native |= {"/home", "/schools"}
    nexts = next_routes()
    access = permissions()

    full = [p for p in inventory if p.get("page_type") != "interaction-fragment"]
    fragments = [p for p in inventory if p.get("page_type") == "interaction-fragment"]
    surfaces: dict[str, dict] = {}
    for p in full:
        route = canonical(p["route"])
        s = surfaces.setdefault(route, {"route": route, "aliases": [], "ids": [], "title": p.get("page_title", ""),
                                        "page_type": p.get("page_type", ""), "task": p.get("primary_user_decision") or p.get("purpose", "")})
        s["ids"].append(p.get("page_id", ""))
        if p["route"] != route:
            s["aliases"].append(p["route"])
    gaps = []
    # Routes the Next app or the Go probe know that the inventory does not.
    # A detail route the probe lists (an action endpoint, a transition) belongs
    # under the workflow that posts to it, not here.
    drawn_by_go = [r for r, kind in served.items() if kind in ("GO", "ERR")]
    for route, source in sorted([(r, "Next page") for r in nexts] + [(r, "Go probe") for r in drawn_by_go]):
        if route not in surfaces:
            surfaces[route] = {"route": route, "aliases": [], "ids": [], "title": "", "page_type": "",
                               "task": "(not in the page inventory)"}
            gaps.append({"route": route, "gap": f"not in the page inventory ({source} knows it)"})
    full_routes = sorted(surfaces)

    rows = []
    for route, s in sorted(surfaces.items()):
        roles = access.get(route)
        if roles is None:
            gaps.append({"route": route, "gap": "not in the permissions matrix: roles taken from the page's own gate when it is checked"})
            roles = ["(unmapped)"]
        spec = named.get(route, {})
        drawn = "next-page" if route in nexts else {"GO": "go", "DETAIL": "go-detail", "ERR": "go"}.get(served.get(route, ""), "django-fallback")
        for role in roles:
            for platform, viewport in PLATFORMS.items():
                if platform == "native" and route not in native:
                    continue
                key = f"{route}|{role}|{platform}"
                st = status.get(key) or status.get(f"{route}|*|{platform}") or status.get(f"{route}|*|*") or {}
                rows.append({
                    "key": key, "route": route, "aliases": s["aliases"], "inventory_ids": s["ids"], "role": role,
                    "country_portfolio": "Uganda (seeded); other countries: no seeded dataset",
                    "platform": platform, "viewport": viewport, "drawn_by": drawn,
                    "primary_task": s["task"], "observation": st.get("observation", spec.get("observation", "")),
                    "proposed_change": spec.get("change", "Lead with the record, status and next action; verify populated and empty states."),
                    "acceptance": spec.get("acceptance", "Opens for this role with its data scope; primary task reachable in the first viewport."),
                    "implementation": st.get("implementation", ""), "test": st.get("test", ""), "evidence": st.get("evidence", ""),
                    "status": st.get("status", "pending"),
                })

    drawers = []
    for f in fragments:
        route = f["route"]
        if not re.search(r"drawer|modal|dialog", route + " " + f.get("page_title", ""), re.I):
            continue
        key = f"{canonical(route)}|drawer"
        st = status.get(key, {})
        drawers.append({"key": key, "drawer": route, "parent": parent_of(canonical(route), full_routes),
                        "checks": "open, validation, save, failure and retry, return to parent with focus",
                        "status": st.get("status", "pending"), "evidence": st.get("evidence", "")})
    return {"rows": rows, "drawers": drawers, "gaps": gaps, "surfaces": len(surfaces)}


def summary(ledger: dict) -> str:
    rows = ledger["rows"]
    by_status = collections.Counter(r["status"] for r in rows)
    by_platform = collections.defaultdict(collections.Counter)
    by_role = collections.defaultdict(collections.Counter)
    for r in rows:
        by_platform[r["platform"]][r["status"]] += 1
        by_role[r["role"]][r["status"]] += 1
    head = "| | " + " | ".join(STATUSES) + " |\n|---|" + "---|" * len(STATUSES) + "\n"
    def table(groups):
        return head + "".join(f"| {k} | " + " | ".join(str(c[s]) for s in STATUSES) + " |\n" for k, c in sorted(groups.items()))
    drawer_status = collections.Counter(d["status"] for d in ledger["drawers"])
    return (
        "# 185 · Coverage ledger (generated)\n\n"
        "Generated by `platform/tools/coverage-ledger/build.py`; do not edit by hand. "
        "Rows are surface × role × platform; statuses are pending / verified as-is / "
        "changed and verified / blocked.\n\n"
        f"Surfaces: {ledger['surfaces']} canonical routes (trailing-slash twins folded in as aliases). "
        f"Rows: {len(rows)}. Drawers and dialogs linked to a parent: {len(ledger['drawers'])}. "
        f"Gaps: {len(ledger['gaps'])}.\n\n"
        "## By status\n\n" + "".join(f"- {s}: {by_status[s]}\n" for s in STATUSES)
        + "\n## By platform\n\n" + table(by_platform)
        + "\n## By role\n\n" + table(by_role)
        + "\n## Drawers\n\n" + "".join(f"- {s}: {drawer_status[s]}\n" for s in STATUSES)
        + "\n## Gaps\n\n" + "".join(f"- `{g['route']}`: {g['gap']}\n" for g in ledger["gaps"][:60])
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe", required=True)
    parser.add_argument("--native", required=True)
    parser.add_argument("--status")
    args = parser.parse_args()
    ledger = build(args)
    (ROOT / "docs/migration/185-coverage-ledger.json").write_text(json.dumps(ledger, indent=1, ensure_ascii=False) + "\n")
    (ROOT / "docs/migration/185-coverage-ledger.md").write_text(summary(ledger))
    print(f"{ledger['surfaces']} surfaces, {len(ledger['rows'])} rows, {len(ledger['drawers'])} drawers, {len(ledger['gaps'])} gaps")


if __name__ == "__main__":
    main()

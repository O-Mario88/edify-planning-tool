"""Every interactive control in the templates, with its route, request and test evidence.

The page inventory answers "which pages exist"; this answers "which controls
exist on them, what each one asks the server to do, and what automated
evidence exercises it". It is built from the templates and the URL resolver,
committed as ``docs/platform-interaction-inventory.json``, and a test fails when
the live platform and the committed manifest disagree — so a control added
without being inventoried fails CI, and a control added with no test evidence
raises the untested count past its ceiling (test_interaction_inventory).

Evidence levels, strongest first. They say what was exercised, not that a
workflow passed:

* ``request-tested`` — the control's destination route is requested by a
  Django test or a browser spec.
* ``browser-rendered`` — the control is on a page the authenticated route
  audit opens for every permitted role (console errors, page errors, pending
  requests and unnamed controls fail that audit), but its own request is not
  exercised.
* ``page-tested`` — a Django test requests a page that renders the control.
* ``none`` — no automated evidence.

Declarations are static: a template branch or a shared component counts once
where it is written, not once per rendered page.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.urls import Resolver404, resolve

PROJECT_ROOT = Path(settings.BASE_DIR)
TEMPLATE_ROOT = PROJECT_ROOT / "templates"
MANIFEST = PROJECT_ROOT / "docs" / "platform-interaction-inventory.json"

VOID = {
    "input",
    "img",
    "br",
    "hr",
    "meta",
    "link",
    "source",
    "area",
    "base",
    "embed",
    "param",
    "wbr",
}
CONTROL_TAGS = {"button", "a", "input", "select", "textarea", "summary"}
HTMX_METHODS = ("hx-get", "hx-post", "hx-put", "hx-patch", "hx-delete")
STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
HIGH_CONSEQUENCE = re.compile(
    r"\b(delete|remove|cancel|reject|return|withdraw|archive|close|reopen|"
    r"decline|revoke|disburse|pay|paid|approve|verify|confirm|submit|reset|"
    r"purge|deactivate|lock|unlock|send|publish|clear|refund|reimburse)\b",
    re.I,
)
_TEMPLATE_EXPR = re.compile(r"{{.*?}}|{%.*?%}", re.S)
_TEST_PATH = re.compile(r"""["'`](/[A-Za-z0-9_\-./{}$<>]*)""")


#: Destinations built from a variable whose values are each their own route,
#: reviewed by hand. test_interaction_inventory proves every expansion
#: resolves, so a renamed route still fails the build.
DYNAMIC_DESTINATIONS = {
    "/finance/actions/{{ action }}": (
        "/finance/actions/disburse_advance",
        "/finance/actions/clear_partner_payment",
        "/finance/actions/process_reimbursement",
        "/finance/actions/confirm_accountability",
        "/finance/actions/return_correction",
    ),
}


class ControlParser(HTMLParser):
    """Start tags with their parents and text, from template markup."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        node = {
            "tag": tag,
            "attrs": dict(attrs),
            "line": self.getpos()[0],
            "parent": self.stack[-1] if self.stack else None,
            "text": [],
        }
        self.nodes.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data):
        for node in self.stack:
            node["text"].append(data)


def ancestor(node, tag):
    node = node["parent"]
    while node:
        if node["tag"] == tag:
            return node
        node = node["parent"]
    return None


def compact(value) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _blank(match) -> str:
    """Replace template syntax with spaces, keeping line numbers."""
    return "".join("\n" if c == "\n" else " " for c in match.group())


def template_markup(source: str) -> str:
    """Template source with comments and tags blanked out, lines preserved."""
    source = re.sub(
        r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}|{#.*?#}|<!--.*?-->",
        _blank,
        source,
        flags=re.S,
    )
    return re.sub(r"{%.*?%}", _blank, source, flags=re.S)


def scan_controls() -> list[dict]:
    """Every control declared in every template, in file order."""
    rows = []
    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        template = str(path.relative_to(TEMPLATE_ROOT))
        parser = ControlParser()
        parser.feed(template_markup(path.read_text(encoding="utf-8")))
        forms_by_id = {
            node["attrs"]["id"]: node
            for node in parser.nodes
            if node["tag"] == "form" and node["attrs"].get("id")
        }
        for node in parser.nodes:
            attrs = node["attrs"]
            tag = node["tag"]
            if tag not in CONTROL_TAGS:
                continue
            if tag == "input" and attrs.get("type") == "hidden":
                continue
            # A control outside its form names it with form="id".
            form = forms_by_id.get(attrs.get("form") or "") or ancestor(node, "form")
            form_attrs = form["attrs"] if form else {}
            control_type = attrs.get("type") or (
                "submit" if tag == "button" and form else ""
            )
            kind = (
                "tab"
                if attrs.get("role") == "tab"
                else "field"
                if tag in {"select", "textarea", "input"}
                and control_type not in {"submit", "button", "reset"}
                else "disclosure"
                if tag == "summary"
                else "link"
                if tag == "a"
                else "button"
            )
            label = compact(
                attrs.get("aria-label")
                or attrs.get("title")
                or "".join(node["text"])
                or attrs.get("placeholder")
                or attrs.get("value")
            )[:160]
            method, destination = _request_of(attrs, form_attrs, kind, control_type)
            rows.append(
                {
                    "template": template,
                    "line": node["line"],
                    "kind": kind,
                    "tag": tag,
                    "accessible_name": label,
                    "element_id": attrs.get("id", ""),
                    "name": attrs.get("name", ""),
                    "type": control_type,
                    "method": method,
                    "destination": destination,
                }
            )
    return rows


def _request_of(attrs, form_attrs, kind, control_type) -> tuple[str, str]:
    """The request a control makes: (METHOD, destination) or ("", "")."""
    for key in HTMX_METHODS:
        if key in attrs:
            return key[3:].upper(), attrs[key] or ""
    if kind == "link" and attrs.get("href"):
        return "GET", attrs["href"]
    if (
        kind in {"button", "field"}
        and control_type == "submit"
        or (kind == "button" and form_attrs and control_type != "button")
    ):
        for key in HTMX_METHODS:
            if key in form_attrs:
                return key[3:].upper(), form_attrs[key] or ""
        if form_attrs:
            return (
                (form_attrs.get("method") or "get").upper(),
                form_attrs.get("action") or "",
            )
    if "formaction" in attrs:
        return "POST", attrs["formaction"]
    return "", ""


def resolve_route(path: str) -> str:
    """The URL pattern a literal or templated path resolves to, or ""."""
    if not path or not path.startswith("/") or path.startswith("//"):
        return ""
    # Attribute values wrap across lines before their query string.
    concrete = re.sub(r"\s+", "", path)
    # An expression that opens a path segment stands for that segment; one
    # glued to the end of a segment ("/drilldown{{ item.link }}") appends a
    # query or fragment and is dropped.
    concrete = re.sub(r"(?<=/)(?:{{.*?}}|{%.*?%})", "x", concrete)
    concrete = _TEMPLATE_EXPR.sub("", concrete)
    concrete = re.sub(r"(?<=/)(?:\$\{[^}]*\}|\{[^}]*\}|<[^>]*>)", "x", concrete)
    concrete = re.sub(r"\$\{[^}]*\}|\{[^}]*\}|<[^>]*>", "", concrete)
    concrete = concrete.split("?", 1)[0].split("#", 1)[0].split("&", 1)[0]
    try:
        match = resolve(concrete)
    except Resolver404:
        return ""
    return "/" + match.route if match.route is not None else ""


def _tested_routes() -> tuple[set[str], set[str]]:
    """Route patterns requested by Django tests, and by browser specs."""

    def routes_in(paths) -> set[str]:
        found = set()
        for path in paths:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for literal in _TEST_PATH.findall(text):
                route = resolve_route(literal)
                if route:
                    found.add(route)
        return found

    django = routes_in(
        [
            *PROJECT_ROOT.glob("apps/**/test*.py"),
            *PROJECT_ROOT.glob("apps/**/tests/*.py"),
        ]
    )
    browser = routes_in(PROJECT_ROOT.glob("e2e/**/*.js"))
    return django, browser


def _page_map() -> tuple[dict[str, set[str]], dict[str, set[str]], set[str]]:
    """template → page routes, route → roles, and the routes the browser
    route audit opens (argument-free pages with a role mapping)."""
    from apps.system_health.page_inventory import (
        _navigation_map,
        _route_catalog,
        _template_dependency_names,
    )

    inventory = json.loads(
        (PROJECT_ROOT / "docs" / "platform-page-inventory.json").read_text(
            encoding="utf-8"
        )
    )
    roles_by_route: dict[str, set[str]] = {}
    audited: set[str] = set()
    for surface in inventory.get("pages", []):
        roles_by_route.setdefault(surface["route"], set()).update(
            surface.get("role_access") or []
        )
        if (
            surface.get("surface_kind") == "page"
            and surface.get("role_access")
            and "<" not in surface["route"]
            and "logout" not in surface["route"]
        ):
            audited.add(surface["route"])

    pages_by_template: dict[str, set[str]] = {}
    for entry in _route_catalog(_navigation_map()):
        for name in _template_dependency_names(entry["templates"]):
            pages_by_template.setdefault(name, set()).add(entry["route"])
    return pages_by_template, roles_by_route, audited


def _stable_id(row: dict, occurrence: int) -> str:
    key = "|".join(
        [
            row["template"],
            row["kind"],
            row["tag"],
            row["element_id"],
            row["name"],
            row["accessible_name"],
            row["method"],
            row["destination"],
            str(occurrence),
        ]
    )
    return (
        "INT-"
        + hashlib.sha1(key.encode("utf-8"), usedforsecurity=False)
        .hexdigest()[:12]
        .upper()
    )


def build_interaction_inventory() -> dict:
    django_routes, browser_routes = _tested_routes()
    pages_by_template, roles_by_route, audited = _page_map()
    tested = django_routes | browser_routes

    seen: Counter = Counter()
    controls = []
    # Pages and roles per template, once: a layout partial sits on hundreds
    # of pages, and repeating that list on each of its controls was most of
    # the manifest.
    templates: dict[str, dict] = {}
    for row in scan_controls():
        signature = (
            row["template"],
            row["kind"],
            row["tag"],
            row["element_id"],
            row["name"],
            row["accessible_name"],
            row["method"],
            row["destination"],
        )
        occurrence = seen[signature]
        seen[signature] += 1

        pages = pages_by_template.get(row["template"], set())
        if row["template"] not in templates:
            templates[row["template"]] = {
                "pages": sorted(pages),
                "roles": sorted(
                    {r for page in pages for r in roles_by_route.get(page, set())}
                ),
            }
        expansions = DYNAMIC_DESTINATIONS.get(row["destination"])
        destination_route = (
            resolve_route(expansions[0])
            if expansions
            else resolve_route(row["destination"])
        )
        if destination_route and destination_route in tested:
            evidence = "request-tested"
        elif any(page in audited for page in pages):
            evidence = "browser-rendered"
        elif any(page in django_routes for page in pages):
            evidence = "page-tested"
        else:
            evidence = "none"
        state_changing = row["method"] in STATE_CHANGING
        controls.append(
            {
                "id": _stable_id(row, occurrence),
                "template": row["template"],
                "line": row["line"],
                "kind": row["kind"],
                "tag": row["tag"],
                "accessible_name": row["accessible_name"],
                "selector": (
                    f"#{row['element_id']}"
                    if row["element_id"] and "{" not in row["element_id"]
                    else f"{row['tag']}[name={row['name']}]"
                    if row["name"] and "{" not in row["name"]
                    else ""
                ),
                "method": row["method"],
                "destination": row["destination"],
                "destination_route": destination_route,
                "state_changing": state_changing,
                "high_consequence": bool(
                    state_changing
                    and HIGH_CONSEQUENCE.search(
                        f"{row['accessible_name']} {row['destination']}"
                    )
                ),
                "evidence": evidence,
            }
        )

    by_evidence = Counter(c["evidence"] for c in controls)
    return {
        "schema_version": 1,
        "method": (
            "Static scan of every template control (button, link, input, "
            "select, textarea, summary; hidden inputs excluded), joined to the "
            "URL resolver, the page inventory and the literal paths requested "
            "by Django tests and browser specs. Evidence says what was "
            "exercised, not that a workflow passed."
        ),
        "summary": {
            "templates_scanned": len({c["template"] for c in controls}),
            "controls": len(controls),
            "by_kind": dict(sorted(Counter(c["kind"] for c in controls).items())),
            "by_evidence": dict(sorted(by_evidence.items())),
            "state_changing": sum(c["state_changing"] for c in controls),
            "high_consequence": sum(c["high_consequence"] for c in controls),
            "untested": by_evidence.get("none", 0),
            "untested_state_changing": sum(
                c["state_changing"] and c["evidence"] == "none" for c in controls
            ),
            "unresolved_destinations": sum(
                bool(c["destination"].startswith("/") and not c["destination_route"])
                for c in controls
            ),
        },
        "templates": templates,
        "controls": controls,
    }


def inventory_as_json(inventory: dict) -> str:
    """Pretty summary, one control per line: small, and a diff names controls."""
    head = {k: v for k, v in inventory.items() if k != "controls"}
    text = json.dumps(head, indent=1, ensure_ascii=False, sort_keys=True)
    lines = ",\n".join(
        "  " + json.dumps(control, ensure_ascii=False, sort_keys=True)
        for control in inventory["controls"]
    )
    return text[:-2] + ',\n "controls": [\n' + lines + "\n ]\n}\n"


def inventory_as_markdown(inventory: dict) -> str:
    summary = inventory["summary"]
    lines = [
        "# Platform Interaction Inventory",
        "",
        "Generated by `python manage.py build_interaction_inventory` from the "
        "templates, the URL resolver and the test corpus. Do not edit by hand.",
        "",
        inventory["method"],
        "",
        "| Measure | Count |",
        "|---|---:|",
        f"| Templates with controls | {summary['templates_scanned']} |",
        f"| Control declarations | {summary['controls']} |",
        f"| State-changing | {summary['state_changing']} |",
        f"| High-consequence (state-changing) | {summary['high_consequence']} |",
        f"| No automated evidence | {summary['untested']} |",
        f"| State-changing with no automated evidence | "
        f"{summary['untested_state_changing']} |",
        f"| Destination path that resolves to no route | "
        f"{summary['unresolved_destinations']} |",
        "",
        "| Kind | Count |",
        "|---|---:|",
        *[f"| {k} | {v} |" for k, v in summary["by_kind"].items()],
        "",
        "| Evidence | Count |",
        "|---|---:|",
        *[f"| {k} | {v} |" for k, v in summary["by_evidence"].items()],
        "",
        "## State-changing controls with no automated evidence",
        "",
        "| ID | Template | Line | Control | Request |",
        "|---|---|---:|---|---|",
    ]
    for control in inventory["controls"]:
        if control["state_changing"] and control["evidence"] == "none":
            name = control["accessible_name"].replace("|", "\\|") or "(unnamed)"
            request = f"{control['method']} {control['destination']}".replace(
                "|", "\\|"
            )
            lines.append(
                f"| {control['id']} | {control['template']} | {control['line']} "
                f"| {name} | `{request}` |"
            )
    return "\n".join(lines) + "\n"

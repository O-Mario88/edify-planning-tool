"""Machine-readable inventory for Edify's routed product surfaces.

The inventory deliberately derives its facts from the URL resolver, the
``@require_page_permission`` metadata, centralized navigation, view source and
rendered templates.  It is not a second hand-maintained list that can drift
away from the product.

The audit is intentionally conservative: automated findings are evidence for
manual review, not a claim that a page is good merely because a regexp did not
find a problem.  The generated score is therefore named
``automated_quality_score`` and the human score remains unset until a visual,
responsive and accessibility review has been completed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import inspect
import json
from pathlib import Path
import re
from typing import Iterable

from django.conf import settings
from django.urls import URLPattern, URLResolver, get_resolver

from apps.core.navigation import ADMIN, PAGE_PERMISSIONS, SIDEBAR_ITEMS
from apps.core.enums import ActivityStatus
from apps.core.rbac import EdifyRole, all_permission_keys
from apps.realtime.registry import JOB_REGISTRY


PROJECT_ROOT = Path(settings.BASE_DIR)
TEMPLATE_ROOT = PROJECT_ROOT / "templates"

_TEMPLATE_RE = re.compile(
    r"(?:render|TemplateResponse)\(\s*[^,]+,\s*[\"']([^\"']+\.html)[\"']"
)
_TEMPLATE_NAME_RE = re.compile(r"template_name\s*=\s*[\"']([^\"']+\.html)[\"']")
_TITLE_BLOCK_RE = re.compile(
    r"{%\s*block\s+title\s*%}(.*?){%\s*endblock\s*%}", re.DOTALL
)
_H1_RE = re.compile(r"<h1\b[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>|{%.*?%}|{{.*?}}", re.DOTALL)
_HTMX_RE = re.compile(r"\bhx-(get|post|put|patch|delete)=[\"']([^\"']+)[\"']")
_FORM_RE = re.compile(
    r"<form\b[^>]*\b(?:action|hx-(?:post|put|patch|delete))=[\"']([^\"']*)[\"']",
    re.IGNORECASE,
)
_API_RE = re.compile(r"[\"'](/api/[^\"']+)[\"']")
_INLINE_EVENT_RE = re.compile(
    r"\bon(?:click|change|input|submit|mouseover|mouseout)=", re.I
)
_RAW_HEX_RE = re.compile(r"(?<!&)#[0-9a-fA-F]{3,8}\b")
_EMOJI_RE = re.compile(
    "["
    "\U0001f300-\U0001f5ff"
    "\U0001f600-\U0001f64f"
    "\U0001f680-\U0001f6ff"
    "\U0001f900-\U0001f9ff"
    "]"
)

CANONICAL_OPERATIONAL_WORKFLOW = [
    "School Upload",
    "Data Quality",
    "School Directory",
    "Cluster",
    "SSA",
    "Planning",
    "Activity",
    "Automatic Costing",
    "My Plan",
    "Fund Request",
    "Disbursement",
    "Execution",
    "Evidence",
    "Activity SF ID",
    "Field Debrief",
    "IA Verification",
    "Accountability",
    "NetSuite Expense ID",
    "Closure",
    "Targets",
    "Analytics",
    "Leadership Action",
]


@dataclass(frozen=True)
class Finding:
    key: str
    severity: str
    evidence: str
    recommended_action: str


@dataclass
class PageInventoryItem:
    app: str
    route: str
    route_name: str
    page_title: str
    surface_kind: str
    permission_key: str
    role_access: list[str]
    purpose: str
    primary_user_decision: str
    primary_action: str
    secondary_actions: list[str]
    backend_view: str
    backend_module: str
    services_and_models: list[str]
    templates: list[str]
    htmx_endpoints: list[str]
    api_endpoints: list[str]
    charts: bool
    tables: bool
    forms: bool
    drawers: bool
    modals: bool
    notifications: bool
    todos: bool
    audit_events: bool
    responsive_state: str
    theme_state: str
    state_coverage: dict[str, bool]
    automated_quality_score: float
    manual_quality_score: float | None
    findings: list[dict]
    implementation_status: str
    test_status: str


def _route_string(pattern: URLPattern, prefix: str) -> str:
    raw = f"{prefix}{pattern.pattern}"
    raw = raw.replace("^", "").replace("$", "")
    raw = re.sub(r"\\Z$", "", raw)
    raw = re.sub(r"\(\?P<([^>]+)>[^)]+\)", r"<\1>", raw)
    raw = raw.replace("\\/", "/")
    return "/" + raw.lstrip("/")


def _iter_patterns(
    patterns: Iterable[URLPattern | URLResolver], prefix: str = ""
) -> Iterable[tuple[URLPattern, str]]:
    for pattern in patterns:
        if isinstance(pattern, URLResolver):
            yield from _iter_patterns(
                pattern.url_patterns, prefix + str(pattern.pattern)
            )
        else:
            yield pattern, _route_string(pattern, prefix)


def _navigation_map() -> dict[str, dict]:
    result: dict[str, dict] = {}
    for section in SIDEBAR_ITEMS:
        for item in section["items"]:
            for url in {item["url"], *item.get("role_urls", {}).values()}:
                result[url.rstrip("/") or "/"] = {
                    "label": item["label"],
                    "group": section["group_label"],
                    "page_key": item["page_key"],
                }
    return result


def _clean_text(value: str) -> str:
    value = _TAG_RE.sub(" ", value)
    return re.sub(r"\s+", " ", value).strip(" —|-\n\t")


def _title_from_template(source: str, fallback: str) -> str:
    block = _TITLE_BLOCK_RE.search(source)
    if block:
        title = _clean_text(block.group(1)).split("—")[0].split("|")[0].strip()
        if title:
            return title
    heading = _H1_RE.search(source)
    if heading:
        title = _clean_text(heading.group(1))
        if title:
            return title
    return fallback


def _template_sources(template_names: Iterable[str]) -> tuple[str, list[str]]:
    chunks: list[str] = []
    existing: list[str] = []
    for name in dict.fromkeys(template_names):
        path = TEMPLATE_ROOT / name
        if path.is_file():
            existing.append(name)
            chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks), existing


def _view_templates(callback) -> list[str]:
    original = inspect.unwrap(callback)
    names: list[str] = []
    template_name = getattr(original, "template_name", None)
    if isinstance(template_name, str):
        names.append(template_name)
    try:
        source = inspect.getsource(original)
    except (OSError, TypeError):
        source = ""
    names.extend(_TEMPLATE_RE.findall(source))
    names.extend(_TEMPLATE_NAME_RE.findall(source))
    return list(dict.fromkeys(names))


@lru_cache(maxsize=None)
def _module_source(module_name: str) -> str:
    try:
        module = __import__(module_name, fromlist=["*"])
        path = inspect.getsourcefile(module)
        return Path(path).read_text(encoding="utf-8") if path else ""
    except (ImportError, OSError, TypeError):
        return ""


def _dependencies(module_name: str) -> list[str]:
    source = _module_source(module_name)
    matches = re.findall(
        r"from\s+(apps\.[\w.]+\.(?:models|services|service|selectors|scoping))\s+import",
        source,
    )
    return sorted(set(matches))


def _template_findings(source: str) -> list[Finding]:
    findings: list[Finding] = []
    checks = [
        (
            "dead-link",
            "critical",
            re.search(r"href=[\"'](?:#|javascript:void\(0\))[\"']", source, re.I),
            "Dead or placeholder navigation is present.",
            "Connect the control to a real route or remove it.",
        ),
        (
            "inline-event-handler",
            "high",
            _INLINE_EVENT_RE.search(source),
            "Inline browser event handlers bypass the shared interaction layer.",
            "Move behavior to the shared Alpine/JavaScript component and keep semantic HTML fallbacks.",
        ),
        (
            "hardcoded-chart-series",
            "critical",
            re.search(r"(?:series|data)\s*:\s*\[\s*-?\d", source),
            "A chart appears to contain a numeric series in template source.",
            "Supply the series from a scoped backend service and provide an accessible data alternative.",
        ),
        (
            "emoji-icon",
            "high",
            _EMOJI_RE.search(source),
            "Emoji is used in product UI and will render inconsistently across platforms.",
            "Replace it with the normalized Edify SVG icon primitive.",
        ),
        (
            "tiny-text",
            "medium",
            re.search(r"text-\[(?:8|9|10|11)px\]", source),
            "Text below the shared readable type scale is present.",
            "Migrate labels and metadata to the semantic typography tokens.",
        ),
        (
            "legacy-white-surface",
            "medium",
            re.search(r"\bbg-white(?:\b|/)", source),
            "A literal white surface can flatten Light mode and break Dark/System themes.",
            "Use the semantic card, elevated or muted surface token.",
        ),
        (
            "raw-hex",
            "medium",
            _RAW_HEX_RE.search(source),
            "A raw hexadecimal color bypasses semantic theme tokens.",
            "Map the color to an existing semantic token or add a documented token.",
        ),
        (
            "inline-style",
            "low",
            re.search(r"\bstyle=[\"']", source),
            "Static inline styling reduces theme and component consistency.",
            "Move static presentation into a shared component class; keep inline custom properties only for live data.",
        ),
        (
            "fixed-pixel-width",
            "medium",
            re.search(r"(?<![-\w])w-\[(?:2[4-9]\d|[3-9]\d{2,})px\]", source),
            "A fixed pixel width may create narrow-screen overflow or dead space.",
            "Use minmax, fluid sizing, or a size-aware container rule.",
        ),
    ]
    for key, severity, match, evidence, action in checks:
        if match:
            findings.append(Finding(key, severity, evidence, action))
    return findings


def _score(findings: list[Finding], state_coverage: dict[str, bool]) -> float:
    weights = {"critical": 1.6, "high": 0.9, "medium": 0.35, "low": 0.1}
    score = 10.0 - sum(weights[f.severity] for f in findings)
    score -= sum(0.15 for supported in state_coverage.values() if not supported)
    return round(max(0.0, min(10.0, score)), 1)


@lru_cache(maxsize=1)
def _test_corpus() -> str:
    chunks = []
    for path in PROJECT_ROOT.glob("apps/**/test*.py"):
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return "\n".join(chunks)


def _surface_kind(route: str, route_name: str, templates: list[str]) -> str:
    value = " ".join([route, route_name, *templates]).lower()
    if "drawer" in value:
        return "drawer"
    if "partial" in value or any("/partials/" in f"/{t}" for t in templates):
        return "partial"
    if any(word in value for word in ("export", "download", "print")):
        return "export"
    return "page"


def _http_methods(callback) -> list[str]:
    original = inspect.unwrap(callback)
    view_class = getattr(callback, "view_class", None)
    if view_class:
        names = getattr(view_class, "http_method_names", [])
        return sorted(name.upper() for name in names if name not in {"options", "head"})
    try:
        source = inspect.getsource(original)
    except (OSError, TypeError):
        return ["GET"]
    methods = set(re.findall(r"request\.method\s*==\s*[\"']([A-Z]+)[\"']", source))
    methods.update(
        re.findall(r"request\.method\s+in\s+\[[^\]]*[\"']([A-Z]+)[\"']", source)
    )
    methods.add("GET")
    return sorted(methods)


def _route_catalog(nav_map: dict[str, dict]) -> list[dict]:
    catalog = []
    for pattern, route in _iter_patterns(get_resolver().url_patterns):
        callback = pattern.callback
        original = inspect.unwrap(callback)
        module_name = getattr(callback, "__module__", "")
        route_name = pattern.name or ""
        permission_key = getattr(callback, "page_permission", "")
        required = getattr(callback, "required_permissions", None)
        if required is None:
            required = getattr(
                getattr(callback, "view_class", None), "required_permissions", None
            )
        if isinstance(required, str):
            required_values = [required]
        elif isinstance(required, (list, tuple, set, frozenset)):
            required_values = list(required)
        else:
            # Some class-based views expose descriptors/properties here; the
            # runtime permission class resolves those on an instance.
            required_values = []
        templates = _view_templates(callback)
        route_key = route.rstrip("/") or "/"

        if templates or permission_key or route_key in nav_map:
            kind = _surface_kind(route, route_name, templates)
        elif route.startswith("/api/") or ".api" in module_name:
            kind = "api"
        elif required_values or re.search(
            r"(?:create|update|delete|approve|return|submit|confirm|assign|action)",
            route_name,
            re.I,
        ):
            kind = "mutation-or-action"
        else:
            kind = "platform-route"

        catalog.append(
            {
                "route": route,
                "route_name": route_name,
                "kind": kind,
                "callback": f"{module_name}.{getattr(original, '__name__', original.__class__.__name__)}",
                "methods": _http_methods(callback),
                "page_permission": permission_key,
                "required_permissions": sorted(
                    str(getattr(value, "value", value)) for value in required_values
                ),
                "templates": templates,
            }
        )
    return sorted(catalog, key=lambda item: item["route"])


def _component_catalog() -> list[dict]:
    result = []
    for directory in (TEMPLATE_ROOT / "components", TEMPLATE_ROOT / "partials"):
        if not directory.exists():
            continue
        for path in directory.rglob("*.html"):
            source = path.read_text(encoding="utf-8")
            result.append(
                {
                    "template": str(path.relative_to(TEMPLATE_ROOT)),
                    "bytes": len(source.encode("utf-8")),
                    "forms": source.lower().count("<form"),
                    "tables": source.lower().count("<table"),
                    "htmx_controls": len(_HTMX_RE.findall(source)),
                    "findings": [asdict(f) for f in _template_findings(source)],
                }
            )
    return sorted(result, key=lambda item: item["template"])


def _primary_action(source: str) -> str:
    candidates = re.findall(
        r"<(?:button|a)\b[^>]*(?:btn-primary|edify-button--primary|bg-(?:blue|indigo)-6\d\d)[^>]*>(.*?)</(?:button|a)>",
        source,
        re.I | re.DOTALL,
    )
    for candidate in candidates:
        label = _clean_text(candidate)
        if label:
            return label
    return "Requires manual product review"


def build_page_inventory() -> dict:
    nav_map = _navigation_map()
    entries: list[PageInventoryItem] = []

    for pattern, route in _iter_patterns(get_resolver().url_patterns):
        callback = pattern.callback
        module_name = getattr(callback, "__module__", "")
        permission_key = getattr(callback, "page_permission", "")
        template_names = _view_templates(callback)
        route_key = route.rstrip("/") or "/"
        nav_item = nav_map.get(route_key)

        # The inventory covers human-facing product surfaces. API-only routes
        # are catalogued separately by the DRF schema and are not pages.
        if not template_names and not permission_key and not nav_item:
            continue

        source, templates = _template_sources(template_names)
        original = inspect.unwrap(callback)
        view_name = getattr(original, "__name__", callback.__class__.__name__)
        route_name = pattern.name or ""
        fallback_title = (
            nav_item["label"]
            if nav_item
            else re.sub(r"[_-]+", " ", route_name or view_name).title()
        )
        roles = set(PAGE_PERMISSIONS.get(permission_key, set()))
        if permission_key:
            roles.add(ADMIN)  # RolePermissionService has an explicit admin bypass.

        findings = _template_findings(source)
        state_coverage = {
            "loading": bool(
                re.search(r"skeleton|hx-indicator|\bloading\b", source, re.I)
            ),
            "empty": bool(
                re.search(
                    r"empty-state|No (?:data|results|records|items)|{%\s*empty\s*%}",
                    source,
                    re.I,
                )
            ),
            "error": bool(re.search(r"error|messages|role=[\"']alert", source, re.I)),
            "disabled": "disabled" in source or "aria-disabled" in source,
        }
        responsive = bool(
            re.search(
                r"(?:sm|md|lg|xl):|@media|@container|admin-command|page-shell", source
            )
        )
        theme_aware = bool(
            re.search(r"var\(--edify-|theme-(?:dark|blue)|dark:", source)
        ) and not any(f.key == "legacy-white-surface" for f in findings)

        htmx = [
            f"{method.upper()} {endpoint}"
            for method, endpoint in _HTMX_RE.findall(source)
        ]
        actions = list(dict.fromkeys(_FORM_RE.findall(source)))
        test_tokens = [route_key, route_name, view_name, permission_key]
        has_test = any(token and token in _test_corpus() for token in test_tokens)
        purpose = (
            (inspect.getdoc(original) or "").split("\n\n", 1)[0].replace("\n", " ")
        )

        entries.append(
            PageInventoryItem(
                app=module_name.split(".")[1]
                if module_name.startswith("apps.")
                else module_name,
                route=route,
                route_name=route_name,
                # A single route can intentionally render a different cockpit
                # per role (notably /dashboard). In that case the navigation
                # label is the honest shared title; each template remains
                # listed for role-by-role review.
                page_title=(
                    fallback_title
                    if len(templates) > 1 and nav_item
                    else _title_from_template(source, fallback_title)
                ),
                surface_kind=_surface_kind(route, route_name, templates),
                permission_key=permission_key or (nav_item or {}).get("page_key", ""),
                role_access=sorted(roles),
                purpose=purpose or "Requires product-purpose documentation",
                primary_user_decision="Requires manual product review",
                primary_action=_primary_action(source),
                secondary_actions=actions[:12],
                backend_view=f"{module_name}.{view_name}" if module_name else view_name,
                backend_module=module_name,
                services_and_models=_dependencies(module_name),
                templates=templates,
                htmx_endpoints=list(dict.fromkeys(htmx)),
                api_endpoints=list(dict.fromkeys(_API_RE.findall(source))),
                charts=bool(re.search(r"ApexCharts|FullCalendar|<canvas\b", source)),
                tables="<table" in source.lower(),
                forms="<form" in source.lower(),
                drawers="drawer" in source.lower() or "drawer" in route_name.lower(),
                modals=bool(re.search(r"<dialog\b|\bmodal\b", source, re.I)),
                notifications="notification" in source.lower(),
                todos=bool(re.search(r"to-?do", source, re.I)),
                audit_events="audit" in _module_source(module_name).lower(),
                responsive_state="detected" if responsive else "manual-review-required",
                theme_state="token-driven" if theme_aware else "migration-required",
                state_coverage=state_coverage,
                automated_quality_score=_score(findings, state_coverage),
                manual_quality_score=None,
                findings=[asdict(f) for f in findings],
                implementation_status="existing-routed-surface",
                test_status="referenced-by-automated-test"
                if has_test
                else "coverage-review-required",
            )
        )

    serialized = [asdict(item) for item in sorted(entries, key=lambda item: item.route)]
    severity_counts = {
        severity: 0 for severity in ("critical", "high", "medium", "low")
    }
    for item in serialized:
        for finding in item["findings"]:
            severity_counts[finding["severity"]] += 1

    routes = _route_catalog(nav_map)
    components = _component_catalog()
    roles = [role.value for role in EdifyRole]
    jobs = [asdict(job) for job in JOB_REGISTRY]

    return {
        "schema_version": 1,
        "source_of_truth": [
            "django.urls.get_resolver",
            "apps.core.navigation.PAGE_PERMISSIONS",
            "apps.core.navigation.SIDEBAR_ITEMS",
            "view and template source",
        ],
        "quality_score_note": (
            "Automated scores are provisional evidence derived from explicit findings and "
            "state coverage. A page is not complete until manual visual, responsive and "
            "accessibility scores are recorded."
        ),
        "summary": {
            "all_routes": len(routes),
            "api_routes": sum(item["kind"] == "api" for item in routes),
            "roles": len(roles),
            "permission_keys": len(all_permission_keys()),
            "scheduled_jobs": len(jobs),
            "activity_states": len(ActivityStatus.choices),
            "component_templates": len(components),
            "routed_surfaces": len(serialized),
            "full_pages": sum(item["surface_kind"] == "page" for item in serialized),
            "partials_and_drawers": sum(
                item["surface_kind"] in {"partial", "drawer"} for item in serialized
            ),
            "permission_gated": sum(
                bool(item["permission_key"]) for item in serialized
            ),
            "test_referenced": sum(
                item["test_status"] == "referenced-by-automated-test"
                for item in serialized
            ),
            "severity_counts": severity_counts,
        },
        "platform": {
            "installed_domain_apps": sorted(
                app for app in settings.INSTALLED_APPS if app.startswith("apps.")
            ),
            "roles": roles,
            "permission_keys": all_permission_keys(),
            "scheduled_jobs": jobs,
            "activity_states": [
                {"value": value, "label": label}
                for value, label in ActivityStatus.choices
            ],
            "canonical_operational_workflow": CANONICAL_OPERATIONAL_WORKFLOW,
        },
        "routes": routes,
        "components": components,
        "pages": serialized,
    }


def inventory_as_markdown(inventory: dict) -> str:
    summary = inventory["summary"]
    lines = [
        "# Edify Platform Page Inventory",
        "",
        "Generated from the live Django URL resolver, role permissions, navigation, view source and templates.",
        "",
        "## Summary",
        "",
        f"- Routed product surfaces: **{summary['routed_surfaces']}**",
        f"- All registered routes: **{summary['all_routes']}**",
        f"- API routes: **{summary['api_routes']}**",
        f"- Roles: **{summary['roles']}**",
        f"- Permission keys: **{summary['permission_keys']}**",
        f"- Scheduled jobs: **{summary['scheduled_jobs']}**",
        f"- Activity states: **{summary['activity_states']}**",
        f"- Shared component templates: **{summary['component_templates']}**",
        f"- Full pages: **{summary['full_pages']}**",
        f"- Partials and drawers: **{summary['partials_and_drawers']}**",
        f"- Permission-gated surfaces: **{summary['permission_gated']}**",
        f"- Referenced by automated tests: **{summary['test_referenced']}**",
        "- Findings: "
        + ", ".join(
            f"{severity} **{count}**"
            for severity, count in summary["severity_counts"].items()
        ),
        "",
        "> " + inventory["quality_score_note"],
        "",
        "## Routed surfaces",
        "",
        "| Route | Page | Roles | Template | Automated score | Findings | Test |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for page in inventory["pages"]:
        roles = ", ".join(page["role_access"]) or "Unmapped"
        templates = "<br>".join(page["templates"]) or "Dynamic / none detected"
        lines.append(
            "| {route} | {title} | {roles} | {templates} | {score:.1f} | {findings} | {test} |".format(
                route=page["route"].replace("|", "\\|"),
                title=page["page_title"].replace("|", "\\|"),
                roles=roles,
                templates=templates,
                score=page["automated_quality_score"],
                findings=len(page["findings"]),
                test=page["test_status"].replace("-", " "),
            )
        )
    lines.extend(
        [
            "",
            "## Machine-readable source",
            "",
            "The complete per-surface workflow, component, state and finding records are in `docs/platform-page-inventory.json`.",
            "",
        ]
    )
    return "\n".join(lines)


def inventory_as_json(inventory: dict) -> str:
    return json.dumps(inventory, indent=2, sort_keys=True) + "\n"


__all__ = [
    "build_page_inventory",
    "inventory_as_json",
    "inventory_as_markdown",
]

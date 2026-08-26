"""A machine-readable inventory of every KPI tile the platform builds.

Like ``page_inventory``, this derives its facts from source rather than from a
hand-kept list, so it cannot quietly drift away from the product. It exists
because the KPI surface was too large to audit by reading: 281 tiles across 37
modules, carrying 227 distinct labels in 25 different dict shapes, of which
none carried a stable identifier and 11 carried a drill-down.

Classification matters more than raw counts. A KPI *tile* is a headline number
a reader acts on. A *breakdown row* -- ``{"label": ..., "amount": ...}`` inside
a status distribution -- is workflow vocabulary that is legitimately repeated
wherever that workflow is drawn. An early version of this scan lumped the two
together and reported "Returned" as a five-way duplicated KPI; it is in fact
one shared status bucket (``weekly_status_buckets``) rendered in several
places, which is the correct design. Counting it as a defect would have sent
someone to "fix" working code.

The findings are evidence for review, not a verdict. A repeated label is a
question ("is this the same metric, or two metrics sharing a word?"), and only
the registry in ``apps.core.metrics`` can answer it.

What the tile count actually measures
-------------------------------------

This is a *source* scan, so it counts hand-written dict literals. A tile built
through ``render_metric`` or ``render_precomputed_metric_item`` gets its key at
runtime and has no literal dict to find -- it therefore leaves this scan
altogether rather than appearing as a registered tile. ``with_metric_key``
stays at 0.

So read ``tiles`` as "KPI tiles still built by hand", which is the number that
should fall to zero. ``with_metric_key`` is retained to catch the other case:
someone hand-writing ``"metric_key": ...`` into a literal dict, which looks
registered without going through the registry.
"""

from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

from django.conf import settings


PROJECT_ROOT = Path(settings.BASE_DIR)
APPS_ROOT = PROJECT_ROOT / "apps"
TEMPLATE_ROOT = PROJECT_ROOT / "templates"

# Keys that make a dict look like it carries a displayable number.
VALUE_KEYS = frozenset(
    {"value", "count", "amount", "pct", "percent", "total", "display_value"}
)
# Keys that only a presentation tile carries.
TILE_MARKERS = frozenset({"variant", "icon", "helper", "hint", "trend", "tone"})


@dataclass
class KpiSite:
    """One place in the source that builds a metric-shaped dict."""

    audit_id: str
    kind: str  # kpi-tile | breakdown-row | other
    module: str
    line: int
    label: str | None
    keys: tuple[str, ...]
    has_metric_key: bool
    has_drilldown: bool
    recommendation: str
    reason: str
    priority: str
    implementation_status: str


@dataclass
class KpiTemplateSite:
    """One rendered KPI/context summary and its page-level audit decision."""

    audit_id: str
    template: str
    line: int
    source_pattern: str
    items_expression: str
    presentation: str
    page_type: str
    route: str
    page_title: str
    roles: tuple[str, ...]
    page_purpose: str
    primary_action: str
    previous_presentation: str
    new_prominent_kpi_limit: int
    mobile_result: str
    accessibility_result: str
    recommendation: str
    reason: str
    replacement_pattern: str
    implementation_status: str


@dataclass
class KpiPayloadGroup:
    """One Python list that supplies registered metrics to a UI surface."""

    audit_id: str
    module: str
    line: int
    function: str
    target: str
    source_item_count: int
    registered_metric_keys: tuple[str, ...]
    professional_metric_keys: tuple[str, ...]
    distinct_category_count: int
    repeated_categories: tuple[str, ...]
    professional_headline_count: int
    requires_headline_consolidation: bool


@dataclass
class KpiInventory:
    sites: list[KpiSite] = field(default_factory=list)
    template_sites: list[KpiTemplateSite] = field(default_factory=list)
    registered_metrics: list[dict] = field(default_factory=list)
    payload_groups: list[KpiPayloadGroup] = field(default_factory=list)

    # ── Derived views ────────────────────────────────────────────────────────
    def tiles(self) -> list[KpiSite]:
        return [s for s in self.sites if s.kind == "kpi-tile"]

    def labels_built_in_several_modules(self) -> dict[str, list[str]]:
        """Labels whose value is computed independently in more than one module.

        Each entry is a consolidation candidate: either one metric with one
        owning service, or two metrics that need two names.
        """
        by_label: dict[str, set[str]] = defaultdict(set)
        for site in self.tiles():
            if site.label:
                by_label[site.label].add(site.module)
        return {
            label: sorted(modules)
            for label, modules in sorted(by_label.items())
            if len(modules) > 1
        }

    def shape_counts(self) -> dict[str, int]:
        return {
            ", ".join(shape): n
            for shape, n in Counter(s.keys for s in self.tiles()).most_common()
        }

    def summary(self) -> dict:
        tiles = self.tiles()
        return {
            "tiles": len(tiles),
            "modules": len({s.module for s in tiles}),
            "distinct_labels": len({s.label for s in tiles if s.label}),
            "distinct_shapes": len({s.keys for s in tiles}),
            "with_metric_key": sum(1 for s in tiles if s.has_metric_key),
            "with_drilldown": sum(1 for s in tiles if s.has_drilldown),
            "labels_in_several_modules": len(self.labels_built_in_several_modules()),
            "breakdown_rows": sum(1 for s in self.sites if s.kind == "breakdown-row"),
            "registered_metrics": len(self.registered_metrics),
            "rendered_summaries": len(self.template_sites),
            "context_summaries": sum(
                1 for site in self.template_sites if site.presentation == "context"
            ),
            "headline_summaries": sum(
                1 for site in self.template_sites if site.presentation == "executive"
            ),
            "unclassified_summaries": sum(
                1
                for site in self.template_sites
                if site.presentation not in {"context", "executive", "supporting"}
            ),
            "legacy_summary_surfaces": sum(
                1
                for site in self.template_sites
                if site.source_pattern == "legacy-adapter"
            ),
            "shared_component_surfaces": sum(
                1
                for site in self.template_sites
                if site.source_pattern == "shared-component"
            ),
            "registered_payload_groups": len(self.payload_groups),
            "source_items_in_registered_payloads": sum(
                group.source_item_count for group in self.payload_groups
            ),
            "payload_groups_over_six": sum(
                group.source_item_count > 6 for group in self.payload_groups
            ),
            "payload_groups_with_repeated_categories": sum(
                bool(group.repeated_categories) for group in self.payload_groups
            ),
            "professional_headline_limit": _measured_tray_limit(None),
            "professional_compact_limit": _measured_tray_limit("compact"),
            "professional_category_limit": None,
            "supporting_metric_disclosures": 0,
        }

    def as_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "duplicated_labels": self.labels_built_in_several_modules(),
            "shapes": self.shape_counts(),
            "sites": [asdict(s) for s in self.sites],
            "template_sites": [asdict(s) for s in self.template_sites],
            "registered_metrics": self.registered_metrics,
            "payload_groups": [asdict(group) for group in self.payload_groups],
        }


KPI_INCLUDE_RE = re.compile(
    r'{%\s*include\s+["\']components/kpi_strip\.html["\'](?P<args>.*?)%}',
    re.DOTALL,
)
LEGACY_KPI_RE = re.compile(
    r'<(?:div|section)\b[^>]*class=["\'][^"\']*\bedify-kpi-strip\b[^"\']*["\'][^>]*>',
    re.DOTALL | re.IGNORECASE,
)


def _argument(args: str, name: str) -> str | None:
    match = re.search(
        rf"\b{re.escape(name)}=(?P<value>\"[^\"]*\"|'[^']*'|[^\s%]+)", args
    )
    if not match:
        return None
    return match.group("value").strip("\"'")


def _page_type(template: str) -> str:
    if "/dashboards/" in template or "/analytics/" in template:
        return "dashboard-or-analytics"
    if "/detail" in template or "review" in template:
        return "workflow-detail"
    if any(
        word in template for word in ("planning", "work_plan", "my_plan", "targets")
    ):
        return "planning"
    return "operational"


def _page_context_by_template() -> dict[str, dict]:
    """Join the KPI scan to the generated route/page inventory.

    The page inventory remains the route source of truth; this scan does not
    invent role or purpose metadata when that inventory still says manual
    review is required.
    """
    from apps.system_health.page_inventory import build_page_inventory

    pages = build_page_inventory().get("pages", [])
    by_template: dict[str, dict] = {}
    include_re = re.compile(r'{%\s*include\s+["\'](?P<template>[^"\']+)["\']')

    include_graph: dict[str, tuple[str, ...]] = {}
    for path in TEMPLATE_ROOT.rglob("*.html"):
        source = path.read_text(encoding="utf-8")
        key = path.relative_to(TEMPLATE_ROOT).as_posix()
        include_graph[key] = tuple(
            match.group("template") for match in include_re.finditer(source)
        )

    def descendants(template: str) -> set[str]:
        found: set[str] = set()
        pending = [template]
        while pending:
            current = pending.pop()
            for child in include_graph.get(current, ()):
                if child not in found:
                    found.add(child)
                    pending.append(child)
        return found

    for page in pages:
        for template in page.get("templates", []):
            by_template.setdefault(f"templates/{template}", page)
            for child in descendants(template):
                by_template.setdefault(f"templates/{child}", page)

    # These templates are rendered through helper views or HTMX fragments, so
    # the route scanner cannot see the literal template name. Keep the exact
    # public route here instead of silently emitting an unauditable blank.
    indirect_routes = {
        "templates/pages/hr/module_workspace.html": {
            "route": (
                "/org-structure; /workforce-planning; /recruitment; "
                "/candidate-pipeline; /onboarding; /cpd-learning; "
                "/succession-planning; /performance-reviews; /recovery-plans; "
                "/culture-engagement; /employee-relations; /wellness; "
                "/compensation-benefits; /payroll-readiness; "
                "/compliance-register; /policies; /offboarding; /hr-analytics; "
                "/hr-audit-log"
            ),
            "page_title": "HR operational workspace",
            "role_access": ["ADMIN", "HR"],
            "purpose": "Help HR complete the selected people workflow.",
            "primary_action": "Complete the selected HR workflow action",
        },
        "templates/pages/partners/index.html": {
            "route": "/partners",
            "page_title": "Partners",
            "role_access": [],
            "purpose": "Review partners and open the records requiring oversight.",
            "primary_action": "Open or create a partner record",
        },
        "templates/partials/analytics/impact_workspace.html": {
            "route": "/impact",
            "page_title": "Impact Readiness",
            "role_access": [],
            "purpose": "Compare verified outcomes and identify weak evidence.",
            "primary_action": "Open the affected impact records",
        },
        "templates/partials/finance/fund_allocation_kpis.html": {
            "route": "/finance/fund-allocation",
            "page_title": "Consolidated Fund Allocation",
            "role_access": [],
            "purpose": "Review country allocation context alongside costed activities.",
            "primary_action": "Review the allocation lines",
        },
        "templates/partials/ssa/performance_workspace.html": {
            "route": "/ssa",
            "page_title": "SSA Performance",
            "role_access": [],
            "purpose": "Identify schools and interventions furthest from the SSA standard.",
            "primary_action": "Open the affected schools or add a confirmed SSA score",
        },
    }
    for template, page in indirect_routes.items():
        by_template.setdefault(template, page)
    return by_template


def _template_sites() -> list[KpiTemplateSite]:
    page_context = _page_context_by_template()
    found: list[tuple[str, int, str, str, str]] = []

    for path in sorted(TEMPLATE_ROOT.rglob("*.html")):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        for match in KPI_INCLUDE_RE.finditer(source):
            args = match.group("args")
            found.append(
                (
                    relative,
                    source.count("\n", 0, match.start()) + 1,
                    _argument(args, "items") or "unknown",
                    _argument(args, "variant") or "unclassified",
                    "shared-component",
                )
            )

        if relative != "templates/components/kpi_strip.html":
            for match in LEGACY_KPI_RE.finditer(source):
                opening_tag = match.group(0)
                found.append(
                    (
                        relative,
                        source.count("\n", 0, match.start()) + 1,
                        "template-loop-or-inline-values",
                        (
                            "executive"
                            if "data-edify-summary-kpi" in opening_tag
                            else "context"
                        ),
                        "legacy-adapter",
                    )
                )

    sites: list[KpiTemplateSite] = []
    found.sort(key=lambda row: (row[0], row[1], row[4]))
    for number, (template, line, items, presentation, source_pattern) in enumerate(
        found, start=1
    ):
        page = page_context.get(template, {})
        if presentation == "context":
            recommendation = "convert"
            reason = (
                "Operational context supports the workflow but does not warrant "
                "independent headline tiles."
            )
            replacement = "compact context summary"
            status = "completed"
        elif presentation == "executive":
            recommendation = "retain"
            reason = "Dashboard or analytical headline metrics support a cross-record decision."
            replacement = "primary KPI group"
            status = "completed"
        elif presentation == "supporting":
            recommendation = "relocate"
            reason = "Secondary analysis belongs after the primary analytical question."
            replacement = "supporting analysis summary"
            status = "completed"
        else:
            recommendation = "review"
            reason = "The summary has no explicit information-hierarchy classification."
            replacement = "decision pending"
            status = "pending"

        if source_pattern == "legacy-adapter":
            replacement = f"shared {replacement}"
            status = "pending"

        sites.append(
            KpiTemplateSite(
                audit_id=f"KPI-SURFACE-{number:03d}",
                template=template,
                line=line,
                source_pattern=source_pattern,
                items_expression=items,
                presentation=presentation,
                page_type=_page_type(template),
                route=page.get("route", ""),
                page_title=page.get("page_title", ""),
                roles=tuple(page.get("role_access", [])),
                page_purpose=page.get(
                    "purpose", "Requires product-purpose documentation"
                ),
                primary_action=page.get(
                    "primary_action", "Requires manual product review"
                ),
                previous_presentation=(
                    "independent KPI tile grid"
                    if source_pattern == "shared-component"
                    else "legacy KPI strip or tile grid"
                ),
                new_prominent_kpi_limit=6 if presentation == "executive" else 0,
                mobile_result=(
                    "At most six distinct headline metrics; the tray reflows without horizontal scrolling"
                    if presentation == "executive"
                    else "Single-column context summary with no horizontal carousel"
                ),
                accessibility_result=(
                    "Semantic list with accessible labels and no hidden overflow controls"
                    if presentation == "executive"
                    else "Semantic definition list with labelled drill-down links"
                ),
                recommendation=recommendation,
                reason=reason,
                replacement_pattern=replacement,
                implementation_status=status,
            )
        )
    return sites


def _enum_value(value):
    return value.value if isinstance(value, Enum) else value


def _registered_metrics() -> list[dict]:
    from apps.core.metrics import METRIC_REGISTRY
    from apps.core.metrics.spec import Category

    primary_categories = {
        Category.PENDING_ACTION,
        Category.RISK,
        Category.QUALITY,
        Category.READINESS,
        Category.COMPLIANCE,
    }
    default_roles_by_page = {
        "my_plan": ("CCEO", "Program Lead", "ProjectCoordinator"),
        "uploads": ("CCEO", "Program Lead", "CountryDirector", "Admin"),
        "policy_compliance": ("HumanResources", "Admin"),
        "fund_requests": ("CCEO", "Program Lead", "Accountant", "Admin"),
        "work_plan": ("CCEO", "Program Lead", "CountryDirector", "Admin"),
        "ia_verification": ("ImpactAssessment", "Admin"),
        "ia_returned": ("ImpactAssessment", "CCEO", "Program Lead"),
        "ssa_unmatched": ("ImpactAssessment", "Admin"),
        "ssa_performance": (
            "CCEO",
            "Program Lead",
            "CountryDirector",
            "RegionalVicePresident",
            "ImpactAssessment",
            "Admin",
        ),
        "impact_analytics": (
            "CountryDirector",
            "RegionalVicePresident",
            "ImpactAssessment",
            "Admin",
        ),
        "partners": ("PartnerAdmin", "CountryDirector", "Admin"),
        "dashboard": ("CCEO", "Program Lead", "CountryDirector", "Admin"),
        "admin_dashboard": ("Admin",),
        "team_planning_oversight": ("Program Lead", "CountryDirector", "Admin"),
        "country_planning_oversight": (
            "CountryDirector",
            "RegionalVicePresident",
            "Admin",
        ),
        "partner_oversight": ("Program Lead", "CountryDirector", "Admin"),
        "business_transformation": (
            "BusinessTransformationOfficer",
            "MfiPartnerAdmin",
            "MfiLoanOfficer",
            "CountryDirector",
            "Admin",
        ),
    }

    output: list[dict] = []
    for number, metric in enumerate(METRIC_REGISTRY, start=1):
        if metric.category in primary_categories:
            metric_class = "primary-decision-kpi"
            recommendation = "retain"
        elif metric.category is Category.OUTCOME:
            metric_class = "outcome-kpi"
            recommendation = "retain-or-relocate-to-analytics"
        else:
            metric_class = "context-kpi"
            recommendation = "convert"

        output.append(
            {
                "audit_id": f"KPI-REG-{number:03d}",
                "kpi_id": metric.key,
                "metric_registry_id": metric.key,
                "page": metric.owner_page,
                "roles": list(
                    metric.roles or default_roles_by_page.get(metric.owner_page, ())
                ),
                "metric_name": metric.label,
                "definition": metric.definition,
                "value_type": metric.unit.value,
                "period": metric.period.value,
                "scope": metric.scope,
                "data_state": "measured-or-explicit-absence",
                "numerator": metric.numerator,
                "denominator": metric.denominator,
                "date_basis": metric.date_basis.value,
                "finance_stage": _enum_value(metric.finance_stage),
                "primary_home": metric.owner_page,
                "approved_contextual_pages": list(metric.secondary_pages),
                "user_question": metric.question,
                "user_decision": metric.question,
                "user_action": metric.drilldown or metric.no_drilldown_reason,
                "drill_down": metric.drilldown,
                "metric_class": metric_class,
                "recommendation": recommendation,
                "reason": metric.notes or metric.question,
                "replacement_pattern": (
                    "primary KPI group"
                    if recommendation == "retain"
                    else "compact context summary"
                    if recommendation == "convert"
                    else "analytics headline or contextual reference"
                ),
                "priority": "high"
                if metric_class == "primary-decision-kpi"
                else "medium",
                "implementation_status": "completed",
                "service": metric.service,
                "source_location": metric.source_location or metric.service,
                "source_models": list(metric.source_models),
                "filter_behaviour": metric.filter_behaviour.value,
            }
        )
    return output


def _string_keys(node: ast.Dict) -> set[str]:
    return {
        k.value
        for k in node.keys
        if isinstance(k, ast.Constant) and isinstance(k.value, str)
    }


def _literal(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value if isinstance(v, ast.Constant) else "{…}" for v in node.values
        )
    return None


def _classify(keys: set[str]) -> str:
    # Select options, chart bands and status legends legitimately use a
    # label/value pair. They carry vocabulary, not an independently actionable
    # number, so registering them as KPIs would corrupt the metric catalogue.
    if keys <= {"label", "value"}:
        return "breakdown-row"
    if {"band", "bar_pct", "score"} <= keys:
        return "breakdown-row"
    if {"primary", "status"} <= keys:
        return "other"
    has_tile_marker = bool(keys & TILE_MARKERS)
    if "value" in keys and has_tile_marker:
        return "kpi-tile"
    if (keys & {"amount", "count"}) and "value" not in keys:
        return "breakdown-row"
    return "other"


def _is_scanned(path: Path) -> bool:
    parts = path.as_posix()
    if "__pycache__" in parts or "/migrations/" in parts:
        return False
    return not path.name.startswith("test_")


_METRIC_RENDERERS = frozenset(
    {
        "render_metric",
        "render_kpi_item",
        "render_precomputed_metric_item",
        "render_precomputed_metric_for_source",
    }
)


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _target_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return "unknown"


class _PayloadVisitor(ast.NodeVisitor):
    """Find literal registered-metric payloads without executing services."""

    def __init__(self, *, module: str):
        self.module = module
        self.function_stack: list[str] = []
        self.groups: list[KpiPayloadGroup] = []

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self.function_stack.append(node.name)
        self.generic_visit(node)
        self.function_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node: ast.Assign):
        target = _target_name(node.targets[0]) if node.targets else "unknown"
        self._record(node.value, target)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        self._record(node.value, _target_name(node.target))
        self.generic_visit(node)

    def _record(self, value: ast.expr | None, target: str):
        if not isinstance(value, ast.List):
            return

        calls = [
            element
            for element in value.elts
            if isinstance(element, ast.Call)
            and _call_name(element) in _METRIC_RENDERERS
        ]
        if not calls:
            return

        keys = tuple(
            call.args[0].value
            for call in calls
            if call.args
            and isinstance(call.args[0], ast.Constant)
            and isinstance(call.args[0].value, str)
            and _call_name(call) != "render_precomputed_metric_for_source"
        )

        from apps.core.metrics import consolidate_kpi_items, get_metric

        category_counts: Counter[str] = Counter()
        for key in keys:
            try:
                category_counts[get_metric(key).category.value] += 1
            except KeyError:
                continue
        repeated = tuple(
            sorted(category for category, count in category_counts.items() if count > 1)
        )
        selected = consolidate_kpi_items(
            ({"metric_key": key, "label": key} for key in keys), max_items=6
        )
        professional_count = len(selected)
        self.groups.append(
            KpiPayloadGroup(
                audit_id="",
                module=self.module,
                line=value.lineno,
                function=(self.function_stack[-1] if self.function_stack else "module"),
                target=target,
                source_item_count=len(calls),
                registered_metric_keys=keys,
                professional_metric_keys=tuple(item["metric_key"] for item in selected),
                distinct_category_count=len(category_counts),
                repeated_categories=repeated,
                professional_headline_count=professional_count,
                requires_headline_consolidation=(len(calls) > professional_count),
            )
        )


def build_inventory() -> KpiInventory:
    inventory = KpiInventory(
        template_sites=_template_sites(),
        registered_metrics=_registered_metrics(),
    )

    for path in sorted(APPS_ROOT.rglob("*.py")):
        if not _is_scanned(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue

        module = path.relative_to(PROJECT_ROOT).as_posix()
        payload_visitor = _PayloadVisitor(module=module)
        payload_visitor.visit(tree)
        for group in payload_visitor.groups:
            group.audit_id = f"KPI-PAYLOAD-{len(inventory.payload_groups) + 1:03d}"
            inventory.payload_groups.append(group)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = _string_keys(node)
            if "label" not in keys or not (keys & VALUE_KEYS):
                continue

            label = None
            for key_node, value_node in zip(node.keys, node.values):
                if isinstance(key_node, ast.Constant) and key_node.value == "label":
                    label = _literal(value_node)

            kind = _classify(keys)
            if label is None and keys <= {"label", "value", "pct", "tone"}:
                kind = "breakdown-row"
            inventory.sites.append(
                KpiSite(
                    audit_id=f"KPI-SOURCE-{len(inventory.sites) + 1:03d}",
                    kind=kind,
                    module=module,
                    line=node.lineno,
                    label=label,
                    keys=tuple(sorted(keys)),
                    has_metric_key="metric_key" in keys,
                    has_drilldown=bool(keys & {"link", "url", "drilldown_url", "href"}),
                    recommendation=(
                        "register-and-review"
                        if kind == "kpi-tile"
                        else "retain-as-breakdown"
                    ),
                    reason=(
                        "Hand-built KPI payload lacks a canonical metric identity and "
                        "must be tested against the page decision before retention."
                        if kind == "kpi-tile"
                        else "Status breakdown rows support a workflow distribution and "
                        "are not independent headline KPIs."
                    ),
                    priority="high" if kind == "kpi-tile" else "low",
                    implementation_status=(
                        "pending" if kind == "kpi-tile" else "completed"
                    ),
                )
            )

    return inventory


def _measured_tray_limit(density) -> int | None:
    """How many headline cards the tray actually admits, by asking it.

    These two numbers were hard-coded literals here — 6 and 2 — which made
    this generated manifest assert a policy rather than record one. FE-02 was
    partly that: the stated rule said four, the code did six, and nothing
    reconciled the two because nothing measured either.

    So it is measured. The tag is handed more items than any plausible cap and
    the result counted; ``None`` means it returned all of them, which is now
    the answer for the dashboard tray. If somebody reintroduces a cap, this
    file records the real one on the next build instead of repeating a number
    that was true once.
    """
    from apps.core.templatetags.kpi_metrics import professional_kpis

    probe = [{"label": f"probe-{index}", "value": index} for index in range(1, 41)]
    admitted = len(professional_kpis(probe, density=density))
    return None if admitted == len(probe) else admitted

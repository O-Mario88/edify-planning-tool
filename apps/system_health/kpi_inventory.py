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
through ``render_metric`` gets its key at runtime and has no literal dict to
find -- it therefore leaves this scan altogether rather than appearing as a
registered tile. Migrating My Plan's eight tiles took the count from 281 to
272 for that reason, and ``with_metric_key`` stays at 0.

So read ``tiles`` as "KPI tiles still built by hand", which is the number that
should fall to zero. ``with_metric_key`` is retained to catch the other case:
someone hand-writing ``"metric_key": ...`` into a literal dict, which looks
registered without going through the registry.
"""

from __future__ import annotations

import ast
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
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

    kind: str  # kpi-tile | breakdown-row | other
    module: str
    line: int
    label: str | None
    keys: tuple[str, ...]
    has_metric_key: bool
    has_drilldown: bool


@dataclass
class KpiInventory:
    sites: list[KpiSite] = field(default_factory=list)

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
        }

    def as_dict(self) -> dict:
        return {
            "summary": self.summary(),
            "duplicated_labels": self.labels_built_in_several_modules(),
            "shapes": self.shape_counts(),
            "sites": [asdict(s) for s in self.sites],
        }


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
    has_tile_marker = bool(keys & TILE_MARKERS)
    if "value" in keys and (has_tile_marker or keys <= {"label", "value"}):
        return "kpi-tile"
    if (keys & {"amount", "count"}) and "value" not in keys:
        return "breakdown-row"
    return "other"


def _is_scanned(path: Path) -> bool:
    parts = path.as_posix()
    if "__pycache__" in parts or "/migrations/" in parts:
        return False
    return not path.name.startswith("test_")


def build_inventory() -> KpiInventory:
    inventory = KpiInventory()

    for path in sorted(APPS_ROOT.rglob("*.py")):
        if not _is_scanned(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue

        module = path.relative_to(PROJECT_ROOT).as_posix()
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

            inventory.sites.append(
                KpiSite(
                    kind=_classify(keys),
                    module=module,
                    line=node.lineno,
                    label=label,
                    keys=tuple(sorted(keys)),
                    has_metric_key="metric_key" in keys,
                    has_drilldown=bool(keys & {"link", "url", "drilldown_url", "href"}),
                )
            )

    return inventory

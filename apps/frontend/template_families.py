"""Templates that split into views read as one source in contract tests.

The home dashboards split on 2026-09-05 into a fixed part (header, KPI strip,
attention band, view rail) and two views (map, operations). A test that pins
what a dashboard shows still reads the whole of it through `read_template`.
"""

from __future__ import annotations

from pathlib import Path

TEMPLATE_FAMILIES: dict[str, tuple[str, ...]] = {
    "templates/partials/dashboards/cd/body.html": (
        "templates/partials/dashboards/cd/view.html",
        "templates/partials/dashboards/cd/map_view.html",
        "templates/partials/dashboards/cd/operations.html",
    ),
    "templates/partials/dashboards/pl/body.html": (
        "templates/partials/dashboards/pl/view.html",
        "templates/partials/dashboards/pl/map_view.html",
        "templates/partials/dashboards/pl/operations.html",
    ),
    "templates/pages/dashboards/rvp.html": (
        "templates/partials/dashboards/rvp/view.html",
        "templates/partials/dashboards/rvp/map_view.html",
        "templates/partials/dashboards/rvp/operations.html",
        "templates/partials/dashboards/rvp/_region_ranking.html",
    ),
    "templates/partials/ia/dashboard_body.html": (
        "templates/partials/ia/view.html",
        "templates/partials/ia/operations.html",
        "templates/partials/ia/_geography_cards.html",
    ),
    "templates/pages/dashboards/cceo.html": (
        "templates/partials/dashboards/cceo/view.html",
        "templates/partials/dashboards/cceo/map_view.html",
        "templates/partials/dashboards/cceo/week.html",
    ),
    "templates/partials/dashboards/hr/body.html": (
        "templates/partials/dashboards/hr/view.html",
        "templates/partials/dashboards/hr/map_view.html",
        "templates/partials/dashboards/hr/operations.html",
    ),
    "templates/pages/dashboards/special_projects.html": (
        "templates/partials/dashboards/special_projects/view.html",
        "templates/partials/dashboards/special_projects/map_view.html",
        "templates/partials/dashboards/special_projects/operations.html",
    ),
    "templates/pages/dashboards/main.html": (
        "templates/partials/dashboards/admin/view.html",
        "templates/partials/dashboards/admin/map_view.html",
        "templates/partials/dashboards/admin/operations.html",
    ),
}


def family(relative: str) -> tuple[str, ...]:
    relative = relative.replace("\\", "/")
    for head, members in TEMPLATE_FAMILIES.items():
        if relative.endswith(head):
            return (relative, *members)
    return (relative,)


def read_template(root: Path, relative: str) -> str:
    """The template's source, followed by the views it splits into."""
    root = Path(root)
    return "\n".join(
        (root / member).read_text(encoding="utf-8") for member in family(relative)
    )

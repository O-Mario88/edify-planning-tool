"""Cards of the existing web's own families, read as lists that name the
family, so the new web app draws them in that family's markup.

The Admin dashboard's cards (partials/dashboards/admin/_platform_operations.html:
Critical Now, Recent Incidents, Sign-ins) are an ``.admin-panel`` of
``.admin-target-row`` rows: a title (a link, or a day), a figure, then a
status, a next step or a bar. They sit side by side in ``.admin-ops-grid``,
which each card names as its group.
"""

from __future__ import annotations

import re

#: The existing layouts that set the cards inside them side by side.
GROUPS = ("admin-ops-grid",)

#: An .admin-status's colour, as a badge tone.
STATUS_TONES = (
    ("s-red", "danger"),
    ("s-orange", "warning"),
    ("s-blue", "info"),
    ("s-green", "success"),
)

#: The bar's width (style="--w: 40%").
BAR_WIDTH = re.compile(r"--w:\s*([0-9.]+)%")

#: The arrow a next step ends in.
ARROW = "→"


def group_of(node) -> str:
    """The layout ``node`` is, when it is one of GROUPS."""
    return next((group for group in GROUPS if node.has(group)), "")


def is_admin_panel(node) -> bool:
    """An .admin-panel card of .admin-target-row rows, or of none yet."""
    if not node.has("admin-panel"):
        return False
    return any(
        not isinstance(child, str)
        and (child.has("admin-target-row") or child.has("admin-panel__empty"))
        for child in node.children
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _row(row) -> dict:
    cells = [child for child in row.children if not isinstance(child, str)]
    item: dict = {}
    if row.has("admin-target-row--head"):
        item["tone"] = "head"
    for cell in cells:
        if cell.has("admin-next-step"):
            label = cell.text().rstrip(ARROW).strip()
            item.setdefault("actions", []).append(
                {
                    "key": _slug(label),
                    "label": label,
                    "enabled": True,
                    "href": cell.get("href"),
                }
            )
        elif cell.has("admin-status"):
            tone = next(
                (tone for marker, tone in STATUS_TONES if cell.has(marker)), "plain"
            )
            item.setdefault("badges", []).append({"text": cell.text(), "tone": tone})
        elif cell.has("admin-presence-bar"):
            bar = cell.find(lambda n: n.tag == "i")
            width = BAR_WIDTH.search(bar.get("style") if bar is not None else "")
            item["meter"] = {"fraction": float(width.group(1)) / 100 if width else 0.0}
        elif cell.tag == "strong":
            item["count"] = cell.text()
        elif "title" not in item and cell.text():
            item["title"] = cell.text()
            if cell.tag == "a":
                item["href"] = cell.get("href")
    # The page's order: title and link first, then the figure.
    return {
        key: item[key]
        for key in ("title", "href", "count", "badges", "actions", "meter", "tone")
        if key in item
    }


def read_admin_panel(node) -> dict:
    """The card as a list block of family admin-panel."""
    header = node.find(lambda n: n.has("admin-panel__header"))
    title = header.find(lambda n: n.tag in ("h2", "h3")) if header is not None else None
    caption = header.find(lambda n: n.tag == "span") if header is not None else None
    empty = node.find(lambda n: n.has("admin-panel__empty"))
    rows = [
        child
        for child in node.children
        if not isinstance(child, str) and child.has("admin-target-row")
    ]
    return {
        "list": {
            "title": title.text() if title is not None else "",
            "subtitle": caption.text()
            if caption is not None and caption.parent is header
            else "",
            "family": "admin-panel",
            "empty": empty.text() if empty is not None else "",
            "items": [_row(row) for row in rows],
        }
    }

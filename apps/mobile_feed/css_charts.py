"""Charts the web draws in CSS rather than from chart data, read as the
app's bar chart.

Two shapes:

* My Performance's indicator cards (partials/team_performance/_area_row.html):
  the indicator's name and "700 of 700 · 100% · On Track", then a chart of
  target and achieved bars per district or region (each bar's title holds
  its figure: "Mukono target: 700") over the same figures as a table. Read
  as the chart, then its table.
* A card of progress bars (My Targets' Contribution to Roll-up): a heading
  over rows of a label, a percentage and a bar. Read as one horizontal chart
  out of 100.
"""

from __future__ import annotations

import re

from apps.mobile_feed.page_blocks import Node

#: "Mukono target: 700": the bar's group, its series and its figure.
BAR_TITLE = re.compile(r"^(?P<series>[^:]+):\s*(?P<value>-?[\d,]*\.?\d+)\s*$")
WIDTH = re.compile(r"(?:^|;)\s*width:\s*(?P<pct>\d+(?:\.\d+)?)%")
PERCENT = re.compile(r"^\s*(?P<pct>-?\d+(?:\.\d+)?)\s*%\s*$")
MIN_BARS = 2
PERCENT_MAX = 100.0


# -- My Performance's indicator cards ---------------------------------------


def is_area_card(node: Node) -> bool:
    """An indicator card, or one of its charts on its own."""
    return (node.has("tp-card") and _charts_in(node) != []) or (
        "data-tp-chart" in node.attrs and _chart_of(node) is not None
    )


def read_area(node: Node) -> list[dict]:
    """The card's charts, each followed by its table."""
    from apps.mobile_feed import page_blocks

    head = node.find(lambda n: n.has("tp-card__head"))
    heading = head.find(lambda n: n.tag == "h2") if head is not None else None
    meta = head.find(lambda n: n.has("tp-card__meta")) if head is not None else None
    holders = _charts_in(node) if node.has("tp-card") else [node]
    blocks: list[dict] = []
    for holder in holders:
        caption = holder.find(lambda n: n.has("tp-chart-title"))
        title = (
            heading.text()
            if heading is not None and len(holders) == 1
            else (caption.text() if caption is not None else "")
        )
        chart = _chart_of(holder)
        blocks.append(
            {
                "chart": {
                    **chart,
                    "title": title,
                    "subtitle": meta.text() if meta is not None else "",
                }
            }
        )
        for table in holder.find_all(lambda n: n.tag == "table"):
            blocks.append({"table": page_blocks._table(table, table)})
    return blocks


def _charts_in(card: Node) -> list[Node]:
    return [
        holder
        for holder in card.find_all(lambda n: "data-tp-chart" in n.attrs)
        if _chart_of(holder) is not None
    ]


def _chart_of(holder: Node) -> dict | None:
    """The chart's bars: one category per group, one series per bar kind."""
    chart = holder.find(lambda n: n.has("tp-chart"))
    if chart is None:
        return None
    categories: list[str] = []
    series: dict[str, list[float]] = {}
    for group in chart.find_all(lambda n: n.has("tp-chart__group")):
        name = group.get("data-tp-bar")
        if not name:
            continue
        categories.append(name)
        for bar in group.find_all(lambda n: n.has("tp-chart__bar")):
            found = BAR_TITLE.match(bar.get("title").removeprefix(f"{name} "))
            if found is None:
                continue
            label = found.group("series").strip().capitalize()
            values = series.setdefault(label, [0.0] * (len(categories) - 1))
            values.append(float(found.group("value").replace(",", "")))
        for values in series.values():
            values.extend([0.0] * (len(categories) - len(values)))
    if not categories or not series:
        return None
    return {
        "horizontal": True,
        "categories": categories,
        "series": [
            {"name": label, "values": values} for label, values in series.items()
        ],
        "min": 0.0,
        "max": 0.0,
        "axisTitle": "",
    }


# -- A card of progress bars --------------------------------------------------


def bar_card(node: Node) -> dict | None:
    """A heading over a list of progress bars, as one chart out of 100."""
    parts = [child for child in node.children if isinstance(child, Node)]
    if len(parts) != 2 or parts[0].tag not in ("h2", "h3", "h4"):
        return None
    rows = [child for child in parts[1].children if isinstance(child, Node)]
    if len(rows) < MIN_BARS:
        return None
    read = [_bar_row(row) for row in rows]
    if any(row is None for row in read):
        return None
    title = parts[0].text()
    return {
        "title": title,
        "subtitle": "",
        "horizontal": True,
        "categories": [label for label, _ in read],
        "series": [{"name": title, "values": [value for _, value in read]}],
        "min": 0.0,
        "max": PERCENT_MAX,
        "axisTitle": "%",
    }


def _bar_row(row: Node) -> tuple[str, float] | None:
    """A row's label and percentage: two words over one filled track."""
    fills = row.find_all(lambda n: bool(WIDTH.search(n.get("style"))))
    if len(fills) != 1 or fills[0].parent is None:
        return None
    if not fills[0].parent.has("overflow-hidden"):
        return None
    texts = [
        leaf.text()
        for leaf in row.nodes()
        if isinstance(leaf, Node)
        and not any(isinstance(child, Node) for child in leaf.children)
        and leaf.text()
    ]
    if len(texts) != 2:
        return None
    label, figure = texts
    shown = PERCENT.match(figure)
    width = WIDTH.search(fills[0].get("style"))
    return label, float(shown.group("pct") if shown else width.group("pct"))

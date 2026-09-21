"""Charts reuse already-scoped view data; tags never query or widen access."""

import math
from django import template

register = template.Library()


def _number(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError):
        return None


def _split(csv: str) -> list[str]:
    return [part.strip() for part in csv.split(",")]


def _card(title, subtitle, payload):
    return {"title": title, "subtitle": subtitle or "", "chart_payload": payload}


@register.inclusion_tag("components/bar_chart.html")
def summary_chart(summary, keys, labels, title, subtitle=""):
    keys = _split(keys)
    labels = _split(labels)
    return _card(
        title,
        subtitle,
        {
            "chart": {"type": "bar"},
            "series": [
                {
                    "name": "Count",
                    "data": [_number((summary or {}).get(key)) for key in keys],
                }
            ],
            "xaxis": {"categories": labels},
        },
    )


@register.inclusion_tag("components/bar_chart.html")
def comparison_chart(
    rows,
    label_key,
    value_key,
    comparison_key,
    title,
    value_label,
    comparison_label,
    subtitle="",
):
    rows = list(rows or [])
    return _card(
        title,
        subtitle,
        {
            "chart": {"type": "bar"},
            "plotOptions": {"bar": {"horizontal": True}},
            "series": [
                {
                    "name": value_label,
                    "data": [_number(row.get(value_key)) for row in rows],
                },
                {
                    "name": comparison_label,
                    "data": [_number(row.get(comparison_key)) for row in rows],
                },
            ],
            "xaxis": {
                "categories": [str(row.get(label_key) or "Unnamed") for row in rows]
            },
        },
    )


@register.inclusion_tag("components/bar_chart.html")
def score_chart(rows, label_key, score_key, title, subtitle=""):
    rows = list(rows or [])
    return _card(
        title,
        subtitle,
        {
            "chart": {"type": "bar"},
            "plotOptions": {"bar": {"horizontal": True}},
            "series": [
                {
                    "name": "SSA score",
                    "data": [_number(row.get(score_key)) for row in rows],
                }
            ],
            "xaxis": {
                "categories": [str(row.get(label_key) or "Unnamed") for row in rows]
            },
            "yaxis": {"min": 0, "max": 10, "title": {"text": "SSA score (0–10)"}},
        },
    )


@register.inclusion_tag("components/bar_chart.html")
def team_chart(rows, name_key, keys, labels, title, subtitle=""):
    """One series per person, grouped under each measure.

    A lead reads their team as people, so every officer (and the lead) is a
    series of their own and keeps the same colour on every chart of the page:
    the series order is the row order, and the renderer assigns colour by that
    position rather than by whichever series happens to be drawn. A measure a
    row does not carry stays unmeasured rather than becoming zero.
    """
    keys = _split(keys)
    labels = _split(labels)
    rows = list(rows or [])
    return _card(
        title,
        subtitle,
        {
            "chart": {"type": "bar"},
            "series": [
                {
                    "name": str(row.get(name_key) or "Unnamed"),
                    "data": [_number(row.get(key)) for key in keys],
                }
                for row in rows
            ],
            "xaxis": {"categories": labels},
        },
    )

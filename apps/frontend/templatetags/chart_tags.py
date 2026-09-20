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


@register.inclusion_tag("components/bar_chart.html")
def summary_chart(summary, keys, labels, title):
    keys = keys.split(",")
    labels = labels.split(",")
    return {"title": title, "chart_payload": {
        "chart": {"type": "bar"},
        "series": [{"name": "Count", "data": [_number((summary or {}).get(key)) for key in keys]}],
        "xaxis": {"categories": labels},
    }}


@register.inclusion_tag("components/bar_chart.html")
def comparison_chart(rows, label_key, value_key, comparison_key, title, value_label, comparison_label):
    rows = list(rows or [])
    return {"title": title, "chart_payload": {
        "chart": {"type": "bar"},
        "plotOptions": {"bar": {"horizontal": True}},
        "series": [
            {"name": value_label, "data": [_number(row.get(value_key)) for row in rows]},
            {"name": comparison_label, "data": [_number(row.get(comparison_key)) for row in rows]},
        ],
        "xaxis": {"categories": [str(row.get(label_key) or "Unnamed") for row in rows]},
    }}


@register.inclusion_tag("components/bar_chart.html")
def score_chart(rows, label_key, score_key, title):
    rows = list(rows or [])
    return {"title": title, "chart_payload": {
        "chart": {"type": "bar"},
        "plotOptions": {"bar": {"horizontal": True}},
        "series": [{"name": "SSA score", "data": [_number(row.get(score_key)) for row in rows]}],
        "xaxis": {"categories": [str(row.get(label_key) or "Unnamed") for row in rows]},
        "yaxis": {"min": 0, "max": 10, "title": {"text": "SSA score (0–10)"}},
    }}

"""Charts reuse already-scoped view data; tags never query or widen access."""

import json
import math

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


_JS_ESCAPES = {ord(">"): "\\u003E", ord("<"): "\\u003C", ord("&"): "\\u0026"}


@register.filter
def js_data(value):
    """A Python value as a JavaScript literal for an inline chart series.

    ``{{ series|escape }}`` printed a Python list, so a month with no rate
    rendered ``None`` and the Country Director's operations chart died with
    "None is not defined" (2026-09-27 platform sweep). JSON writes ``null``,
    which the charts draw as a gap; ``<``, ``>`` and ``&`` are escaped so the
    value cannot close the surrounding <script>."""
    from django.core.serializers.json import DjangoJSONEncoder

    # Safe to mark: the value is JSON (numbers, null, quoted strings), and the
    # three characters that could end the <script> or start markup are
    # escaped, as django.utils.html.json_script does. Suppressed unqualified
    # because B308 is a blacklist check and ignores a test-id list.
    return mark_safe(  # nosec B308 B703
        json.dumps(value, cls=DjangoJSONEncoder).translate(_JS_ESCAPES)
    )


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


def _card(title, subtitle, payload, bare=False):
    """``bare`` draws the chart without a card of its own, for a section
    that already is one."""
    return {
        "title": title,
        "subtitle": subtitle or "",
        "chart_payload": payload,
        "bare": bare,
    }


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


SSA_SCORE_AXIS = {"min": 0, "max": 10, "title": {"text": "SSA score (0–10)"}}


def _year_payload(labels, previous, current, previous_label, current_label):
    """Last year's bar under this year's on one line (the cut-out the shared
    standard draws for two horizontal series). With nothing confirmed last
    year there is one series: a second, empty one would say "Not measured"
    on every row."""
    series = [{"name": current_label, "data": current}]
    if any(value is not None for value in previous):
        series.insert(0, {"name": previous_label, "data": previous})
    return {
        "chart": {"type": "bar"},
        "plotOptions": {"bar": {"horizontal": True}},
        "series": series,
        "xaxis": {"categories": labels},
        "yaxis": SSA_SCORE_AXIS,
    }


@register.inclusion_tag("components/bar_chart.html")
def ssa_year_chart(comparison, title, subtitle="", bare=False):
    """Each SSA intervention this year beside last year
    (`apps.ssa.year_comparison.intervention_comparison`)."""
    comparison = comparison or {}
    rows = list(comparison.get("rows") or [])
    return _card(*_year_card(comparison, rows, title, subtitle), bare=bare)


def _year_card(comparison, rows, title, subtitle):
    return (
        title,
        subtitle
        or (
            f"{comparison.get('previous_label')} and {comparison.get('label')}"
            if comparison.get("has_previous")
            else comparison.get("label", "")
        ),
        _year_payload(
            [row["label"] for row in rows],
            [_number(row.get("previous")) for row in rows],
            [_number(row.get("current")) for row in rows],
            comparison.get("previous_label") or "Previous FY",
            comparison.get("label") or "This FY",
        ),
    )


@register.inclusion_tag("components/bar_chart.html")
def ssa_year_rows_chart(
    rows,
    label_key,
    previous_key,
    current_key,
    previous_label,
    current_label,
    title,
    subtitle="",
):
    """Any SSA grouping — districts, staff, clusters — this year beside
    last year, from rows that carry both scores."""
    rows = list(rows or [])
    return _card(
        title,
        subtitle,
        _year_payload(
            [str(row.get(label_key) or "Unnamed") for row in rows],
            [_number(row.get(previous_key)) for row in rows],
            [_number(row.get(current_key)) for row in rows],
            previous_label,
            current_label,
        ),
    )


@register.inclusion_tag("components/bar_chart.html")
def ssa_progress_chart(rows, title, subtitle=""):
    """The average confirmed SSA score of each financial year, one bar a
    year (`apps.ssa.services.get_ssa_progress_by_fy`, or a school's own
    `progress_by_fy`)."""
    from apps.ssa.year_comparison import fy_label

    rows = list(rows or [])

    def name(row):
        label = fy_label(row.get("fy"))
        count = row.get("school_count")
        if count is None:
            return label
        return f"{label} ({count} school{'' if count == 1 else 's'})"

    return _card(
        title,
        subtitle,
        {
            "chart": {"type": "bar"},
            "plotOptions": {"bar": {"horizontal": True}},
            "series": [
                {
                    "name": "Average SSA score",
                    "data": [_number(row.get("avg_score")) for row in rows],
                }
            ],
            "xaxis": {"categories": [name(row) for row in rows]},
            "yaxis": SSA_SCORE_AXIS,
        },
    )

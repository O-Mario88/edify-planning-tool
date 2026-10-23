"""Figures on the Team Performance page: a missing figure is a dash, never 0
(docs/team-performance-report.md)."""

from __future__ import annotations

from django import template

register = template.Library()

DASH = "—"


@register.filter
def num(value):
    """1,234 for a count; one decimal place only where the figure has one."""
    if value is None or value == "":
        return DASH
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.1f}"


@register.filter
def pct(value):
    if value is None or value == "":
        return DASH
    try:
        return f"{float(value):,.1f}%".replace(".0%", "%")
    except (TypeError, ValueError):
        return DASH


@register.filter
def signed(value):
    """+12 / −3 / 0 for a change."""
    if value is None or value == "":
        return DASH
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = num(abs(number))
    if number > 0:
        return f"+{text}"
    if number < 0:
        return f"−{text}"
    return "0"


@register.filter
def tone(share):
    """The band a percentage of target sits in: the workbook's 100% / 75%."""
    if share is None or share == "":
        return ""
    share = float(share)
    if share >= 100:
        return "good"
    if share >= 75:
        return "fair"
    return "low"


@register.filter
def bar(share):
    """A progress bar's width, held to 0–100."""
    if share is None or share == "":
        return 0
    return round(min(100.0, max(0.0, float(share))), 1)


@register.filter
def column(cols, key):
    """A {Month} {Year} Summary cell: a percentage for a "_p" column, else a
    count."""
    value = (cols or {}).get(key)
    return pct(value) if str(key).endswith("_p") else num(value)


@register.filter
def column_tone(cols, key):
    return tone((cols or {}).get(key)) if str(key).endswith("_p") else ""

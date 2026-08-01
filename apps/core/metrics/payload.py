"""Turns a registered metric plus a measured value into what a template renders.

Templates must not infer a metric's meaning from a bare number, and they must
not decide whether a blank is a zero. Both decisions happen here, once, using
the registry entry -- so a tile's label, unit, period, drill-down and
missing-data wording all come from the same declaration the guard tests read.

The rendered dict is intentionally flat and stable: ``data-metric-key`` on the
card is what the duplication test greps for, and it can only be right if every
tile is built through this function.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.metrics.registry import get_metric
from apps.core.metrics.spec import MetricSpec, Unit
from apps.core.metrics.states import DataState, MetricValue


def format_value(spec: MetricSpec, value: int | float) -> str:
    """Display form for a measured value. Formatting only -- never arithmetic."""
    if spec.unit is Unit.PERCENT:
        # Trailing ".0" reads as false precision on a whole percentage.
        return f"{value:g}%"
    if spec.unit is Unit.MONEY_UGX:
        return f"UGX {value:,.0f}"
    if spec.unit is Unit.COUNT:
        return f"{value:,}"
    if spec.unit is Unit.DAYS:
        return f"{value:g} days" if value != 1 else "1 day"
    return f"{value:g}"


def accessible_description(spec: MetricSpec, measured: MetricValue) -> str:
    """A sentence a screen reader can read out.

    Section 34: exposing only "82% ↑" tells a non-visual reader the number and
    nothing about what it measures or what it rose against.
    """
    if not measured.state.is_measured:
        return f"{spec.label}: {measured.display_text}."
    body = f"{spec.label}: {format_value(spec, measured.value)}"
    if spec.unit is Unit.PERCENT and measured.denominator:
        body += f", of {measured.denominator:,}"
    return body + "."


@dataclass(frozen=True)
class RenderedMetric:
    """What a KPI card needs, and nothing it should be left to work out."""

    metric_key: str
    label: str
    value: int | float | None
    display_value: str
    unit: str
    period: str
    scope: str
    data_state: str
    definition: str
    accessible_description: str
    drilldown_url: str | None
    denominator: int | float | None
    is_measured: bool

    def as_dict(self) -> dict:
        return {
            "metric_key": self.metric_key,
            "label": self.label,
            "value": self.value,
            "display_value": self.display_value,
            "unit": self.unit,
            "period": self.period,
            "scope": self.scope,
            "data_state": self.data_state,
            "definition": self.definition,
            "accessible_description": self.accessible_description,
            "drilldown_url": self.drilldown_url,
            "denominator": self.denominator,
            "is_measured": self.is_measured,
        }


def render_strip(
    tiles: list[RenderedMetric],
    *,
    allow_repeats: frozenset[str] = frozenset(),
) -> list[dict]:
    """Template-ready items for one KPI strip, refusing same-strip duplicates.

    Section 5 of the KPI mandate: a metric appears once on a page unless a
    second representation adds a different analytical dimension. A strip
    showing one metric twice is never that -- it is a copy-paste, and it is
    invisible in review because both tiles look correct in isolation.

    ``allow_repeats`` is the documented exception list. It takes metric keys,
    so an exception has to be argued for a named metric rather than switched
    off for the whole strip.
    """
    seen: dict[str, int] = {}
    for tile in tiles:
        seen[tile.metric_key] = seen.get(tile.metric_key, 0) + 1

    repeated = sorted(
        key for key, n in seen.items() if n > 1 and key not in allow_repeats
    )
    if repeated:
        raise ValueError(
            f"metric(s) rendered more than once in one strip: {repeated} -- "
            f"remove the duplicate, or pass the key in allow_repeats with a "
            f"stated reason"
        )
    return [tile.as_dict() for tile in tiles]


def render_metric(
    key: str,
    measured: MetricValue,
    *,
    drilldown_url: str | None = None,
) -> RenderedMetric:
    """Bind a measured value to its registry entry, ready for a template."""
    spec = get_metric(key)

    if (
        spec.is_ratio
        and measured.state is DataState.MEASURED
        and not measured.denominator
    ):
        raise ValueError(
            f"{key}: a percentage must carry the denominator it was computed "
            f"from -- use MetricValue.ratio()"
        )

    display = (
        format_value(spec, measured.value)
        if measured.state.is_measured
        else measured.display_text
    )

    return RenderedMetric(
        metric_key=spec.key,
        label=spec.label,
        value=measured.value,
        display_value=display,
        unit=spec.unit.value,
        period=spec.period.value,
        scope=spec.scope,
        data_state=measured.state.value,
        definition=spec.definition,
        accessible_description=accessible_description(spec, measured),
        drilldown_url=drilldown_url,
        denominator=measured.denominator,
        is_measured=measured.state.is_measured,
    )


def render_kpi_item(
    key: str,
    measured: MetricValue,
    *,
    helper: str,
    tone: str = "neutral",
    drilldown_url: str | None = None,
    icon: str | None = None,
) -> dict:
    """Return one registry-backed item for the shared KPI strip.

    Meaning stays in :class:`MetricSpec`; this adapter adds only the local
    presentation treatment.  Keeping the adapter here prevents views from
    rebuilding ``label``/``value`` dictionaries that have no stable identity.
    """

    item = render_metric(
        key,
        measured,
        drilldown_url=drilldown_url,
    ).as_dict()
    item.update({"helper": helper, "tone": tone})
    if icon:
        item["icon"] = icon
    return item

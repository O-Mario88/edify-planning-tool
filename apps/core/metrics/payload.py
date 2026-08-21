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
from apps.core.metrics.states import DEFAULT_STATE_TEXT, DataState, MetricValue


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


@dataclass(frozen=True)
class PresentationKpi:
    """A shared presentation DTO for a server fact awaiting registry binding.

    It exists so template-era values still travel through one typed boundary
    instead of recreating ad-hoc dictionaries in every view. Canonical metrics
    should continue to use :class:`RenderedMetric`.
    """

    label: str
    value: object
    display_value: object
    helper: str = ""
    tone: str = "neutral"
    icon: str = "chart"
    link: str | None = None
    hx_get: str | None = None

    def as_dict(self) -> dict:
        return vars(self)


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


def consolidate_kpi_items(items, *, max_items: int = 6) -> list[dict]:
    """Return a bounded, identity-deduplicated headline set.

    A professional headline tray is not an inventory of every number a page
    can calculate. Registered metrics are deduplicated by stable identity and
    retained in product-authored source order. Categories remain useful audit
    metadata, but are deliberately not a deletion rule: two scale, finance or
    progress metrics can answer different business questions. Legacy items use
    their normalized label as the temporary identity. The returned list is a
    new render payload; surplus values are not hidden in CSS or moved into a
    disclosure.
    """

    if max_items < 0:
        raise ValueError("max_items must be zero or greater")
    if max_items == 0:
        return []

    prepared: list[dict] = []
    seen_identities: set[str] = set()
    for source_item in items or ():
        item = (
            source_item.as_dict()
            if hasattr(source_item, "as_dict")
            else dict(source_item)
        )
        metric_key = item.get("metric_key")
        label = str(item.get("canonical_label") or item.get("label") or "").strip()
        identity = str(metric_key or label.casefold())
        if not identity or identity in seen_identities:
            continue
        seen_identities.add(identity)

        prepared.append(item)

    return prepared[:max_items]


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


_UNSET = object()
_ABSENT_DISPLAY_VALUES = frozenset(
    {"", "—", "-", "no data", "no ssa", "not available", "not set"}
)


def render_precomputed_metric_item(
    metric_key: str,
    display_value,
    *,
    raw_value=_UNSET,
    data_state: DataState | None = None,
    drilldown_url: str | None = None,
    **presentation,
) -> dict:
    """Bind an existing server-computed display value to a registered metric.

    Older services already perform their arithmetic on the server, but return
    formatted strings such as ``"82%"``, ``"UGX 4.2m"`` or ``"4 / 7"``.
    Recomputing those values during registry migration would change business
    logic. This renderer preserves that result while adding canonical identity,
    definition, period, scope, state and an accessible description.
    """

    spec = get_metric(metric_key)
    shown = "" if display_value is None else str(display_value)
    inferred_absence = (
        display_value is None
        or (raw_value is not _UNSET and raw_value is None)
        or shown.strip().casefold() in _ABSENT_DISPLAY_VALUES
    )
    state = data_state or (
        DataState.NO_DATA if inferred_absence else DataState.MEASURED
    )
    is_measured = state.is_measured

    if raw_value is _UNSET:
        raw = display_value if isinstance(display_value, (int, float)) else None
    else:
        raw = raw_value
    if not is_measured:
        raw = None

    rendered_display = (
        shown if is_measured or shown else DEFAULT_STATE_TEXT.get(state, "No data")
    )
    route = drilldown_url
    if route is None and spec.drilldown and spec.drilldown.startswith("/"):
        route = spec.drilldown

    from apps.core.metrics.reconciled_registry import source_label_for_key

    item = {
        "metric_key": spec.key,
        # Keep ``label`` as the service contract while downstream Python moves
        # from display-label lookup to ``metric_key``. Shared UI components use
        # canonical_label, whose scope qualifier resolves formerly duplicated
        # labels without breaking non-visual integrations in the same release.
        "label": source_label_for_key(spec.key),
        "canonical_label": spec.label,
        # Preserve the legacy display contract: a few templates compare
        # ``item.value`` with strings such as "0%". ``raw_value`` remains the
        # machine-readable measurement when the service already exposes one.
        "value": display_value if is_measured else rendered_display,
        "raw_value": raw,
        "display_value": rendered_display,
        "unit": spec.unit.value,
        "period": spec.period.value,
        "scope": spec.scope,
        "data_state": state.value,
        "definition": spec.definition,
        "accessible_description": f"{spec.label}: {rendered_display}.",
        "drilldown_url": route,
        "denominator": None,
        "is_measured": is_measured,
    }
    item.update(presentation)
    return item


def render_precomputed_metric_for_source(
    source: str,
    label: str,
    display_value,
    **presentation,
) -> dict:
    """Resolve a dynamic legacy card factory by its audited source and label."""

    from apps.core.metrics.reconciled_registry import key_for_source_label

    return render_precomputed_metric_item(
        key_for_source_label(source, label),
        display_value,
        **presentation,
    )

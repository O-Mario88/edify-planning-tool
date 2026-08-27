"""Template boundary for the platform's headline-KPI policy."""

from django import template

from apps.core.metrics import PresentationKpi, consolidate_kpi_items


register = template.Library()


@register.simple_tag
def professional_kpis(items, variant="executive", density=None):
    """Build the final render payload instead of hiding surplus cards.

    FE-02, decided: the dashboard tray no longer caps at six. The count
    follows the work — "it should not limit to 4 or 6 based on how many things
    need to be tracked" — so a page that registers eight metrics shows eight.
    Fourteen payload groups were feeding more than six into a six-slot tray and
    losing the rest with nothing on screen to say so.

    The compact density keeps its limit of two, and that one is a layout fact
    rather than a policy: the mobile tray is two cards wide and reflows badly
    past that. It is the only cap left, and because it is real, the surface
    that uses it should disclose what it left out — ``dropped_kpi_items``
    answers that.
    """

    if density == "compact":
        return consolidate_kpi_items(items, max_items=2)
    return consolidate_kpi_items(items)


@register.simple_tag
def legacy_kpi_item(
    label,
    value,
    *,
    helper="",
    tone="neutral",
    icon="chart",
    link=None,
    hx_get=None,
):
    """Adapt a remaining template-owned fact to the shared card contract.

    This is deliberately presentation-only. It lets older views enter the one
    component immediately while their formulas are progressively moved into
    the metric registry; it does not pretend that a label/value pair is a
    canonical metric definition.
    """

    return PresentationKpi(
        label=str(label),
        value=value,
        display_value=value,
        helper=str(helper),
        tone=str(tone),
        icon=str(icon),
        link=link,
        hx_get=hx_get,
    )


@register.simple_tag
def collect_kpi_items(*items):
    """Collect named template variables into one shared-component payload."""

    return [item for item in items if item]

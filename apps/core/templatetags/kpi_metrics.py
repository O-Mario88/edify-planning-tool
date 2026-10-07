"""Template boundary for the platform's contextual-metric policy."""

from html import unescape
import re

from django import template
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from apps.core.metrics import PresentationKpi, consolidate_kpi_items


register = template.Library()


@register.simple_tag
def professional_kpis(items, variant="executive", density=None):
    """Keep every unique metric; responsive overflow controls visible count.

    An intervention named in a helper is abbreviated for the tile and kept
    whole for its title (owner, 2026-09-12: "abbreviate the intervention
    names inside the KPIs … in all the KPIs and stats strips").
    """
    from apps.core.interventions import abbreviate_interventions, mentions_intervention
    from apps.core.metrics.payload import HELPER_FIGURE_CHARS, brief_helper

    prepared = []
    for item in consolidate_kpi_items(items):
        helper = item.get("helper") if hasattr(item, "get") else None
        if mentions_intervention(helper):
            item = dict(item)
            item["helper_exact"] = helper
            item["helper"] = abbreviate_interventions(helper)
        # The line under the figure is a second figure or nothing (owner,
        # 2026-10-07: "minimize the explanations so the focus is on the actual
        # KPI"). The sentence it was is kept whole for the hover text and for
        # a screen reader, so nothing a tile said is lost.
        shown = item.get("helper") if hasattr(item, "get") else None
        # A line that names an intervention ("Weakest: TE") is a second fact
        # about the figure, not an explanation of it: kept when it is short.
        names_a_fact = bool(item.get("helper_exact")) if hasattr(item, "get") else False
        if shown and not (names_a_fact and len(str(shown)) <= HELPER_FIGURE_CHARS):
            brief = brief_helper(shown)
            if brief != shown:
                item = dict(item)
                item["helper_note"] = item.get("helper_exact") or helper
                item["helper"] = brief
        prepared.append(item)
    return prepared


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
    """Adapt a remaining template-owned fact to the shared context contract.

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


# Template-authored summaries use the same renderer as registered payloads.
# Block values retain existing filters, conditional states, and loop scope.


def _metric_text(value):
    return " ".join(
        unescape(strip_tags(re.sub(r"</(?:span|div|p)>", " ", value))).split()
    )


class MetricFieldNode(template.Node):
    def __init__(self, field, body):
        self.field, self.body = field, body

    def render(self, context):
        item = context.get("_platform_kpi_item")
        if item is None:
            raise template.TemplateSyntaxError("KPI fields require kpi_metric")
        value = _metric_text(self.body.render(context))
        item[self.field] = " · ".join(filter(None, (item.get(self.field), value)))
        return ""


def _field_tag(field):
    def parse(parser, token):
        body = parser.parse(("end" + token.contents,))
        parser.delete_first_token()
        return MetricFieldNode(field, body)

    return parse


for _name in ("label", "helper", "link", "hx_get", "current"):
    register.tag("kpi_" + _name, _field_tag(_name))


class MetricNode(template.Node):
    def __init__(self, body):
        self.body = body

    def render(self, context):
        items = context.get("_platform_kpi_items")
        if items is None:
            raise template.TemplateSyntaxError("kpi_metric requires kpi_strip")
        item = {}
        with context.push(_platform_kpi_item=item):
            item["value"] = _metric_text(self.body.render(context)) or "—"
        if item.get("label"):
            items.append(item)
        return ""


@register.tag("kpi_metric")
def parse_metric(parser, token):
    body = parser.parse(("endkpi_metric",))
    parser.delete_first_token()
    return MetricNode(body)


class MetricStripNode(template.Node):
    def __init__(self, body, live_id=""):
        self.body = body
        # An id that makes the strip a live region: it reads itself again
        # when the plan changes (static/js/live-regions.js).
        self.live_id = live_id

    def render(self, context):
        items = []
        with context.push(_platform_kpi_items=items):
            self.body.render(context)
        values = context.flatten()
        values.update(
            items=items,
            title="",
            subtitle="",
            density=None,
            variant="executive",
            drilldown_mode="",
            live_id=self.live_id,
        )
        return render_to_string("components/context_metrics.html", values)


@register.tag("kpi_strip")
def parse_metric_strip(parser, token):
    live_id = ""
    for bit in token.split_contents()[1:]:
        name, _, value = bit.partition("=")
        if name != "live_id" or not value:
            raise template.TemplateSyntaxError(
                'kpi_strip takes one optional argument: live_id="an-id"'
            )
        live_id = value.strip("\"'")
    body = parser.parse(("endkpi_strip",))
    parser.delete_first_token()
    return MetricStripNode(body, live_id)


@register.simple_tag
def kpi_value(item):
    """Compact large currency displays without losing the exact source value."""
    from decimal import Decimal, InvalidOperation

    value = item.get("display_value")
    if value is None or value == "":
        value = item.get("value", "—")
    exact = str(value) if value is not None else "—"
    result = {"exact": exact, "display": exact, "compact": False}
    # "Exposure to the Word of God" reads as "WOG" in a tile; the title keeps
    # the whole name (owner, 2026-09-12).
    from apps.core.interventions import abbreviate_interventions, mentions_intervention

    if mentions_intervention(exact):
        result["display"] = abbreviate_interventions(exact)
        return result
    match = re.fullmatch(
        r"(UGX|USD|EUR|GBP|KES|TZS|RWF)\s+(-?\d[\d,]*(?:\.\d+)?)", exact
    )
    if not match:
        return result
    try:
        amount = Decimal(match[2].replace(",", ""))
    except InvalidOperation:
        return result
    for divisor, suffix in (
        (Decimal("1000000000000"), "T"),
        (Decimal("1000000000"), "B"),
        (Decimal("1000000"), "M"),
    ):
        if abs(amount) >= divisor:
            short = f"{amount / divisor:.2f}".rstrip("0").rstrip(".")
            result.update(display=f"{match[1]} {short}{suffix}", compact=True)
            break
    return result

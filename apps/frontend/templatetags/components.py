"""The platform's page components, as template tags with a fixed API.

The UI audit of 2026-10-01 traced most visual drift to one cause: a page is
hand-written markup that 50,000 lines of CSS then restyle by heuristic. Two
hundred templates each wrote their own page header; fourteen filter forms each
decided for themselves whether to carry an Apply button. A component is the
other way round: the page says WHAT it has — a header with this title, a
filter bar with these fields, a table with this caption — and one template
decides the markup, so a change to the anatomy is one edit.

    {% load components %}

    {% page_header eyebrow="Finance" title="Cost Catalogue" description=intro %}
      <a href="{{ add_url }}" class="edify-action-button primary h-9">Add cost</a>
    {% endpage_header %}

    {% filter_bar action="/programme-schools" label="Programme school filters" %}
      <label class="block">…<select name="district">…</select></label>
    {% endfilter_bar %}

    {% data_table name="overdue" title="Manager actions overdue" %}
      {% slot summary %}{{ total }} actions{% endslot %}
      <thead>…</thead>
      <tbody>…</tbody>
    {% enddata_table %}

Arguments are template expressions: a quoted string, a variable, a variable
with filters. A part that needs template logic of its own is written as a
slot inside the tag instead:

    {% page_header title="Planning Oversight" %}
      {% slot description %}{% if lens == "region" %}Your region's…{% else %}Your team's…{% endif %}{% endslot %}
      …controls…
    {% endpage_header %}

Everything left in the body after the slots is the component's main slot: a
header's controls, a filter bar's fields, a table's rows.

Adoption is tracked, and held, by apps/frontend/test_component_adoption.py;
the anatomy and the migration notes are in docs/ui-components.md.
"""

from __future__ import annotations

from django import template
from django.template.loader import get_template
from django.utils.safestring import mark_safe

register = template.Library()


class SlotNode(template.Node):
    """A named part of the enclosing component. Renders nothing on its own:
    the component reads it."""

    def __init__(self, name: str, nodelist):
        self.name = name
        self.nodelist = nodelist

    def render(self, context):
        return ""


@register.tag("slot")
def slot(parser, token):
    """``{% slot name %} … {% endslot %}`` inside a component tag."""
    bits = token.split_contents()
    if len(bits) != 2:
        raise template.TemplateSyntaxError("{% slot %} takes one argument, its name.")
    nodelist = parser.parse(("endslot",))
    parser.delete_first_token()
    return SlotNode(bits[1], nodelist)


def _arguments(parser, token, allowed: tuple[str, ...]) -> dict:
    """``name=expression`` pairs, compiled; a name the component does not
    know is an error at template load rather than a part silently dropped."""
    bits = token.split_contents()
    tag = bits[0]
    arguments = {}
    for bit in bits[1:]:
        name, separator, expression = bit.partition("=")
        if not separator or name not in allowed:
            raise template.TemplateSyntaxError(
                f"{{% {tag} %}} takes {', '.join(allowed)} as name=value; got {bit!r}."
            )
        arguments[name] = parser.compile_filter(expression)
    return arguments


class ComponentNode(template.Node):
    """A component: its arguments and slots resolved, its remaining body
    rendered as the main slot, and one template deciding the markup."""

    template_name = ""
    body_name = "body"
    slots: tuple[str, ...] = ()

    def __init__(self, nodelist, arguments):
        self.arguments = arguments
        self.slot_nodes = {
            node.name: node for node in nodelist if isinstance(node, SlotNode)
        }
        unknown = set(self.slot_nodes) - set(self.slots)
        if unknown:
            raise template.TemplateSyntaxError(
                f"{type(self).__name__} has no slot named {', '.join(sorted(unknown))}."
            )
        self.nodelist = nodelist

    def render(self, context):
        # Rendered in the caller's own context, so the body keeps its
        # variables, its csrf token and its autoescaping. What comes back is
        # markup the caller's template already escaped; str.strip() drops the
        # safe mark, so it is put back for the component template to print.
        values = {
            name: expression.resolve(context)
            for name, expression in self.arguments.items()
        }
        for name, node in self.slot_nodes.items():
            values[name] = mark_safe(node.nodelist.render(context).strip())  # noqa: S308
        values[self.body_name] = mark_safe(self.nodelist.render(context).strip())  # noqa: S308
        return get_template(self.template_name).render(values)


class PageHeaderNode(ComponentNode):
    template_name = "components/page_header.html"
    body_name = "page_header_controls"
    slots = ("eyebrow", "title", "description", "aside")


@register.tag("page_header")
def page_header(parser, token):
    """The canonical page header: eyebrow, title, description, and the page's
    few controls as the body. ``element="div"`` keeps a wrapper that was a
    div; the default is ``<header>``. ``{% slot aside %}`` is for the rare
    header that carries something else beside its lead (an export menu that
    HTMX re-sends, a KPI strip): it is drawn after the controls, as written."""
    arguments = _arguments(
        parser,
        token,
        ("eyebrow", "title", "description", "element", "page_header_class"),
    )
    nodelist = parser.parse(("endpage_header",))
    parser.delete_first_token()
    return PageHeaderNode(nodelist, arguments)


class FilterBarNode(ComponentNode):
    template_name = "components/filter_bar.html"
    body_name = "fields"


@register.tag("filter_bar")
def filter_bar(parser, token):
    """A page's filter row. The fields are the body; the row applies itself
    when a field changes (the platform's one filter model since 2026-10-01)
    and keeps a submit button only for a browser without JavaScript."""
    arguments = _arguments(
        parser, token, ("action", "label", "form_id", "extra_class", "reset_url")
    )
    nodelist = parser.parse(("endfilter_bar",))
    parser.delete_first_token()
    return FilterBarNode(nodelist, arguments)


class DataTableNode(ComponentNode):
    template_name = "components/data_table.html"
    body_name = "rows"
    slots = ("title", "summary", "caption", "empty", "footer")


@register.tag("data_table")
def data_table(parser, token):
    """A record table in its card: the title band, the scroll region and the
    table. The body is the ``<thead>``, ``<tbody>`` and ``<tfoot>``; a body
    that renders nothing draws ``{% slot empty %}`` in the table's place.
    ``name`` ties the card to its title for a screen reader; ``summary`` is
    the line at the end of the title band, ``footer`` what follows the table
    (its pager, its notes)."""
    arguments = _arguments(parser, token, ("name", "title", "caption"))
    nodelist = parser.parse(("enddata_table",))
    parser.delete_first_token()
    return DataTableNode(nodelist, arguments)

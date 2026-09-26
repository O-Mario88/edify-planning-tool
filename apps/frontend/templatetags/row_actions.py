"""One record's actions as the platform's Actions menu.

Owner, 2026-09-26: on a tablet a row's Schedule and Assign buttons wrapped
onto two lines; "for it to be neat, switch to Action button with options to
schedule and assign. Every page use actions with dropdown options."

    {% load row_actions %}
    {% row_actions school.name %}
      <button type="button" class="row-menu__item" role="menuitem"
              hx-get="/planning/schedule-modal?school_id=…"
              hx-target="#drawer-container" hx-swap="innerHTML">Schedule</button>
      <button type="button" class="row-menu__item" role="menuitem"
              aria-disabled="true">Assign<span class="row-menu__reason">Why not</span></button>
    {% endrow_actions %}

The caller writes the items, so each keeps its own htmx, link or form; the
tag wraps them in components/row_actions.html, the one trigger and list every
page shares. A row with no action to offer renders nothing at all.
"""

from django import template
from django.template.loader import get_template

register = template.Library()


class RowActionsNode(template.Node):
    def __init__(self, nodelist, name):
        self.nodelist = nodelist
        self.name = name

    def render(self, context):
        # The caller's items, rendered (and autoescaped) in the caller's own
        # context: NodeList.render already returns them as a SafeString, so
        # the shell prints them as they are without marking anything safe.
        items = self.nodelist.render(context)
        if not items.strip():
            return ""
        name = self.name.resolve(context) if self.name is not None else ""
        return get_template("components/row_actions.html").render(
            {"items": items, "name": name}
        )


@register.tag("row_actions")
def row_actions(parser, token):
    """``{% row_actions [record name] %} … {% endrow_actions %}``."""
    bits = token.split_contents()
    if len(bits) > 2:
        raise template.TemplateSyntaxError(
            "{% row_actions %} takes at most one argument, the record's name."
        )
    name = parser.compile_filter(bits[1]) if len(bits) == 2 else None
    nodelist = parser.parse(("endrow_actions",))
    parser.delete_first_token()
    return RowActionsNode(nodelist, name)

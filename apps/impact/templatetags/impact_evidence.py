"""Template tags for Impact Assessment's dashboard views (IA review, 2026-09-13).

The Collection view's tiles need the reader and the worklist the view already
built; the dashboard view (apps/frontend/views/ia_views.py) hands the template
the worklist, and this tag turns it into registry tiles where the Collection
view renders them, so no other view pays for the count of unmatched rows.
"""

from __future__ import annotations

from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def ia_collection_tiles(context, worklist):
    """{% ia_collection_tiles ia_collection as collection_tiles %}"""
    from apps.analytics.ia_collection import collection_tiles

    request = context.get("request")
    user = getattr(request, "user", None)
    if user is None or not worklist:
        return []
    return collection_tiles(user, worklist)

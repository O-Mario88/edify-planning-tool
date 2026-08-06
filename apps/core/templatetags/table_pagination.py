"""`{% paginate %}` — bound a table to one page from inside the template.

Wiring 143 tables by refactoring 109 views is the thorough fix and a very large
one. This is the small change that gets each table bounded consistently now:

    {% load table_pagination %}
    {% paginate schools "schools_page" as page %}
    <table>{% for row in page.rows %}…{% endfor %}</table>
    {% include "components/table_pager.html" with pager=page param="schools_page" %}

It bounds what is *rendered*, not what is *fetched*. For a list the view has
already loaded into context — which is most of these — that is the whole cost
of the problem. Where a list is genuinely large the queryset should be paged in
the view as well, and `apps/system_health/table_inventory.py` names those.

The page number comes from the request, so each table on a page needs its own
parameter; passing the same one to two tables would move both at once.
"""

from __future__ import annotations

from django import template

from apps.core.pagination import paginate_rows

register = template.Library()


@register.simple_tag(takes_context=True)
def paginate(context, rows, param="page", page_size=None):
    """One page of `rows`, with everything the shared pager needs."""
    request = context.get("request")
    raw = ""
    if request is not None:
        raw = request.GET.get(param, "")
    try:
        page = max(1, int(raw or 1))
    except (TypeError, ValueError):
        page = 1

    from apps.core.pagination import TABLE_PAGE_SIZE

    return paginate_rows(rows or [], page=page, page_size=page_size or TABLE_PAGE_SIZE)


@register.simple_tag(takes_context=True)
def pager_query(context, param):
    """Every current query parameter except this table's own page.

    So paging one table keeps the period, the district and the search someone
    already chose, and never carries another table's page number along with it.
    """
    request = context.get("request")
    if request is None:
        return ""
    pairs = [
        (key, value)
        for key, value in request.GET.items()
        if value and key != param and not key.endswith("_page")
    ]
    if not pairs:
        return ""
    from urllib.parse import urlencode

    return urlencode(pairs) + "&"

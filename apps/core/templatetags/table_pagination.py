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

    # Not `rows or []`: the truth test of a QuerySet fetches every row, which
    # undid the database paging `paginate_rows` does for one. A missing
    # context variable arrives as the template engine's empty string.
    if rows is None or isinstance(rows, str):
        rows = []
    return paginate_rows(rows, page=page, page_size=page_size or TABLE_PAGE_SIZE)


@register.simple_tag(takes_context=True)
def pager_query(context, param):
    """Every current query parameter except this table's own page.

    So paging one table keeps the period, the district and the search someone
    already chose, including repeated multi-select filters and other tables' pages.
    """
    request = context.get("request")
    if request is None:
        return ""
    pairs = [
        (key, value)
        for key, values in request.GET.lists()
        for value in values
        if value and key != param
    ]
    if not pairs:
        return ""
    from urllib.parse import urlencode

    return urlencode(pairs) + "&"


@register.simple_tag
def tab_values(rows, key="id"):
    """The ids a tab strip may hold, as a JSON array for `tabState`.

    A tab strip and its tables are two halves of one thing: the strip decides
    which table is on screen and the pager decides which page of it. The strip
    lives in the browser, so its choice reaches the server only as a query
    parameter — and only a value the strip actually offers may be honoured.
    Without that check a Country Director who paged one Lead's officer and
    then opened a different Lead saw an empty panel, because the officer id in
    the URL belonged to somebody else's team.

    Each id is rendered exactly as ``{{ row.id }}`` renders it in the panel's
    own `x-show`, `str()` and all — a group with no id at all (the "Unassigned"
    fold on the country lens) is written "None" on both sides. Anything else
    and that group's tab would be the one tab nothing could select.

    The output is escaped by Django and decoded again by the HTML parser, so
    it is read inside an attribute as ordinary JSON.
    """
    from json import dumps

    def value(row):
        if isinstance(row, dict):
            return row.get(key)
        return getattr(row, key, None)

    return dumps([str(value(row)) for row in rows or []])


@register.simple_tag(takes_context=True)
def carry_query(context, *drop):
    """Every current query parameter except *drop*, as `&key=value` pairs.

    For a fragment the page fetches for itself: without this, a table inside
    one arrives at page one whatever page the reader asked for, because the
    fragment's own URL never carried the page number.
    """
    request = context.get("request")
    if request is None:
        return ""
    dropped = set(drop)
    pairs = [
        (key, value)
        for key, values in request.GET.lists()
        for value in values
        if value and key not in dropped
    ]
    if not pairs:
        return ""
    from urllib.parse import urlencode

    return "&" + urlencode(pairs)


@register.simple_tag
def page_param(base, *parts) -> str:
    """A page parameter unique to one instance of a repeated table.

    A table drawn inside a loop is several tables sharing one template, and one
    parameter between them moves all of them at once. The loop's own key — a
    counter, a staff id, a section slug — makes each instance's parameter its
    own:

        {% templatetag openblock %} page_param "members" forloop.counter as members_param {% templatetag closeblock %}
        {% templatetag openblock %} paginate group.members members_param as members_page {% templatetag closeblock %}

    Positional rather than baked into `paginate`, because the caller is the only
    one who knows which key distinguishes their instances.
    """
    return "-".join(
        [str(base)] + [str(part) for part in parts if part not in (None, "")]
    )

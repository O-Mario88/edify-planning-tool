"""
Pagination matching the NestJS `Paginated<T>` envelope.

Input:  `?page=1&pageSize=25&sortBy=<field>&sortDir=asc|desc`
Output: `{data: [...], page, pageSize, total, totalPages}`

Mirrors `PaginationDto` (1-based page, default 25, max 200; `skip`/`take` are
derived and explicitly ignored if sent inbound). Response arrays must never be
null/undefined — the frontend surfaces a DATA_CONTRACT_VIOLATION otherwise.
"""

from collections.abc import Sequence

from django.db.models import QuerySet
from rest_framework.pagination import BasePagination
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.serializer_helpers import ReturnList


class EdifyPagination(BasePagination):
    page_query_param = "page"
    page_size_query_param = "pageSize"
    sort_by_query_param = "sortBy"
    sort_dir_query_param = "sortDir"

    default_page_size = 25
    max_page_size = 200

    def paginate_queryset(self, queryset, request: Request, view=None):
        self._request = request
        self._page = self._get_int(request, self.page_query_param, default=1, minimum=1)
        self._page_size = self._get_int(
            request,
            self.page_size_query_param,
            default=self.default_page_size,
            minimum=1,
            maximum=self.max_page_size,
        )

        sort_by = request.query_params.get(self.sort_by_query_param)
        sort_dir = (
            request.query_params.get(self.sort_dir_query_param) or "asc"
        ).lower()
        if sort_by:
            prefix = "-" if sort_dir == "desc" else ""
            # Defensive: only allow simple field names (no `__`, no relations)
            # to avoid injection via arbitrary ORM ordering. Relations can use
            # `field__related` once whitelisted per-view.
            if sort_by.replace("_", "").replace(".", "").isalnum():
                queryset = queryset.order_by(f"{prefix}{sort_by}")

        self._total = queryset.count()
        offset = (self._page - 1) * self._page_size
        self._list = list(queryset[offset : offset + self._page_size])  # noqa: E203
        return self._list

    def get_paginated_response(self, data) -> Response:
        total_pages = (self._total + self._page_size - 1) // self._page_size or 1
        return Response(
            {
                "data": data,
                "page": self._page,
                "pageSize": self._page_size,
                "total": self._total,
                "totalPages": total_pages,
            }
        )

    def get_paginated_response_schema(self, schema):
        return {
            "type": "object",
            "properties": {
                "data": {"type": "array", "items": schema},
                "page": {"type": "integer"},
                "pageSize": {"type": "integer"},
                "total": {"type": "integer"},
                "totalPages": {"type": "integer"},
            },
        }

    @staticmethod
    def _get_int(
        request: Request,
        param: str,
        *,
        default: int,
        minimum: int | None = None,
        maximum: int | None = None,
    ) -> int:
        raw = request.query_params.get(param)
        if raw in (None, ""):
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        if minimum is not None:
            value = max(minimum, value)
        if maximum is not None:
            value = min(maximum, value)
        return value

    def get_results(self):
        # For nested-routers / convenience.
        if isinstance(self._list, ReturnList):
            return list(self._list)
        return self._list


def make_pagination_window(
    current_page: int, total_pages: int, window_size: int = 2
) -> list[int | str]:
    """
    Constructs a sliding-window pagination list of pages.
    e.g., [1, 2, 3, '...', 40] or [1, '...', 9, 10, 11, '...', 40]
    """
    if total_pages <= 7:
        return list(range(1, total_pages + 1))

    pages = []
    pages.append(1)

    if current_page - window_size > 2:
        pages.append("...")
        for p in range(current_page - window_size, current_page):
            pages.append(p)
    else:
        for p in range(2, current_page):
            pages.append(p)

    if current_page != 1:
        pages.append(current_page)

    if current_page + window_size < total_pages - 1:
        for p in range(current_page + 1, current_page + window_size + 1):
            pages.append(p)
        pages.append("...")
    else:
        for p in range(current_page + 1, total_pages):
            pages.append(p)

    if total_pages not in pages:
        pages.append(total_pages)

    return pages


#: The token a page list uses for a gap. Django's elided range yields its own
#: Unicode ellipsis; the directory, staff, cluster and core-school pagers
#: compare against this ASCII token, so a gap rendered as a page button that
#: submitted page=… and reset the list (controls audit F-02, 2026-09-14).
PAGE_GAP = "..."


def elided_page_numbers(page_obj, *, on_each_side: int = 1, on_ends: int = 1):
    """The page numbers to show around `page_obj`, gaps as PAGE_GAP."""
    return [
        number if isinstance(number, int) else PAGE_GAP
        for number in page_obj.paginator.get_elided_page_range(
            page_obj.number, on_each_side=on_each_side, on_ends=on_ends
        )
    ]


# ── Table pagination (server-rendered pages, not the DRF envelope above) ─────
#
# Started on My Plan and now shared. A table with no bound grows with the data
# behind it, so two cards side by side end up different heights and the page
# scrolls for reasons nobody chose. Every table shows ten rows and the rest sit
# behind pages.
#
# The page count is not a fixed window -- it runs to the end of the data, so a
# person who planned three weeks gets three weeks of pages and one who planned
# three months gets three months. Nothing is hidden behind a filter somebody
# has to discover.
#
# Bounding what is *rendered* is not the same as bounding what is *fetched*.
# Where a view already loads the whole list into context this makes the page
# readable at no extra cost; where a list is genuinely large the queryset
# should be paged in the view too, and
# `apps/system_health/table_inventory.py` is what tells you which those are.

TABLE_PAGE_SIZE = 10


def paginate_rows(rows: list, page: int = 1, page_size: int = TABLE_PAGE_SIZE) -> dict:
    """One card's slice, plus what the template needs to draw its pager.

    Out-of-range pages clamp rather than erroring: a stale link from a card
    that has since emptied should show the last real page, not a 404 in the
    middle of a working list.
    """
    # A sized sequence that is not already in memory (a lazily built table,
    # such as apps.my_plan.past_due_service.PastDueRows) is sliced rather
    # than materialised, so only the page on show is built.
    #
    # An unevaluated QuerySet is paged in the database the same way: COUNT for
    # the total, LIMIT/OFFSET for the page. `list(queryset)` fetched every row
    # to draw ten — on the Blocked Closures page at 50,000 schools that was
    # every blocker in the country, each with its activity and school joined.
    if isinstance(rows, QuerySet) and rows._result_cache is None:
        total = rows.count()
    else:
        if not (
            isinstance(rows, Sequence) and not isinstance(rows, (list, tuple, str))
        ):
            rows = list(rows)
        total = len(rows)
    page_size = max(1, int(page_size or TABLE_PAGE_SIZE))
    page_count = max(1, -(-total // page_size))  # ceiling division
    current = min(max(1, int(page or 1)), page_count)

    start = (current - 1) * page_size
    window = rows[start : start + page_size] if total else []
    if isinstance(window, QuerySet):
        window = list(window)

    return {
        "rows": window,
        "page": current,
        "page_count": page_count,
        "page_size": page_size,
        "total": total,
        "has_previous": current > 1,
        "has_next": current < page_count,
        "previous_page": current - 1,
        "next_page": current + 1,
        # Both ends are 1-based and inclusive, for "11–20 of 47".
        "first_index": start + 1 if window else 0,
        "last_index": start + len(window),
        # A single page needs no pager at all; saying so here keeps the
        # decision out of the template.
        "paginated": page_count > 1,
        # One adjacent page on either side keeps the shared table pager small
        # enough for a phone without hiding the first or last page.
        "pages": make_pagination_window(current, page_count, window_size=1),
    }
